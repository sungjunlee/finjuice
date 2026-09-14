"""Plan, build, and verify frozen-source preservation migration."""

from __future__ import annotations

import json
import os
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

from finjuice.pipeline.migrate.encoding import (
    canonical_bytes,
    digest_text,
    hex_digest,
    load_json_object,
    sha256_bytes,
)
from finjuice.pipeline.migrate.errors import invalid
from finjuice.pipeline.migrate.inventory import (
    capture_hex,
    capture_to_dict,
    captured_byte_count,
    expand_planned_inputs,
    iter_role_entries,
    load_capture_manifest,
    preflight_space,
    reject_overlap,
    require_outside_repo,
    revalidate_capture,
)
from finjuice.pipeline.migrate.mapping import (
    map_absent,
    map_config_file,
    map_csv_entry,
    map_opaque_file,
    map_transaction_row,
)
from finjuice.pipeline.migrate.mapping_overview import (
    map_asset_snapshot_row,
    map_overview_balance_row,
    map_overview_cashflow_row,
    map_overview_fact_row,
    map_overview_insurance_row,
    map_overview_investment_row,
    map_overview_loan_row,
)
from finjuice.pipeline.migrate.preserve import (
    parse_tag_sequence,
    split_hidden_category,
    unknown_fields,
)
from finjuice.pipeline.migrate.records import BuildState, add_origin_revision
from finjuice.pipeline.migrate.types import (
    COMPLETION_MARKER,
    MIGRATION_KIND,
    MIGRATION_MANIFEST_FILENAME,
    ORIGIN_KIND,
    SCHEMA_VERSION,
    CaptureManifest,
    MigrationPlan,
    MigrationResult,
    PlannedInput,
)
from finjuice.pipeline.storage.csv_schema import CSV_COLUMNS
from finjuice.pipeline.storage.sqlite import (
    GenerationPaths,
    RepositoryBuilder,
    RepositoryReader,
    migration_entity_id,
)

_CONFIG_KIND = {
    "rules": "rules",
    "goals": "goals",
    "assets": "assets",
    "scenarios": "scenarios",
    "overlay": "other",
}
_CSV_HANDLERS = {
    "transaction_partition": map_transaction_row,
    "overview_facts": map_overview_fact_row,
    "overview_balance": map_overview_balance_row,
    "overview_cashflow": map_overview_cashflow_row,
    "overview_insurance": map_overview_insurance_row,
    "overview_investment": map_overview_investment_row,
    "overview_loan": map_overview_loan_row,
    "asset_snapshot": map_asset_snapshot_row,
}
_FILE_ROLE_ORDER = (
    "rules",
    "goals",
    "assets",
    "scenarios",
    "overlay",
    "source_workbook",
    "import_history",
    "audit_history",
    "overview_facts",
    "overview_balance",
    "overview_cashflow",
    "overview_insurance",
    "overview_investment",
    "overview_loan",
    "asset_snapshot",
    "transaction_partition",
    "unclassified",
)


def notify_build_progress(stage: str) -> None:
    """Hook for tests to inject interruption; production is a no-op."""
    return None


def plan_migration(capture_manifest: Path) -> MigrationPlan:
    """Inventory captured inputs and expected dispositions without writing the source.

    Args:
        capture_manifest: Path to a frozen capture manifest.

    Returns:
        A plan whose IDs depend only on the capture digest and locators.
    """
    path = require_outside_repo(capture_manifest, context="capture manifest")
    capture = load_capture_manifest(path)
    revalidate_capture(capture)
    plan = MigrationPlan(
        capture_digest=capture.canonical_digest,
        frozen_root=capture.frozen_root,
        capture_path=path,
        inputs=expand_planned_inputs(capture),
        extra_roots=dict(capture.extra_roots),
    )
    notify_build_progress("plan")
    return plan


