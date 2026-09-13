"""CLI regressions for mutation fences after SQLite authority activation."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

import pytest
from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app
from finjuice.pipeline.cli.output import ErrorCode, ExitCode
from finjuice.pipeline.storage.authority import (
    ActivationEvidence,
    AuthorityPaths,
    StaticActivationEvidenceProvider,
)
from finjuice.pipeline.storage.mutation_facade import (
    ConfigDocument,
    StorageMutationFacade,
)
from finjuice.pipeline.storage.sqlite import RepositoryBuilder, new_entity_id
from finjuice.pipeline.storage.sqlite.schema import SQLITE_SCHEMA_VERSION

_NOW = "2026-09-09T00:00:00Z"


@dataclass(frozen=True)
class _ActiveRoot:
    root: Path
    paths: AuthorityPaths
    evidence: ActivationEvidence
    generation: str

    @property
    def provider(self) -> StaticActivationEvidenceProvider:
        return StaticActivationEvidenceProvider(self.evidence)

    @property
    def facade(self) -> StorageMutationFacade:
        return StorageMutationFacade(self.root, self.provider)

    @property
    def database(self) -> Path:
        return self.paths.generation(self.generation).database


@pytest.fixture
def active_root(tmp_path: Path) -> _ActiveRoot:
    """Create an activated empty repository plus legacy-path sentinels."""
    root = (tmp_path / "data").resolve()
    paths = AuthorityPaths.for_data_dir(root)
    generation = new_entity_id()
    with RepositoryBuilder(paths.generation(generation), generation) as builder:
        builder.finalize()

    evidence = ActivationEvidence(
        installed_release_version="0.7.3",
        installed_release_artifact_sha256="a" * 64,
        verified_migration_manifest_sha256="b" * 64,
        verified_pre_cutover_backup_manifest_sha256="c" * 64,
    )
    paths.control_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    paths.activation.write_text(
        json.dumps(
            {
                "activation_schema_version": 1,
                "release_version": evidence.installed_release_version,
                "release_artifact_sha256": evidence.installed_release_artifact_sha256,
                "dataset_generation": generation,
                "sqlite_schema_version": SQLITE_SCHEMA_VERSION,
                "dataset_revision": 0,
                "migration_manifest_sha256": evidence.verified_migration_manifest_sha256,
                "pre_cutover_backup_manifest_sha256": (
                    evidence.verified_pre_cutover_backup_manifest_sha256
                ),
                "activated_at": _NOW,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    for directory in ("imports", "transactions", "exports", "metadata"):
        (root / directory).mkdir(exist_ok=True)
    for filename in ("rules.yaml", "goals.yaml", "assets.yaml"):
        (root / filename).write_bytes(b"legacy sentinel unchanged\n")

    active = _ActiveRoot(root, paths, evidence, generation)
    with closing(sqlite3.connect(active.database)) as connection:
        assert connection.execute("SELECT count(*) FROM transactions").fetchone() == (0,)
    return active


@pytest.mark.parametrize(
    ("command", "message_fragment"),
    [
        (("init", "--no-git"), "Repository activation is present"),
        (("validate", "--fix"), "Repository activation is present"),
        (("networth", "init"), "Repository activation is present"),
        (
            ("rules", "suggest", "--apply", "--yes"),
            "SQLite repository is active",
        ),
    ],
)
@pytest.mark.parametrize("json_output", [False, True], ids=["human", "json"])
def test_legacy_entrypoints_fail_closed_without_mutating_active_repository(
    active_root: _ActiveRoot,
    command: tuple[str, ...],
    message_fragment: str,
    json_output: bool,
) -> None:
    """Eight human/JSON entry paths must reject legacy writes after activation."""
    before = _authority_state(active_root)
    argv = ["--data-dir", str(active_root.root), *command]
    if json_output:
        argv.append("--json")

    result = CliRunner().invoke(
        app,
        argv,
        obj={"activation_evidence_provider": active_root.provider},
    )

    assert result.exit_code == ExitCode.VALIDATION_ERROR, result.output
    assert result.output.strip()
    assert "Traceback" not in result.output
    if json_output:
        payload = json.loads(result.output)
        assert payload["error"]["code"] == ErrorCode.VALIDATION_FAILED
        assert payload["exit_code"] == ExitCode.VALIDATION_ERROR
        assert message_fragment in payload["error"]["message"]
    else:
        assert message_fragment in result.output
    assert _authority_state(active_root) == before


def test_active_budget_rejects_invalid_update_before_confirmation(
    active_root: _ActiveRoot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Current active config validation must finish before asking to mutate it."""
    _seed_goals(active_root)
    before = _authority_state(active_root)

    def unexpected_confirmation(*args: object, **kwargs: object) -> bool:
        raise AssertionError("invalid budget edit reached confirmation")

    monkeypatch.setattr(
        "finjuice.pipeline.cli.commands.budget.typer.confirm",
        unexpected_confirmation,
    )

    result = _invoke_budget(active_root, "--set", "categories=1")

    assert result.exit_code == ExitCode.USAGE_ERROR, result.output
    assert "Invalid budget key" in result.output
    assert _authority_state(active_root) == before


