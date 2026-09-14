"""Read-only committed-record coverage for recovery graphs.

Coverage is the inclusion of source-observed immutable commit facts in one
verified snapshot. Dataset revision, UUID order, rowid, and caller flags are
not proof. Public payloads omit keys, actors, result text, and paths.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from finjuice.pipeline.storage.authority import (
    ActivationEvidenceProvider,
    AuthorityPaths,
    RepositoryAuthority,
    require_repository_binding,
    resolve_storage_authority,
    shared_write_lease,
)
from finjuice.pipeline.storage.sqlite.backup import DATABASE_BASENAME
from finjuice.pipeline.storage.sqlite.backup_io import read_regular_bytes
from finjuice.pipeline.storage.sqlite.backup_verify import resolve_backup_input
from finjuice.pipeline.storage.sqlite.errors import BackupVerificationError
from finjuice.pipeline.storage.sqlite.objects import _assert_no_symlink_ancestors
from finjuice.pipeline.storage.sqlite.recovery_bundle import ExpectedRecoveryGraph
from finjuice.pipeline.storage.sqlite.schema import SQLITE_SCHEMA_VERSION, _resolve_schema_version

_ERROR = "Committed backup coverage could not be verified."
_CHUNK = 256
CoverageStatus = Literal[
    "covered",
    "pending",
    "verification_failed",
    "unknown",
    "transfer_failed",
]
FactKind = Literal["receipt", "changeset", "entry", "audit", "asset_meaning"]


@dataclass(frozen=True)
class CommittedFact:
    """One immutable commit fact compared by identity and canonical content."""

    kind: FactKind
    identity_digest: str
    content_digest: str
    commit_digest: str
    committed_revision: int | None


@dataclass(frozen=True)
class CommitObservation:
    """Pinned committed-fact set from one SQLite snapshot."""

    generation: str
    schema_version: int
    dataset_revision: int
    facts: tuple[CommittedFact, ...]
    coverage_digest: str
    observed_at: str

    def identity_map(self) -> dict[str, str]:
        """Return identity digest to content digest; duplicates must already match."""
        mapping: dict[str, str] = {}
        for fact in self.facts:
            previous = mapping.get(fact.identity_digest)
            if previous is not None and previous != fact.content_digest:
                raise BackupVerificationError(_ERROR)
            mapping[fact.identity_digest] = fact.content_digest
        return mapping


@dataclass(frozen=True)
class SourceObservation:
    """Independently verified source snapshot of committed records."""

    activation_sha256: str
    enrollment_digest: str
    generation: str
    schema_version: int
    dataset_revision: int
    facts: tuple[CommittedFact, ...]
    coverage_digest: str
    observed_at: str
    receipt_count: int

    def commit_set(self) -> CommitObservation:
        """Return the committed-fact set without source authority fields."""
        return CommitObservation(
            self.generation,
            self.schema_version,
            self.dataset_revision,
            self.facts,
            self.coverage_digest,
            self.observed_at,
        )


@dataclass(frozen=True)
class CoverageComparison:
    """Inclusion result for one source observation against one graph snapshot."""

    status: CoverageStatus
    pending_commit_count: int | None
    source_revision: int
    graph_revision: int | None
    graph_digest: str | None
    snapshot_manifest_digest: str | None
    copy_id: str | None
    coverage_as_of: str
    missing_commits: frozenset[str] | None = None


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _fact(kind: FactKind, identity: Any, content: Any) -> CommittedFact:
    changeset_id = identity.get("changeset_id", content.get("changeset_id"))
    return CommittedFact(
        kind,
        _sha(_canonical(identity)),
        _sha(_canonical(content)),
        _sha(_canonical({"changeset_id": changeset_id})),
        content.get("committed_revision"),
    )


def _connect_reader(database: Path) -> sqlite3.Connection:
    _assert_no_symlink_ancestors(database)
    if database.is_symlink() or not database.is_file():
        raise BackupVerificationError(_ERROR)
    uri = f"{database.resolve().as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=5.0, isolation_level=None)
    connection.execute("PRAGMA query_only = ON")
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def _fetch_keyed(
    connection: sqlite3.Connection, sql: str, initial: tuple[Any, ...]
) -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    cursor = initial
    while True:
        chunk = connection.execute(sql, (*cursor, _CHUNK)).fetchall()
        rows.extend(chunk)
        if len(chunk) < _CHUNK:
            return rows
        cursor = (chunk[-1][0],)


def _fetch_entries(connection: sqlite3.Connection) -> list[tuple[Any, ...]]:
    sql = (
        "SELECT changeset_id, entry_index, entity_kind, entity_id, action, "
        "before_json, after_json FROM changeset_entries "
        "WHERE changeset_id > ? OR (changeset_id = ? AND entry_index > ?) "
        "ORDER BY changeset_id, entry_index LIMIT ?"
    )
    rows: list[tuple[Any, ...]] = []
    changeset_id, entry_index = "", -1
    while True:
        chunk = connection.execute(
            sql, (changeset_id, changeset_id, entry_index, _CHUNK)
        ).fetchall()
        rows.extend(chunk)
        if len(chunk) < _CHUNK:
            return rows
        changeset_id, entry_index = str(chunk[-1][0]), int(chunk[-1][1])


def _load_facts(connection: sqlite3.Connection) -> tuple[CommittedFact, ...]:
    receipts = _fetch_keyed(
        connection,
        "SELECT changeset_id, command_scope, idempotency_key, request_digest, "
        "result_json, base_revision, committed_revision, state_changed, created_at "
        "FROM idempotency_requests WHERE status = 'committed' AND changeset_id > ? "
        "ORDER BY changeset_id LIMIT ?",
        ("",),
    )
    changesets = _fetch_keyed(
        connection,
        "SELECT changeset_id, command_scope, payload_digest, base_revision, "
        "committed_revision, state_changed, confirmation_json, "
        "reversal_of_changeset_id, created_at, idempotency_key, actor, reason "
        "FROM changesets WHERE changeset_id > ? ORDER BY changeset_id LIMIT ?",
        ("",),
    )
    entries = _fetch_entries(connection)
    audits = _fetch_keyed(
        connection,
        "SELECT audit_event_id, changeset_id, event_kind, event_json, created_at "
        "FROM audit_events WHERE audit_event_id > ? ORDER BY audit_event_id LIMIT ?",
        ("",),
    )
    facts: list[CommittedFact] = []
    if connection.execute("PRAGMA user_version").fetchone()[0] >= 7:
        cursor = connection.execute("SELECT * FROM asset_meaning_assertions ORDER BY assertion_id")
        names = [column[0] for column in cursor.description]
        for row in cursor:
            content = dict(zip(names, row, strict=True))
            content["changeset_id"] = content["created_changeset_id"]
            facts.append(_fact("asset_meaning", {"assertion_id": content["assertion_id"]}, content))
    receipt_changes = set()
    for row in receipts:
        receipt_changes.add(row[0])
        facts.append(
            _fact(
                "receipt",
                {"command_scope": row[1], "idempotency_key": row[2]},
                {
                    "changeset_id": row[0],
                    "request_digest": row[3],
                    "result_digest": _sha(str(row[4]).encode("utf-8")),
                    "base_revision": row[5],
                    "committed_revision": row[6],
                    "state_changed": int(row[7]),
                    "created_at": row[8],
                },
            )
        )
    changeset_ids = set()
    for row in changesets:
        changeset_ids.add(row[0])
        facts.append(
            _fact(
                "changeset",
                {"changeset_id": row[0]},
                {
                    "command_scope": row[1],
                    "payload_digest": row[2],
                    "base_revision": row[3],
                    "committed_revision": row[4],
                    "state_changed": int(row[5]),
                    "confirmation_digest": None if row[6] is None else _sha(str(row[6]).encode()),
                    "reversal_of_changeset_id": row[7],
                    "created_at": row[8],
                    "idempotency_key": row[9],
                    "actor": row[10],
                    "reason": row[11],
                },
            )
        )
    for row in entries:
        facts.append(
            _fact(
                "entry",
                {"changeset_id": row[0], "entry_index": int(row[1])},
                {
                    "entity_kind": row[2],
                    "entity_id": row[3],
                    "action": row[4],
                    "before_digest": None if row[5] is None else _sha(str(row[5]).encode()),
                    "after_digest": None if row[6] is None else _sha(str(row[6]).encode()),
                },
            )
        )
    audit_changes = set()
    for row in audits:
        audit_changes.add(row[1])
        facts.append(
            _fact(
                "audit",
                {"audit_event_id": row[0], "changeset_id": row[1]},
                {
                    "event_kind": row[2],
                    "event_digest": _sha(str(row[3]).encode()),
                    "created_at": row[4],
                },
            )
        )
    if receipt_changes != changeset_ids or audit_changes != changeset_ids:
        raise BackupVerificationError(_ERROR)
    ordered = tuple(sorted(facts, key=lambda item: (item.kind, item.identity_digest)))
    return ordered


def _coverage_digest(facts: tuple[CommittedFact, ...]) -> str:
    body = [{"c": item.content_digest, "i": item.identity_digest, "k": item.kind} for item in facts]
    return _sha(_canonical(body))


def _read_commit_set(
    database: Path, *, schema_version: int = SQLITE_SCHEMA_VERSION
) -> CommitObservation:
    _resolve_schema_version(schema_version)
    connection = _connect_reader(database)
    try:
        connection.execute("BEGIN")
        row = connection.execute(
            "SELECT dataset_generation, schema_version, dataset_revision "
            "FROM repository_meta WHERE singleton = 1"
        ).fetchone()
        if row is None or row[1] != schema_version:
            raise BackupVerificationError(_ERROR)
        facts = _load_facts(connection)
        observed_at = _utc_now()
        return CommitObservation(
            str(row[0]),
            int(row[1]),
            int(row[2]),
            facts,
            _coverage_digest(facts),
            observed_at,
        )
    finally:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        connection.close()


def observe_source_commits(
    data_dir: Path,
    expected: ExpectedRecoveryGraph,
    evidence_provider: ActivationEvidenceProvider,
    *,
    timeout_ms: int = 5_000,
) -> SourceObservation:
    """Read committed facts under verified activation and one SQLite snapshot."""
    from finjuice.pipeline.storage.sqlite.recovery_store import enrollment_digest

    paths = AuthorityPaths.for_data_dir(data_dir)
    with shared_write_lease(paths, timeout_ms=timeout_ms):
        dispatch = resolve_storage_authority(data_dir, evidence_provider)
        if not isinstance(dispatch.authority, RepositoryAuthority):
            raise BackupVerificationError(_ERROR)
        if dispatch.evidence != expected.activation_evidence:
            raise BackupVerificationError(_ERROR)
        raw = read_regular_bytes(paths.activation)
        if _sha(raw) != expected.activation_sha256:
            raise BackupVerificationError(_ERROR)
        authority = require_repository_binding(paths, expected.activation_evidence)
        live_generation = dispatch.authority.activation.dataset_generation
        if authority.activation.dataset_generation != live_generation:
            raise BackupVerificationError(_ERROR)
        observed = _read_commit_set(authority.paths.database)
        if observed.generation != authority.activation.dataset_generation:
            raise BackupVerificationError(_ERROR)
        if observed.schema_version != authority.activation.sqlite_schema_version:
            raise BackupVerificationError(_ERROR)
        if observed.dataset_revision < authority.activation.dataset_revision:
            raise BackupVerificationError(_ERROR)
        receipts = tuple(item for item in observed.facts if item.kind == "receipt")
        return SourceObservation(
            expected.activation_sha256,
            enrollment_digest(expected),
            observed.generation,
            observed.schema_version,
            observed.dataset_revision,
            observed.facts,
            observed.coverage_digest,
            observed.observed_at,
            len(receipts),
        )


def read_graph_commits(
    bundle: Path,
    *,
    snapshot_generation: str,
    snapshot_schema_version: int,
    snapshot_revision: int,
) -> CommitObservation:
    """Read committed facts from one graph snapshot already verified by the caller."""
    selected, _manifest, _layout = resolve_backup_input(bundle / "snapshot")
    observed = _read_commit_set(
        selected / DATABASE_BASENAME, schema_version=snapshot_schema_version
    )
    if (
        observed.generation != snapshot_generation
        or observed.schema_version != snapshot_schema_version
        or observed.dataset_revision != snapshot_revision
    ):
        raise BackupVerificationError(_ERROR)
    return observed


def compare_commit_coverage(
    source: CommitObservation | SourceObservation,
    graph: CommitObservation | None,
    *,
    graph_digest: str | None = None,
    snapshot_manifest_digest: str | None = None,
    copy_id: str | None = None,
) -> CoverageComparison:
    """Compare source facts against one graph. Conflicts are not covered."""
    source_set = source.commit_set() if isinstance(source, SourceObservation) else source

    def result(status: CoverageStatus, missing: frozenset[str] | None) -> CoverageComparison:
        return CoverageComparison(
            status,
            None if missing is None else len(missing),
            source_set.dataset_revision,
            None if graph is None else graph.dataset_revision,
            graph_digest,
            snapshot_manifest_digest,
            copy_id,
            source_set.observed_at,
            missing,
        )

    try:
        source_map = source_set.identity_map()
        graph_map = {} if graph is None else graph.identity_map()
    except BackupVerificationError:
        return result("verification_failed", None)
    if graph is not None and (
        graph.generation != source_set.generation
        or graph.schema_version != source_set.schema_version
    ):
        return result("verification_failed", None)
    if any(
        identity in graph_map and graph_map[identity] != digest
        for identity, digest in source_map.items()
    ):
        return result("verification_failed", None)
    missing = frozenset(
        fact.commit_digest for fact in source_set.facts if fact.identity_digest not in graph_map
    )
    return result("pending" if missing else "covered", missing)


def graph_covers_source(source: CommitObservation, graph: CommitObservation) -> bool:
    """Return True when one graph contains every source fact with matching content."""
    return compare_commit_coverage(source, graph).status == "covered"


def coverage_relation(
    left: CommitObservation, right: CommitObservation
) -> Literal["equal", "left_contains", "right_contains", "incomparable", "conflict"]:
    """Compare two graph commit sets for retention without using revision alone."""
    try:
        left_map = left.identity_map()
        right_map = right.identity_map()
    except BackupVerificationError:
        return "conflict"
    identities = set(left_map) | set(right_map)
    left_only = False
    right_only = False
    for identity in identities:
        left_digest = left_map.get(identity)
        right_digest = right_map.get(identity)
        if left_digest is not None and right_digest is not None and left_digest != right_digest:
            return "conflict"
        if left_digest is not None and right_digest is None:
            left_only = True
        if right_digest is not None and left_digest is None:
            right_only = True
    if left_only and right_only:
        return "incomparable"
    if left_only:
        return "left_contains"
    if right_only:
        return "right_contains"
    return "equal"


def select_covering_copy(
    source: CommitObservation,
    candidates: tuple[tuple[str, CommitObservation, str, str], ...],
) -> tuple[str, CommitObservation, str, str] | None:
    """Return one copy whose single graph contains every source-observed fact."""
    covering = [item for item in candidates if graph_covers_source(source, item[1])]
    if not covering:
        return None
    return max(
        covering,
        key=lambda item: (item[1].dataset_revision, item[1].observed_at, item[0]),
    )


def select_retention_latest(
    copies: tuple[tuple[str, datetime, CommitObservation | None], ...],
) -> tuple[str | None, frozenset[str]]:
    """Pick the graph that contains the newest facts; retain unresolved copies.

    Returns ``(latest_id, unresolved_ids)``. Unresolved IDs are kept for this
    plan without becoming durable baselines. Equal coverage still ties on
    timestamp then copy identity so identical snapshots can age out.
    """
    readable = [item for item in copies if item[2] is not None]
    unresolved = {item[0] for item in copies if item[2] is None}
    for index, (left_id, _left_time, left) in enumerate(readable):
        assert left is not None
        for right_id, _right_time, right in readable[index + 1 :]:
            assert right is not None
            relation = coverage_relation(left, right)
            if relation in {"conflict", "incomparable"}:
                unresolved.add(left_id)
                unresolved.add(right_id)
    clean = [item for item in readable if item[0] not in unresolved]
    if not clean:
        return None, frozenset(unresolved)
    maximal: list[tuple[str, datetime, CommitObservation]] = []
    for copy_id, created_at, observation in clean:
        assert observation is not None
        contained = any(
            coverage_relation(observation, other[2]) == "right_contains"
            for other in clean
            if other[0] != copy_id and other[2] is not None
        )
        if not contained:
            maximal.append((copy_id, created_at, observation))
    if not maximal:
        return None, frozenset(unresolved)
    digests = {item[2].coverage_digest for item in maximal}
    if len(digests) != 1:
        unresolved.update(item[0] for item in maximal)
        return None, frozenset(unresolved)
    latest = max(maximal, key=lambda item: (item[1], item[0]))[0]
    return latest, frozenset(unresolved)


def recording_from_observation(
    source: SourceObservation,
    *,
    changeset_id: str,
    committed_revision: int,
    replayed: bool,
) -> dict[str, Any] | None:
    """Confirm a public mutation receipt against source-observed committed facts."""
    matches = [
        fact
        for fact in source.facts
        if fact.kind == "changeset"
        and fact.identity_digest == _sha(_canonical({"changeset_id": changeset_id}))
    ]
    if len(matches) != 1 or matches[0].committed_revision != committed_revision:
        return None
    receipts = [
        fact
        for fact in source.facts
        if fact.kind == "receipt"
        and fact.commit_digest == matches[0].commit_digest
        and fact.committed_revision == committed_revision
    ]
    if not receipts:
        return None
    return {
        "status": "committed",
        "changeset_id": changeset_id,
        "committed_revision": committed_revision,
        "replayed": replayed,
    }