def write_plan(plan: MigrationPlan, path: Path) -> Path:
    """Write a plan JSON file outside the frozen source."""
    destination = require_outside_repo(path, context="migration plan")
    reject_overlap(plan.frozen_root, destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        **plan.to_public_dict(),
        "frozen_root": str(plan.frozen_root),
        "capture_path": str(plan.capture_path) if plan.capture_path else None,
        "extra_roots": dict(plan.extra_roots),
        "inputs": [
            {
                "logical_role": item.logical_role,
                "relative_path": item.relative_path,
                "record_kind": item.record_kind,
                "ordinal": item.ordinal,
                "expected_disposition": item.expected_disposition,
                "sha256": item.sha256,
            }
            for item in plan.inputs
        ],
    }
    destination.write_text(canonical_bytes(payload).decode("utf-8") + "\n", encoding="utf-8")
    return destination


def load_plan(path: Path) -> MigrationPlan:
    """Load a previously written plan."""
    payload = load_json_object(path)
    inputs = [
        PlannedInput(
            logical_role=str(item["logical_role"]),
            relative_path=item.get("relative_path"),
            record_kind=str(item["record_kind"]),
            ordinal=item.get("ordinal"),
            expected_disposition=item["expected_disposition"],
            sha256=item.get("sha256"),
        )
        for item in payload.get("inputs", [])
    ]
    capture_path = payload.get("capture_path")
    return MigrationPlan(
        capture_digest=str(payload["capture_digest"]),
        frozen_root=require_outside_repo(
            Path(str(payload["frozen_root"])),
            context="migration source",
        ),
        capture_path=Path(capture_path) if capture_path else None,
        inputs=inputs,
        extra_roots={str(key): str(value) for key, value in payload.get("extra_roots", {}).items()},
    )


def _prepare_empty_staging(path: Path) -> None:
    """Create or tighten a generation root so SQLite storage accepts it as private."""
    if not path.exists():
        path.mkdir(parents=True, mode=0o700)
    os.chmod(path, 0o700)


def _existing_complete(staging: Path, capture_digest: str) -> MigrationResult | None:
    marker = staging / COMPLETION_MARKER
    manifest_path = staging / "manifests" / MIGRATION_MANIFEST_FILENAME
    if not marker.is_file() or not manifest_path.is_file():
        return None
    payload = load_json_object(manifest_path)
    if payload.get("capture_digest") != capture_digest:
        raise invalid("Staging belongs to a different capture digest.")
    return MigrationResult(
        status="already_complete",
        schema_version=SCHEMA_VERSION,
        capture_digest=capture_digest,
        candidate_digest=str(payload.get("candidate_digest")),
        input_count=int(payload.get("input_count", 0)),
        dispositions=dict(payload.get("dispositions", {})),
        unexplained_loss_count=int(payload.get("unexplained_loss_count", 0)),
        issue_count=int(payload.get("issue_count", 0)),
        origin_kind=ORIGIN_KIND,
    )


def _apply_files(state: BuildState, capture: CaptureManifest) -> None:
    for entry in iter_role_entries(capture, _FILE_ROLE_ORDER):
        notify_build_progress(entry.logical_role)
        config_kind = _CONFIG_KIND.get(entry.logical_role)
        if config_kind is not None:
            map_config_file(state, capture, entry, config_kind)
            continue
        handler = _CSV_HANDLERS.get(entry.logical_role)
        if handler is not None:
            map_csv_entry(state, capture, entry, handler)
            continue
        if entry.logical_role == "unclassified":
            map_opaque_file(
                state,
                capture,
                entry,
                reason="Unclassified frozen file quarantined with a cause.",
                disposition="quarantined",
            )
            continue
        map_opaque_file(
            state,
            capture,
            entry,
            reason="Legacy bytes preserved without inventing a complete history.",
        )
    present_roles = {entry.logical_role for entry in capture.present_files()}
    for absent in capture.absent_roles():
        if absent.logical_role not in present_roles:
            map_absent(state, absent.logical_role)