def test_active_budget_detects_head_change_after_confirmation(
    active_root: _ActiveRoot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A confirmed edit must retain the revision pinned before the prompt."""
    _seed_goals(active_root)
    concurrent_content = _goals_bytes(total=1500)

    def replace_head_then_confirm(*args: object, **kwargs: object) -> bool:
        active_root.facade.replace_config(
            ConfigDocument.from_validated_yaml(
                "goals",
                concurrent_content,
                parser_version="finjuice.goals.v1",
            )
        )
        return True

    monkeypatch.setattr(
        "finjuice.pipeline.cli.commands.budget.typer.confirm",
        replace_head_then_confirm,
    )

    result = _invoke_budget(active_root, "--set", "total=2000")

    assert result.exit_code == ExitCode.VALIDATION_ERROR, result.output
    assert "revision is stale" in result.output
    assert active_root.facade.read_config_bytes("goals") == concurrent_content
    assert (active_root.root / "goals.yaml").read_bytes() == b"legacy sentinel unchanged\n"


def test_active_budget_human_output_names_repository_revision(active_root: _ActiveRoot) -> None:
    """Human success output must identify the active config revision it changed."""
    _seed_goals(active_root)

    result = _invoke_budget(active_root, "--set", "total=2000", "--yes")

    assert result.exit_code == ExitCode.SUCCESS, result.output
    assert "Updated active goals config (revision 2)" in result.output
    assert str(active_root.root / "goals.yaml") not in result.output
    assert (active_root.root / "goals.yaml").read_bytes() == b"legacy sentinel unchanged\n"
    assert active_root.facade.read_config_bytes("goals") == _goals_bytes(total=2000)


def test_active_budget_explicit_replay_ignores_later_opaque_head(active_root: _ActiveRoot) -> None:
    """An exact committed retry returns its receipt before reading current config semantics."""
    _seed_goals(active_root)
    explicit_args = (
        "--set",
        "total=2000",
        "--yes",
        "--json",
        "--idempotency-key",
        "stable-budget-edit",
        "--expected-generation",
        active_root.generation,
        "--expected-revision",
        "1",
    )
    first_result = _invoke_budget(active_root, *explicit_args)
    assert first_result.exit_code == ExitCode.SUCCESS, first_result.output
    first = json.loads(first_result.output)

    opaque_content = b"- preserved unsupported goals source\n"
    active_root.facade.replace_config(
        ConfigDocument(
            config_kind="goals",
            content=opaque_content,
            parsed_status="opaque",
            canonical_payload=None,
            parser_version="synthetic.opaque.v1",
        )
    )
    before_replay = _authority_state(active_root)

    replay_result = _invoke_budget(active_root, *explicit_args)

    assert replay_result.exit_code == ExitCode.SUCCESS, replay_result.output
    replay = json.loads(replay_result.output)
    assert replay["replayed"] is True
    assert replay["changeset_id"] == first["changeset_id"]
    assert replay["committed_revision"] == first["committed_revision"] == 2
    assert active_root.facade.read_config_bytes("goals") == opaque_content
    assert _authority_state(active_root) == before_replay


def test_active_rule_patch_distinguishes_omitted_clear_and_replays_exact_intent(
    active_root: _ActiveRoot,
) -> None:
    initial = b"""version: 1
rules:
  - name: retained
    match: old
    fields: [memo_raw]
    conditions:
      - field: merchant_raw
        op: contains
        value: Coupang
    tags: [old]
    priority: 88
    category: Existing
    notes: keep notes
    custom_id: keep-id
"""
    seeded = active_root.facade.replace_config(
        ConfigDocument.from_validated_yaml(
            "rules",
            initial,
            parser_version="finjuice.rules.v1",
        )
    )
    exact_args = (
        "--name",
        "retained",
        "--match",
        "new",
        "--tags",
        "new-tag",
        "--json",
        "--idempotency-key",
        "stable-rule-patch",
        "--expected-generation",
        active_root.generation,
        "--expected-revision",
        str(seeded.committed_revision),
    )

    first_result = _invoke_rules_add(active_root, *exact_args)

    assert first_result.exit_code == ExitCode.SUCCESS, first_result.output
    first = json.loads(first_result.output)
    assert first["rule"]["category"] == "Existing"
    assert first["rule"]["priority"] == 88
    assert first["rule"]["fields"] == ["memo_raw"]
    assert first["rule"]["conditions"][0]["value"] == "Coupang"
    committed = active_root.facade.read_config_bytes("rules")
    assert committed is not None
    assert b"custom_id: keep-id" in committed
    assert b"notes: keep notes" in committed

    opaque_content = b"- later opaque rules head\n"
    active_root.facade.replace_config(
        ConfigDocument(
            config_kind="rules",
            content=opaque_content,
            parsed_status="opaque",
            canonical_payload=None,
            parser_version="synthetic.opaque.v1",
        )
    )
    before_replay = _authority_state(active_root)

    replay_result = _invoke_rules_add(active_root, *exact_args)

    assert replay_result.exit_code == ExitCode.SUCCESS, replay_result.output
    replay = json.loads(replay_result.output)
    assert replay["replayed"] is True
    assert replay["changeset_id"] == first["changeset_id"]
    assert active_root.facade.read_config_bytes("rules") == opaque_content
    assert _authority_state(active_root) == before_replay

    clear_result = _invoke_rules_add(
        active_root,
        *exact_args,
        "--category",
        "",
    )

    assert clear_result.exit_code == ExitCode.VALIDATION_ERROR, clear_result.output
    assert "idempotency" in clear_result.output.lower()
    assert active_root.facade.read_config_bytes("rules") == opaque_content
    assert _authority_state(active_root) == before_replay


def test_active_rule_transform_failure_preserves_config_head(
    active_root: _ActiveRoot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    initial = b"version: 1\nrules: []\n"
    active_root.facade.replace_config(
        ConfigDocument.from_validated_yaml(
            "rules",
            initial,
            parser_version="finjuice.rules.v1",
        )
    )
    before = _authority_state(active_root)

    def fail_transform(*_args: object, **_kwargs: object) -> bytes:
        raise ValueError("synthetic merged-rule failure")

    monkeypatch.setattr(
        "finjuice.pipeline.tagging.rules_yaml_roundtrip.upsert_rule_roundtrip_bytes",
        fail_transform,
    )

    result = _invoke_rules_add(
        active_root,
        "--name",
        "synthetic",
        "--match",
        "value",
        "--tags",
        "tag",
        "--json",
    )

    assert result.exit_code == ExitCode.VALIDATION_ERROR, result.output
    assert "synthetic merged-rule failure" in result.output
    assert active_root.facade.read_config_bytes("rules") == initial
    assert _authority_state(active_root) == before


def _seed_goals(active_root: _ActiveRoot) -> None:
    receipt = active_root.facade.replace_config(
        ConfigDocument.from_validated_yaml(
            "goals",
            _goals_bytes(total=1000),
            parser_version="finjuice.goals.v1",
        )
    )
    assert receipt.committed_revision == 1


def _goals_bytes(*, total: int) -> bytes:
    return (
        b"version: 1\n"
        b"# preserved repository comment\n"
        b"metadata:\n"
        b"  tiny: 1.234567890123456789e-400\n"
        b"monthly_budget:\n" + f"  total: {total}\n".encode() + b"  categories: {}\n"
    )


def _invoke_budget(active_root: _ActiveRoot, *args: str):
    return CliRunner().invoke(
        app,
        ["--data-dir", str(active_root.root), "budget", "edit", *args],
        obj={"activation_evidence_provider": active_root.provider},
    )


def _invoke_rules_add(active_root: _ActiveRoot, *args: str):
    return CliRunner().invoke(
        app,
        ["--data-dir", str(active_root.root), "rules", "add", *args],
        obj={"activation_evidence_provider": active_root.provider},
    )


def _authority_state(
    active_root: _ActiveRoot,
) -> tuple[str, tuple[tuple[str, str], ...], tuple[str, ...]]:
    with closing(sqlite3.connect(active_root.database)) as connection:
        database_dump = "\n".join(connection.iterdump())
    files = tuple(
        sorted(
            (
                path.relative_to(active_root.root).as_posix(),
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )
            for path in active_root.root.rglob("*")
            if path.is_file() and path != active_root.paths.coordination_lock
        )
    )
    directories = tuple(
        sorted(
            path.relative_to(active_root.root).as_posix()
            for path in active_root.root.rglob("*")
            if path.is_dir()
        )
    )
    return database_dump, files, directories