def _semantic_snapshot(database: Path) -> dict[str, Any]:
    with RepositoryReader(database) as reader:
        payload = {
            "transactions": reader.rows("transactions"),
            "accounts": reader.rows("accounts"),
            "exact_values": reader.rows("exact_values"),
            "legacy_payloads": reader.rows("legacy_payloads"),
            "preservation_issues": reader.rows("preservation_issues"),
            "migration_dispositions": reader.rows("migration_dispositions"),
            "legacy_identifiers": reader.rows("legacy_identifiers"),
            "config_revisions": reader.rows("config_revisions"),
            "overview_facts": reader.rows("overview_facts"),
            "overview_balances": reader.rows("overview_balances"),
            "overview_cashflows": reader.rows("overview_cashflows"),
            "overview_insurance": reader.rows("overview_insurance"),
            "overview_investments": reader.rows("overview_investments"),
            "overview_loans": reader.rows("overview_loans"),
            "asset_snapshots": reader.rows("asset_snapshots"),
            "source_artifacts": reader.rows("source_artifacts"),
            "source_occurrences": reader.rows("source_occurrences"),
            "record_provenance": reader.rows("record_provenance"),
            "observations": reader.rows("observations"),
            "resources": reader.rows("resources"),
            "migration_identities": reader.rows("migration_identities"),
        }
    for rows in payload.values():
        rows.sort(key=lambda row: json.dumps(row, sort_keys=True, default=str))
    return payload


def _candidate_digest(database: Path) -> str:
    return digest_text(sha256_bytes(canonical_bytes(_semantic_snapshot(database))))


def _count_unexplained(plan: MigrationPlan, actual: int) -> int:
    return max(0, len(plan.inputs) - actual)


def _write_migration_manifest(
    staging: Path,
    plan: MigrationPlan,
    result: MigrationResult,
    attempt_id: str,
) -> None:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "kind": MIGRATION_KIND,
        "attempt_id": attempt_id,
        "capture_digest": plan.capture_digest,
        "capture_path": str(plan.capture_path) if plan.capture_path else None,
        "candidate_digest": result.candidate_digest,
        "input_count": result.input_count,
        "inputs": [
            {
                "logical_role": item.logical_role,
                "relative_path": item.relative_path,
                "record_kind": item.record_kind,
                "ordinal": item.ordinal,
                "expected_disposition": item.expected_disposition,
                "sha256": item.sha256,
            }
            for item in plan.inputs
        ],
        "dispositions": result.dispositions,
        "unexplained_loss_count": result.unexplained_loss_count,
        "issue_count": result.issue_count,
        "origin_kind": ORIGIN_KIND,
    }
    manifest_path = staging / "manifests" / MIGRATION_MANIFEST_FILENAME
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(canonical_bytes(payload).decode("utf-8") + "\n", encoding="utf-8")
    (staging / COMPLETION_MARKER).write_text(f"{result.candidate_digest}\n", encoding="utf-8")


def build_migration(
    plan: Path | MigrationPlan,
    staging: Path,
    *,
    active_data_dir: Path | None = None,
) -> MigrationResult:
    """Build a new staging repository from a frozen capture. Never writes the source.

    Args:
        plan: Plan object or path written by :func:`write_plan`.
        staging: New empty directory for the candidate generation.
        active_data_dir: Optional live data directory that must not be the target.

    Returns:
        Privacy-safe build result. Repeating a completed build returns
        ``already_complete`` without mutating source or candidate bytes.
    """
    resolved_plan = plan if isinstance(plan, MigrationPlan) else load_plan(plan)
    if resolved_plan.capture_path is None:
        raise invalid("Plan is missing its capture manifest path.")
    capture = load_capture_manifest(resolved_plan.capture_path)
    if capture.canonical_digest != resolved_plan.capture_digest:
        raise invalid("Plan capture digest does not match the capture manifest.")
    staging_path = require_outside_repo(staging, context="migration staging")
    reject_overlap(capture.frozen_root, staging_path)
    if active_data_dir is not None:
        active = require_outside_repo(active_data_dir, context="active data dir")
        reject_overlap(active, staging_path)
    if staging_path.exists():
        existing = _existing_complete(staging_path, resolved_plan.capture_digest)
        if existing is not None:
            return existing
        if any(staging_path.iterdir()):
            raise invalid("Staging is not empty; retry uses a new candidate path.")
    _prepare_empty_staging(staging_path)
    revalidate_capture(capture)
    preflight_space(staging_path.parent, captured_byte_count(capture))
    generation = migration_entity_id(
        capture_hex(capture),
        "dataset_generation",
        {"kind": "generation"},
    )
    paths = GenerationPaths(staging_path)
    attempt_id = str(uuid.uuid4())
    try:
        with RepositoryBuilder(paths, generation) as builder:
            state = BuildState(builder=builder, digest=capture_hex(capture))
            add_origin_revision(state, canonical_bytes(capture_to_dict(capture)))
            notify_build_progress("origin")
            _apply_files(state, capture)
            notify_build_progress("finalize")
            builder.finalize()
    except OSError as exc:
        from finjuice.pipeline.migrate.inventory import raise_io

        raise_io(exc)
        raise
    revalidate_capture(capture)
    disposition_counts: dict[str, int] = {}
    for _, disposition, _reason in state.dispositions:
        disposition_counts[disposition] = disposition_counts.get(disposition, 0) + 1
    unexplained = _count_unexplained(resolved_plan, len(state.dispositions))
    result = MigrationResult(
        status="ok",
        schema_version=SCHEMA_VERSION,
        capture_digest=capture.canonical_digest,
        candidate_digest=_candidate_digest(paths.database),
        input_count=len(state.dispositions),
        dispositions=disposition_counts,
        unexplained_loss_count=unexplained,
        issue_count=state.issues,
        origin_kind=ORIGIN_KIND,
    )
    _write_migration_manifest(staging_path, resolved_plan, result, attempt_id)
    return result


def _check(
    check_id: str,
    *,
    status: str,
    checked_count: int,
    difference_count: int = 0,
    quarantine_count: int = 0,
) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "status": status,
        "checked_count": checked_count,
        "difference_count": difference_count,
        "allowed_difference_count": 0,
        "quarantine_count": quarantine_count,
        "evidence_digest": None,
    }


def _locators_by_provenance(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        row["provenance_id"]: json.loads(row["legacy_locator_json"])
        for row in snapshot["record_provenance"]
    }


def _payload_for_locator(
    relative_path: str | None,
    ordinal: int,
    payload_rows: list[dict[str, Any]],
    locators: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    for item in payload_rows:
        locator = locators.get(item["provenance_id"]) or {}
        if locator.get("relative_path") != relative_path:
            continue
        if locator.get("ordinal") != ordinal:
            continue
        parsed = json.loads(item["payload_json"])
        if not isinstance(parsed, dict):
            return None
        return parsed
    return None


def _payload_record_for_locator(
    relative_path: str | None,
    ordinal: int,
    payload_rows: list[dict[str, Any]],
    locators: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    for item in payload_rows:
        locator = locators.get(item["provenance_id"]) or {}
        if locator.get("relative_path") != relative_path:
            continue
        if locator.get("ordinal") != ordinal:
            continue
        return item
    return None


def _payload_fields(payload: dict[str, Any]) -> dict[str, str]:
    fields = payload.get("fields") or {}
    if not isinstance(fields, dict):
        return {}
    return {str(key): "" if value is None else str(value) for key, value in fields.items()}


def _transaction_plan_items(planned: list[PlannedInput]) -> list[PlannedInput]:
    return [
        item
        for item in planned
        if item.logical_role == "transaction_partition" and item.ordinal is not None
    ]


def _hidden_markers_match(
    planned: list[PlannedInput],
    payload_rows: list[dict[str, Any]],
    locators: dict[str, dict[str, Any]],
) -> bool:
    for item in _transaction_plan_items(planned):
        payload = _payload_for_locator(
            item.relative_path, item.ordinal or 0, payload_rows, locators
        )
        if payload is None:
            return False
        tags, _issue = parse_tag_sequence(_payload_fields(payload).get("tags_manual"))
        _visible, _selected, markers = split_hidden_category(tags)
        if list(payload.get("category_override_markers") or []) != markers:
            return False
    return True


def _persisted_category_match(
    planned: list[PlannedInput],
    transactions: list[dict[str, Any]],
    payload_rows: list[dict[str, Any]],
    locators: dict[str, dict[str, Any]],
) -> bool:
    by_provenance = {row["provenance_id"]: row for row in transactions}
    for item in _transaction_plan_items(planned):
        record = _payload_record_for_locator(
            item.relative_path, item.ordinal or 0, payload_rows, locators
        )
        if record is None:
            return False
        txn = by_provenance.get(record["provenance_id"])
        if txn is None:
            continue
        fields = _payload_fields(json.loads(record["payload_json"]))
        if str(txn.get("category_final") or "") != (fields.get("category_final") or ""):
            return False
        if str(txn.get("category_rule") or "") != (fields.get("category_rule") or ""):
            return False
    return True


def _unknown_fields_match(
    planned: list[PlannedInput],
    payload_rows: list[dict[str, Any]],
    locators: dict[str, dict[str, Any]],
) -> bool:
    known = set(CSV_COLUMNS)
    for item in _transaction_plan_items(planned):
        payload = _payload_for_locator(
            item.relative_path, item.ordinal or 0, payload_rows, locators
        )
        if payload is None:
            return False
        fields = _payload_fields(payload)
        if (payload.get("unknown_fields") or {}) != unknown_fields(fields, known):
            return False
    return True


def _duplicate_hash_ok(snapshot: dict[str, Any], transactions: list[dict[str, Any]]) -> bool:
    transaction_ids = [row["entity_id"] for row in transactions]
    if len(transaction_ids) != len(set(transaction_ids)):
        return False
    txn_set = set(transaction_ids)
    hashes = [
        row["identifier_value"]
        for row in snapshot["legacy_identifiers"]
        if row["identifier_kind"] == "row_hash" and row["entity_id"] in txn_set
    ]
    return len(hashes) == len(transactions)


def _preservation_checks(
    planned: list[PlannedInput],
    snapshot: dict[str, Any],
    transactions: list[dict[str, Any]],
    accounts: list[dict[str, Any]],
) -> tuple[dict[str, Any], ...]:
    payload_rows = snapshot["legacy_payloads"]
    locators = _locators_by_provenance(snapshot)
    txn_items = _transaction_plan_items(planned)
    hidden_count = 0
    unknown_count = 0
    for item in txn_items:
        payload = _payload_for_locator(
            item.relative_path, item.ordinal or 0, payload_rows, locators
        )
        if payload is None:
            continue
        fields = _payload_fields(payload)
        if split_hidden_category(parse_tag_sequence(fields.get("tags_manual"))[0])[2]:
            hidden_count += 1
        if unknown_fields(fields, set(CSV_COLUMNS)):
            unknown_count += 1
    identity_ok = _duplicate_hash_ok(snapshot, transactions)
    return (
        _check(
            "P01",
            status="pass" if identity_ok else "fail",
            checked_count=len(transactions),
        ),
        _check(
            "P02",
            status="pass" if _hidden_markers_match(planned, payload_rows, locators) else "fail",
            checked_count=hidden_count,
        ),
        _check(
            "P03",
            status="pass"
            if _persisted_category_match(planned, transactions, payload_rows, locators)
            else "fail",
            checked_count=len(txn_items),
        ),
        _check(
            "P04",
            status="pass" if _unknown_fields_match(planned, payload_rows, locators) else "fail",
            checked_count=unknown_count,
        ),
        _check("H01", status="pass", checked_count=len(accounts)),
    )


def _matches_planned_locator(item: PlannedInput, locator: dict[str, Any]) -> bool:
    if item.expected_disposition == "intentionally_absent":
        if item.relative_path:
            return locator.get("relative_path") == item.relative_path and "ordinal" not in locator
        return (
            locator.get("logical_role") == item.logical_role
            and locator.get("state") == "intentionally_absent"
        )
    if item.ordinal is not None:
        return (
            locator.get("relative_path") == item.relative_path
            and locator.get("ordinal") == item.ordinal
        )
    return locator.get("relative_path") == item.relative_path and "ordinal" not in locator


def _planned_inputs_from_manifest(payload: dict[str, Any]) -> list[PlannedInput]:
    raw_inputs = payload.get("inputs")
    if not isinstance(raw_inputs, list) or not raw_inputs:
        raise invalid("Migration candidate is missing frozen planned locators.")
    planned: list[PlannedInput] = []
    for item in raw_inputs:
        if not isinstance(item, dict):
            raise invalid("Migration candidate has an invalid planned locator.")
        planned.append(
            PlannedInput(
                logical_role=str(item["logical_role"]),
                relative_path=item.get("relative_path"),
                record_kind=str(item.get("record_kind") or ""),
                ordinal=None if item.get("ordinal") is None else int(item["ordinal"]),
                expected_disposition=item["expected_disposition"],
                sha256=item.get("sha256"),
            )
        )
    return planned


def _locator_coverage(
    planned: list[PlannedInput], snapshot: dict[str, Any]
) -> tuple[bool, int, int]:
    provenances: list[tuple[str, dict[str, Any]]] = []
    for row in snapshot["record_provenance"]:
        provenances.append((row["provenance_id"], json.loads(row["legacy_locator_json"])))
    disposed = {row["provenance_id"] for row in snapshot["migration_dispositions"]}
    used: set[str] = set()
    missing = 0
    for item in planned:
        found: str | None = None
        for provenance_id, locator in provenances:
            if provenance_id in used or provenance_id not in disposed:
                continue
            if not _matches_planned_locator(item, locator):
                continue
            found = provenance_id
            break
        if found is None:
            missing += 1
            continue
        used.add(found)
    return missing == 0, missing, len(planned)


def verify_migration(candidate: Path) -> MigrationResult:
    """Verify a built candidate against its frozen capture, not a live tree."""
    staging = require_outside_repo(candidate, context="migration candidate")
    manifest_path = staging / "manifests" / MIGRATION_MANIFEST_FILENAME
    marker = staging / COMPLETION_MARKER
    if not marker.is_file() or not manifest_path.is_file():
        raise invalid("Migration candidate is incomplete.")
    payload = load_json_object(manifest_path)
    capture_digest = str(payload.get("capture_digest", ""))
    hex_digest(capture_digest)
    capture_path = payload.get("capture_path")
    if not capture_path:
        raise invalid("Migration candidate is missing its capture path.")
    capture = load_capture_manifest(Path(str(capture_path)))
    if capture.canonical_digest != capture_digest:
        raise invalid("Capture digest does not match the frozen capture manifest.")
    database = GenerationPaths(staging).database
    snapshot = _semantic_snapshot(database)
    recomputed = digest_text(sha256_bytes(canonical_bytes(snapshot)))
    stored = str(payload.get("candidate_digest") or "")
    if recomputed != stored:
        raise invalid("Candidate digest does not match the published migration manifest.")
    transactions = snapshot["transactions"]
    accounts = snapshot["accounts"]
    dispositions = snapshot["migration_dispositions"]
    origins = [
        row
        for row in snapshot["config_revisions"]
        if ORIGIN_KIND in str(row.get("canonical_payload_json"))
    ]
    if not origins:
        raise invalid("Candidate is missing the legacy_current_state origin revision.")
    owner_inferred = [row for row in accounts if row["ownership_state"] != "unknown"]
    if owner_inferred:
        raise invalid("Baseline ownership was inferred; migration must keep ownership unknown.")
    planned = _planned_inputs_from_manifest(payload)
    covered, unexplained, planned_count = _locator_coverage(planned, snapshot)
    checks = _preservation_checks(planned, snapshot, transactions, accounts) + (
        _check("I01", status="pass" if covered else "fail", checked_count=planned_count),
    )
    if unexplained:
        raise invalid("Unexplained legacy inputs were not given a disposition.")
    failed = [item for item in checks if item["status"] == "fail"]
    if failed:
        raise invalid("Preservation verification failed.")
    return MigrationResult(
        status="ok",
        schema_version=SCHEMA_VERSION,
        capture_digest=capture_digest,
        candidate_digest=recomputed,
        input_count=len(dispositions),
        dispositions=dict(Counter(row["disposition"] for row in dispositions)),
        unexplained_loss_count=unexplained,
        issue_count=len(snapshot["preservation_issues"]),
        origin_kind=ORIGIN_KIND,
        checks=checks,
    )
