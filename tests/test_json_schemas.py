"""Regression tests for command output JSON Schema artifacts."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from referencing import Registry, Resource
from typer.main import get_command
from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app
from finjuice.pipeline.cli.output import error_code_values, exit_code_items

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMAS_DIR = REPO_ROOT / "schemas"
runner = CliRunner()

CATALOGUED_COMMANDS = [
    ("ssot reconcile submit", [], "ssot_reconcile_submit.schema.json"),
    ("ssot reconcile candidates", [], "ssot_reconcile_candidates.schema.json"),
    ("ssot reconcile confirm", [], "ssot_reconcile_confirm.schema.json"),
    ("ssot reconcile withdraw", [], "ssot_reconcile_withdraw.schema.json"),
    ("ssot intake list", [], "ssot_intake_list.schema.json"),
    ("ssot intake submit", [], "ssot_intake_submit.schema.json"),
    ("ssot intake confirm", [], "ssot_intake_confirm.schema.json"),
    ("ssot intake revise", [], "ssot_intake_revise.schema.json"),
    ("ssot intake withdraw", [], "ssot_intake_withdraw.schema.json"),
    ("ssot assets list", [], "ssot_assets_list.schema.json"),
    ("ssot assets confirm", [], "ssot_assets_confirm.schema.json"),
    ("ssot assets correct", [], "ssot_assets_correct.schema.json"),
    ("ssot assets relation-confirm", [], "ssot_assets_relation_confirm.schema.json"),
    ("ssot assets relation-correct", [], "ssot_assets_relation_correct.schema.json"),
    ("ssot assets report", [], "ssot_assets_report.schema.json"),
    ("ssot account preview", [], "ssot_account_preview.schema.json"),
    ("ssot account ownership-confirm", [], "ssot_account_ownership_confirm.schema.json"),
    ("ssot account ownership-correct", [], "ssot_account_ownership_correct.schema.json"),
    ("ssot account list", [], "ssot_account_list.schema.json"),
    ("ssot account confirm", [], "ssot_account_confirm.schema.json"),
    ("ssot account correct", [], "ssot_account_correct.schema.json"),
    ("ssot account ownership", [], "ssot_account_ownership.schema.json"),
    ("ssot backup create", [], "ssot_backup_create.schema.json"),
    ("ssot backup capture-bundle", [], "ssot_backup_capture_bundle.schema.json"),
    ("ssot backup verify-bundle", [], "ssot_backup_verify_bundle.schema.json"),
    ("ssot backup restore", [], "ssot_backup_restore.schema.json"),
    ("ssot backup restore-bundle", [], "ssot_backup_restore_bundle.schema.json"),
    ("ssot backup status", [], "ssot_backup_status.schema.json"),
    ("ssot backup store init", [], "ssot_backup_store_init.schema.json"),
    ("ssot backup store capture", [], "ssot_backup_store_capture.schema.json"),
    ("ssot backup store list", [], "ssot_backup_store_list.schema.json"),
    ("ssot backup store verify", [], "ssot_backup_store_verify.schema.json"),
    ("ssot backup store restore", [], "ssot_backup_store_restore.schema.json"),
    ("ssot backup store protect", [], "ssot_backup_store_protect.schema.json"),
    ("ssot backup store plan", [], "ssot_backup_store_plan.schema.json"),
    ("ssot backup store prune", [], "ssot_backup_store_prune.schema.json"),
    ("ssot backup deliver status", [], "ssot_backup_deliver_status.schema.json"),
    ("ssot backup deliver run", [], "ssot_backup_deliver_run.schema.json"),
    ("ssot migrate plan", [], "ssot_migrate_plan.schema.json"),
    ("ssot migrate build", [], "ssot_migrate_build.schema.json"),
    ("ssot migrate verify", [], "ssot_migrate_verify.schema.json"),
    ("assets show", ["assets", "show", "--json"], "assets_show.schema.json"),
    ("assets status", ["assets", "status", "--json"], "assets_status.schema.json"),
    ("assets balance", ["assets", "balance", "--json"], "assets_balance.schema.json"),
    ("audit clear", ["audit", "clear", "--yes", "--json"], "audit_clear.schema.json"),
    ("status", ["status", "--json"], "status.schema.json"),
    ("checkup", ["checkup", "--json"], "checkup.schema.json"),
    ("context", ["context", "--json"], "context.schema.json"),
    ("doctor", ["doctor", "--json"], "doctor.schema.json"),
    ("automation run", ["automation", "run", "--json"], "automation_run.schema.json"),
    ("audit stats", ["audit", "stats", "--json"], "audit_stats.schema.json"),
    ("history", ["history", "--json"], "history.schema.json"),
    (
        "import",
        [
            "import",
            "--dry-run",
            "--file",
            str(REPO_ROOT / "tests" / "fixtures" / "sample_banksalad.xlsx"),
            "--json",
        ],
        "import.schema.json",
    ),
    (
        "inspect xlsx",
        [
            "inspect",
            "xlsx",
            str(REPO_ROOT / "tests" / "fixtures" / "sample_banksalad.xlsx"),
            "--json",
        ],
        "inspect_xlsx.schema.json",
    ),
    ("ingest", ["ingest", "--dry-run", "--json"], "ingest.schema.json"),
    (
        "reconcile",
        [
            "reconcile",
            "--evidence",
            str(REPO_ROOT / "tests" / "fixtures" / "sample_evidence.json"),
            "--json",
        ],
        "reconcile.schema.json",
    ),
    ("index", ["index", "--json"], "index.schema.json"),
    ("manifest", ["manifest", "--json"], "manifest.schema.json"),
    ("query", ["query", "SELECT 1 AS one", "--json"], "query.schema.json"),
    ("review", ["review", "--json"], "review.schema.json"),
    (
        "rules add",
        [
            "rules",
            "add",
            "--name",
            "schema_test",
            "--match",
            "SchemaTest",
            "--tags",
            "테스트",
            "--dry-run",
            "--json",
        ],
        "rules_add.schema.json",
    ),
    ("rules export", ["rules", "export", "--json"], "rules_export.schema.json"),
    ("rules gaps", ["rules", "gaps", "--json"], "rules_gaps.schema.json"),
    ("show", ["show", "--json"], "show.schema.json"),
    ("tag", ["tag", "--dry-run", "--json"], "tag.schema.json"),
    ("transfer", ["transfer", "--json"], "transfer.schema.json"),
    ("template list", ["template", "list", "--json"], "template_list.schema.json"),
    ("template show", ["template", "show", "monthly_spend", "--json"], "template_show.schema.json"),
    ("journal list", ["journal", "list", "--json"], "journal_list.schema.json"),
    ("export", ["export", "--dry-run", "--json"], "export.schema.json"),
    ("export-verify", [], "export_verify.schema.json"),
    ("networth", ["networth", "--json"], "networth.schema.json"),
    (
        "networth breakdown",
        ["networth", "breakdown", "--by", "category", "--json"],
        "networth_breakdown.schema.json",
    ),
    (
        "networth forecast",
        ["networth", "forecast", "--years", "1", "--json"],
        "networth_forecast.schema.json",
    ),
    ("networth history", ["networth", "history", "--json"], "networth_history.schema.json"),
    ("rules list", ["rules", "list", "--json"], "rules_list.schema.json"),
    ("rules remove", ["rules", "remove", "--name", "coffee", "--json"], "rules_remove.schema.json"),
    ("rules suggest", ["rules", "suggest", "--json"], "rules_suggest.schema.json"),
    ("rules test", ["rules", "test", "coffee", "--json"], "rules_test.schema.json"),
    ("rules validate", ["rules", "validate", "--json"], "rules_validate.schema.json"),
    ("refresh", ["refresh", "--json"], "refresh.schema.json"),
    ("audit log", ["audit", "log", "--json"], "audit_log.schema.json"),
    ("networth validate", ["networth", "validate", "--json"], "networth_validate.schema.json"),
    ("template run", ["template", "run", "monthly_spend", "--json"], "template_run.schema.json"),
    (
        "budget edit",
        ["budget", "edit", "--set", "식비=700000", "--yes", "--json"],
        "budget_edit.schema.json",
    ),
    ("budget status", ["budget", "status", "--json"], "budget_status.schema.json"),
    ("budget validate", ["budget", "validate", "--json"], "budget_validate.schema.json"),
    ("explain", ["explain", "Starbucks", "--json"], "explain.schema.json"),
    ("version", ["version", "--json"], "version.schema.json"),
    ("init", ["init", "--json"], "init.schema.json"),
    (
        "networth init",
        ["networth", "init", "--json"],
        "networth_init.schema.json",
    ),
    ("validate", ["validate", "--json"], "validate.schema.json"),
    (
        "backup create",
        ["backup", "create", "--json"],
        "backup_create.schema.json",
    ),
    (
        "backup verify",
        ["backup", "verify", "--json"],
        "backup_verify.schema.json",
    ),
    (
        "backup restore",
        ["backup", "restore", "--json"],
        "backup_restore.schema.json",
    ),
]

PRIVACY_PROFILE_COMMANDS = [
    (
        "automation run compact",
        ["automation", "run", "--json", "--privacy", "compact"],
        "automation_run.schema.json",
    ),
    ("checkup compact", ["checkup", "--json", "--privacy", "compact"], "checkup.schema.json"),
    ("review compact", ["review", "--json", "--privacy", "compact"], "review.schema.json"),
    (
        "rules suggest compact",
        ["rules", "suggest", "--json", "--privacy", "compact"],
        "rules_suggest.schema.json",
    ),
    ("index compact", ["index", "--json", "--privacy", "compact"], "index.schema.json"),
]

REQUIRED_SCHEMA_FILES = {
    "_error.schema.json",
    "_meta.schema.json",
    "manifest.schema.json",
    *{schema_file for _, _, schema_file in CATALOGUED_COMMANDS},
}


@pytest.fixture
def schema_data_dir(json_output_data_dir: Path) -> Path:
    """Extend the shared JSON fixture with schema-test-only support files."""
    audit_log = json_output_data_dir / ".execution_audit.jsonl"
    audit_log.write_text(
        json.dumps(
            {
                "timestamp": "2026-05-04T00:00:00+00:00",
                "event": "command_executed",
                "command": "finjuice status",
                "success": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    journal_dir = json_output_data_dir.parent / "_journal"
    journal_dir.mkdir(parents=True, exist_ok=True)
    (journal_dir / "2026-05-04-schema-test.md").write_text(
        "---\n"
        "topic: schema-test\n"
        "created: 2026-05-04T00:00:00+00:00\n"
        "data_range: 2024-10-01 ~ 2024-11-20\n"
        "---\n\n"
        "Schema fixture journal.\n",
        encoding="utf-8",
    )
    (json_output_data_dir / "goals.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "monthly_budget:",
                "  total: 250000",
                "  categories:",
                "    식비: 100000",
                "    구독: 50000",
                '  updated: "2026-05-04"',
                "net_worth_target: 10000000",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (json_output_data_dir / "scenarios.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "assumptions:",
                "  default_savings_per_month: 100000",
                "  asset_returns:",
                "    real_estate:",
                "      conservative: 0.01",
                "      neutral: 0.03",
                "      optimistic: 0.05",
                "    deposit:",
                "      conservative: 0.0",
                "      neutral: 0.01",
                "      optimistic: 0.02",
                "    financial:",
                "      conservative: 0.02",
                "      neutral: 0.05",
                "      optimistic: 0.08",
                "    cash:",
                "      conservative: 0.0",
                "      neutral: 0.0",
                "      optimistic: 0.0",
                "    other:",
                "      conservative: 0.0",
                "      neutral: 0.0",
                "      optimistic: 0.0",
                "  liability_rate_delta: 0.0",
                "lifecycle_events: []",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return json_output_data_dir


def _load_schema(filename: str) -> dict[str, Any]:
    return json.loads((SCHEMAS_DIR / filename).read_text(encoding="utf-8"))


def _build_schema_registry() -> Registry[Any]:
    """Pre-register every \\*.schema.json in SCHEMAS_DIR under its bare filename.

    The legacy `jsonschema.RefResolver` accepted a `base_uri` and resolved
    relative `$ref` entries like ``_meta.schema.json`` against it. The
    `referencing` migration drops `base_uri`, so we instead pre-register
    each schema file by its bare-filename URI. The on-disk schemas already
    use bare-filename refs (e.g. ``"$ref": "_meta.schema.json"``), so each
    ref resolves directly to a registered resource without any base-URI gymnastics.
    """
    resources = [
        (
            schema_file.name,
            Resource.from_contents(json.loads(schema_file.read_text(encoding="utf-8"))),
        )
        for schema_file in SCHEMAS_DIR.glob("*.schema.json")
    ]
    return Registry().with_resources(resources)


_SCHEMA_REGISTRY: Registry[Any] = _build_schema_registry()


def _validator_for(schema: dict[str, Any]) -> jsonschema.Draft202012Validator:
    return jsonschema.Draft202012Validator(schema, registry=_SCHEMA_REGISTRY)


def _command_has_json_option(command: Any) -> bool:
    """Return whether a Click command exposes a --json option."""
    for param in getattr(command, "params", []):
        option_names = [
            *getattr(param, "opts", ()),
            *getattr(param, "secondary_opts", ()),
        ]
        if "--json" in option_names:
            return True
    return False


def _typer_json_command_paths() -> set[str]:
    """Walk the Typer app and return command paths with a --json option."""
    root_command = get_command(app)
    command_paths: set[str] = set()

    def walk(command: Any, path: tuple[str, ...]) -> None:
        if path and _command_has_json_option(command):
            command_paths.add(" ".join(path))
        for name, subcommand in sorted(getattr(command, "commands", {}).items()):
            walk(subcommand, (*path, name))

    walk(root_command, ())
    return command_paths


def test_meta_schema_valid() -> None:
    """The shared _meta schema must be valid Draft 2020-12."""
    jsonschema.Draft202012Validator.check_schema(_load_schema("_meta.schema.json"))


def test_error_schema_valid() -> None:
    """The shared error schema must be valid Draft 2020-12."""
    jsonschema.Draft202012Validator.check_schema(_load_schema("_error.schema.json"))


def test_error_schema_exposes_accepted_error_codes() -> None:
    """The shared error schema should advertise the public error-code catalog."""
    schema = _load_schema("_error.schema.json")
    code_schema = schema["properties"]["error"]["properties"]["code"]

    assert code_schema["enum"] == list(error_code_values())


def test_manifest_schema_exposes_error_and_exit_code_catalogs() -> None:
    """The manifest schema should stay aligned with typed code catalogs."""
    schema = _load_schema("manifest.schema.json")

    error_code_items_schema = schema["properties"]["error_codes"]["items"]
    exit_code_properties = schema["properties"]["exit_codes"]["properties"]

    assert error_code_items_schema["enum"] == list(error_code_values())
    assert {
        name: property_schema["const"] for name, property_schema in exit_code_properties.items()
    } == dict(exit_code_items())


def test_required_schema_artifacts_exist() -> None:
    """Every documented command result schema plus manifest must be generated."""
    schema_files = {schema_file.name for schema_file in SCHEMAS_DIR.glob("*.schema.json")}

    assert REQUIRED_SCHEMA_FILES <= schema_files


def test_rules_gaps_schema_documents_mismatch_classification() -> None:
    """rules gaps schema should document additive mismatch classification fields."""
    schema = _load_schema("rules_gaps.schema.json")

    summary_properties = schema["properties"]["summary"]["properties"]
    assert "total_mismatch_count" in summary_properties
    assert "filtered_mismatch_count" in summary_properties
    assert "filtered_out_mismatch_count" in summary_properties
    assert "conflict_count" in summary_properties
    assert "category_mismatch_count" in summary_properties
    assert "multi_tag_noise_count" in summary_properties

    mismatch_properties = schema["properties"]["mismatches"]["items"]["properties"]
    assert "mismatch_type" in mismatch_properties
    assert "mismatch_severity" in mismatch_properties
    assert "actionable" in mismatch_properties
    assert "expected_category" in mismatch_properties


def test_transfer_review_metadata_is_public_schema_contract() -> None:
    """Transfer review counts should be visible in command JSON schemas."""
    transfer_schema = _load_schema("transfer.schema.json")
    assert {
        "candidate_rows",
        "confirmed_transfer_rows",
        "unconfirmed_candidate_rows",
    } <= transfer_schema["properties"].keys()
    assert {
        "candidate_rows",
        "confirmed_transfer_rows",
        "unconfirmed_candidate_rows",
    } <= set(transfer_schema["required"])

    status_schema = _load_schema("status.schema.json")
    tagging_schema = status_schema["properties"]["tagging"]
    assert {
        "transfer_candidate_count",
        "unconfirmed_transfer_candidate_count",
    } <= tagging_schema["properties"].keys()
    assert {
        "transfer_candidate_count",
        "unconfirmed_transfer_candidate_count",
    } <= set(tagging_schema["required"])

    transfer_exclusions_schema = tagging_schema["properties"]["transfer_exclusions"]
    assert {
        "candidate_count",
        "confirmed_count",
        "unconfirmed_candidate_count",
    } <= transfer_exclusions_schema["properties"].keys()
    assert {
        "candidate_count",
        "confirmed_count",
        "unconfirmed_candidate_count",
    } <= set(transfer_exclusions_schema["required"])


def test_catalogued_commands_match_typer_json_options() -> None:
    """The regression catalog should cover every current CLI --json command."""
    catalogued = {label for label, _, _ in CATALOGUED_COMMANDS}

    assert catalogued == _typer_json_command_paths()


@pytest.mark.parametrize("schema_file", sorted(REQUIRED_SCHEMA_FILES))
def test_schema_artifact_valid_draft_2020_12(schema_file: str) -> None:
    """Each generated schema artifact must be valid Draft 2020-12."""
    jsonschema.Draft202012Validator.check_schema(_load_schema(schema_file))


def _materialize_backup_catalog_args(schema_data_dir: Path, label: str) -> list[str]:
    """Build synthetic backup CLI args against the schema data directory."""
    backup_dir = schema_data_dir.parent / "schema-backup"
    restore_dir = schema_data_dir.parent / "schema-restore"
    create_args = [
        "backup",
        "create",
        "--source",
        str(schema_data_dir),
        "--output",
        str(backup_dir),
        "--consistency",
        "stopped-writers",
        "--stopped-writer",
        "catalog",
        "--json",
    ]
    if label == "backup create":
        return create_args
    if not backup_dir.exists():
        created = runner.invoke(app, ["--data-dir", str(schema_data_dir), *create_args])
        assert created.exit_code == 0, created.output[:500]
    if label == "backup verify":
        return ["backup", "verify", str(backup_dir / "backup-manifest.json"), "--json"]
    return [
        "backup",
        "restore",
        str(backup_dir / "backup-manifest.json"),
        "--target",
        str(restore_dir),
        "--json",
    ]


def _materialize_migration_catalog_args(schema_data_dir: Path, label: str) -> list[str]:
    """Prepare real frozen synthetic evidence for each migration command schema."""
    from finjuice.pipeline.migration import build_migration, plan_migration

    _materialize_backup_catalog_args(schema_data_dir, "backup verify")
    capture = schema_data_dir.parent / "schema-backup"
    plan = schema_data_dir.parent / "migration-plan.json"
    candidate = schema_data_dir.parent / "migration-candidate"
    if label == "ssot migrate plan":
        return ["ssot", "migrate", "plan", "--manifest", str(capture), "--json"]
    plan_migration(capture, output=plan, active_data_dir=schema_data_dir)
    if label == "ssot migrate build":
        return [
            "ssot",
            "migrate",
            "build",
            "--plan",
            str(plan),
            "--staging",
            str(candidate),
            "--json",
        ]
    build_migration(plan, candidate, active_data_dir=schema_data_dir)
    return ["ssot", "migrate", "verify", "--candidate", str(candidate), "--json"]


def _materialize_sqlite_backup_catalog_args(schema_data_dir: Path, label: str) -> list[str]:
    """Prepare an actual snapshot for the SQLite backup command catalog."""
    if label in {
        "ssot backup capture-bundle",
        "ssot backup verify-bundle",
        "ssot backup restore-bundle",
    }:
        return _materialize_recovery_bundle_catalog_args(schema_data_dir, label)
    if label.startswith("ssot backup store "):
        return _materialize_recovery_store_catalog_args(schema_data_dir, label)
    if label.startswith("ssot backup deliver "):
        return _materialize_backup_deliver_catalog_args(schema_data_dir, label)
    from finjuice.pipeline.storage.sqlite.backup import create_backup
    from tests.pipeline.test_sqlite_backup import _build_generation

    source = _build_generation(schema_data_dir.parent / "schema-generation")
    backup = schema_data_dir.parent / "sqlite-backup"
    if label == "ssot backup create":
        return [
            "ssot",
            "backup",
            "create",
            "--source",
            str(source.database),
            "--output",
            str(backup),
            "--json",
        ]
    create_backup(source.database, backup)
    if label == "ssot backup status":
        return ["ssot", "backup", "status", str(backup), "--json"]
    return [
        "ssot",
        "backup",
        "restore",
        str(backup),
        "--target",
        str(schema_data_dir.parent / "sqlite-restored"),
        "--json",
    ]


def _materialize_recovery_bundle_catalog_args(schema_data_dir: Path, label: str) -> list[str]:
    """Prepare a real synthetic graph for recovery-bundle command catalog cases."""
    from finjuice.pipeline.storage.sqlite.recovery_bundle import capture_recovery_bundle
    from tests.cli.test_sqlite_recovery_bundle import _capture_args, _write_expected
    from tests.pipeline.test_recovery_bundle import _live

    root = schema_data_dir.parent / "recovery-bundle-live"
    source, expected, *_ = _live(root)
    expected_path = _write_expected(root / "enrolled.json", expected)
    if label == "ssot backup capture-bundle":
        return ["ssot", "backup", *_capture_args(source, expected_path), "--json"]
    capture_recovery_bundle(source, expected)
    if label == "ssot backup verify-bundle":
        return [
            "ssot",
            "backup",
            "verify-bundle",
            str(source.destination),
            "--expected",
            str(expected_path),
            "--json",
        ]
    return [
        "ssot",
        "backup",
        "restore-bundle",
        str(source.destination),
        "--target",
        str(schema_data_dir.parent / "recovery-restored"),
        "--expected",
        str(expected_path),
        "--json",
    ]


def _materialize_recovery_store_catalog_args(schema_data_dir: Path, label: str) -> list[str]:
    """Prepare an initialized store and one verified graph for store command catalog cases."""
    from finjuice.pipeline.storage.sqlite.recovery_store import (
        capture_into_store,
        initialize_recovery_store,
    )
    from tests.cli.test_sqlite_recovery_bundle import _write_expected
    from tests.pipeline.test_recovery_bundle import _live

    root = schema_data_dir.parent / "recovery-store-live"
    source, expected, *_ = _live(root)
    expected_path = _write_expected(root / "enrolled.json", expected)
    store = root / "store"
    prefix = ["ssot", "backup", "store"]
    shared = ["--store", str(store), "--expected", str(expected_path), "--json"]
    if label == "ssot backup store init":
        return [*prefix, "init", "--store", str(store), "--expected", str(expected_path), "--json"]
    initialize_recovery_store(store, expected)
    if label == "ssot backup store capture":
        paths = source.release_paths
        return [
            *prefix,
            "capture",
            "--store",
            str(store),
            "--source-data-dir",
            str(source.data_dir),
            "--expected",
            str(expected_path),
            "--wheel",
            str(paths.wheel),
            "--dependency-lock",
            str(paths.dependency_lock),
            "--binding",
            str(paths.binding),
            "--migration-candidate",
            str(source.migration_candidate),
            "--json",
        ]
    captured = capture_into_store(store, source, expected)
    action = {
        "ssot backup store list": ["list"],
        "ssot backup store verify": ["verify", "--copy-id", captured.copy_id],
        "ssot backup store restore": [
            "restore",
            "--copy-id",
            captured.copy_id,
            "--target",
            str(schema_data_dir.parent / "recovery-store-restored"),
        ],
        "ssot backup store protect": ["protect", "--copy-id", captured.copy_id],
        "ssot backup store plan": ["plan"],
        "ssot backup store prune": ["prune"],
    }[label]
    return [*prefix, *action, *shared]


def _materialize_backup_deliver_catalog_args(schema_data_dir: Path, label: str) -> list[str]:
    """Prepare sender/destination stores for delivery status and run catalog cases."""
    from finjuice.pipeline.storage.sqlite.recovery_store import (
        capture_into_store,
        initialize_recovery_store,
    )
    from tests.cli.test_sqlite_recovery_bundle import _write_expected
    from tests.pipeline.test_recovery_bundle import _live

    root = schema_data_dir.parent / "backup-deliver-live"
    source, expected, *_ = _live(root)
    expected_path = _write_expected(root / "enrolled.json", expected)
    sender = root / "sender"
    destination = root / "destination"
    control = root / "control"
    initialize_recovery_store(sender, expected)
    initialize_recovery_store(destination, expected)
    capture_into_store(sender, source, expected)
    paths = source.release_paths
    shared = [
        "ssot",
        "backup",
        "deliver",
        "status" if label.endswith("status") else "run",
        "--source-data-dir",
        str(source.data_dir),
        "--expected",
        str(expected_path),
        "--sender-store",
        str(sender),
        "--destination-store",
        str(destination),
        "--control-dir",
        str(control),
        "--json",
    ]
    if label.endswith("run"):
        shared.extend(
            [
                "--wheel",
                str(paths.wheel),
                "--dependency-lock",
                str(paths.dependency_lock),
                "--binding",
                str(paths.binding),
                "--migration-candidate",
                str(source.migration_candidate),
            ]
        )
    return shared


def _account_catalog_result(schema_data_dir: Path, label: str):
    if label.split()[-1] in {"preview", "ownership-confirm", "ownership-correct"}:
        from tests.pipeline.test_account_decisions import _catalog_command_result

        return _catalog_command_result(
            schema_data_dir.parent / "account-decision", label.split()[-1]
        )

    from finjuice.pipeline.storage.mutation_facade import StorageMutationFacade
    from finjuice.pipeline.storage.sqlite.account_bindings import AccountBindingConfirmation
    from finjuice.pipeline.storage.sqlite.schema import inspect_repository
    from tests.pipeline.test_recovery_bundle import _live

    source, _expected, paths, generation, _transactions, account = _live(
        schema_data_dir.parent / "account-live"
    )
    request = schema_data_dir.parent / "account-binding.json"
    body = {
        "source_namespace": "catalog.account.v1",
        "external_key": "synthetic",
        "account_id": account,
        "evidence": {"reason": "explicit synthetic confirmation"},
    }
    request.write_text(json.dumps(body))
    command = label.split()[-1]
    args = ["ssot", "account", command]
    if command == "correct":
        facade = StorageMutationFacade(source.data_dir, evidence_provider=source.evidence_provider)
        first = facade.confirm_account_binding(AccountBindingConfirmation(**body))
        args.append(first.result["binding_id"])
    if command in {"correct", "confirm"}:
        revision = inspect_repository(paths.generation(generation).database).dataset_revision
        args += [
            str(request),
            "--idempotency-key",
            "catalog",
            "--expected-generation",
            generation,
            "--expected-revision",
            str(revision),
        ]
    elif command == "ownership":
        args += [account, "--as-of", "2026-09-14"]
    return runner.invoke(
        app,
        ["--data-dir", str(source.data_dir), *args, "--json"],
        obj={"activation_evidence_provider": source.evidence_provider},
    )


@pytest.mark.parametrize(("label", "cmd_args", "schema_file"), CATALOGUED_COMMANDS)
def test_command_output_validates_against_schema(
    schema_data_dir: Path,
    label: str,
    cmd_args: list[str],
    schema_file: str,
) -> None:
    """Actual Typer CLI --json output should validate against its artifact."""
    if label.startswith("backup "):
        cmd_args = _materialize_backup_catalog_args(schema_data_dir, label)
    if label.startswith("ssot backup "):
        cmd_args = _materialize_sqlite_backup_catalog_args(schema_data_dir, label)
    if label.startswith("ssot migrate "):
        cmd_args = _materialize_migration_catalog_args(schema_data_dir, label)
    if label.startswith("ssot reconcile "):
        from tests.pipeline.test_canonical_reconcile import reconcile_catalog_outputs

        payload = reconcile_catalog_outputs(schema_data_dir.parent / "canonical-reconcile")[
            label.split()[-1]
        ]
        _validator_for(_load_schema(schema_file)).validate(payload)
        return
    if label.startswith("ssot intake "):
        from tests.pipeline.test_canonical_intake_cli import intake_catalog_outputs

        if label.endswith((" revise", " withdraw")):
            from tests.pipeline.test_intake_lifecycle import intake_lifecycle_catalog_outputs

            outputs = intake_lifecycle_catalog_outputs(schema_data_dir.parent / "intake")
        else:
            outputs = intake_catalog_outputs(schema_data_dir.parent / "intake")
        payload = outputs[label.replace(" ", "_")]
        _validator_for(_load_schema(schema_file)).validate(payload)
        return
    if label.startswith("ssot assets "):
        from tests.pipeline.test_canonical_assets import _catalog_asset_result

        result = _catalog_asset_result(
            schema_data_dir.parent / "canonical-assets", label.split()[-1]
        )
    elif label.startswith("ssot account "):
        result = _account_catalog_result(schema_data_dir, label)
    elif label == "export-verify":
        from tests.cli.commands.test_repository_export import _export, _payload, _verify
        from tests.cli.commands.test_repository_query import query_root

        root = query_root.__wrapped__(schema_data_dir / "export-verification")
        generated = _payload(_export(root))
        result = _verify(root, Path(generated["manifest_path"]))
    else:
        result = runner.invoke(app, ["--data-dir", str(schema_data_dir), *cmd_args])

    assert result.exit_code == 0, f"{label} failed: {result.output[:500]}"
    payload = json.loads(result.output)
    schema = _load_schema(schema_file)

    jsonschema.Draft202012Validator.check_schema(schema)
    _validator_for(schema).validate(payload)


@pytest.mark.parametrize(("label", "cmd_args", "schema_file"), PRIVACY_PROFILE_COMMANDS)
def test_privacy_profile_output_validates_against_command_schema(
    schema_data_dir: Path,
    label: str,
    cmd_args: list[str],
    schema_file: str,
) -> None:
    """Compact privacy variants should validate against the same command schemas."""
    result = runner.invoke(app, ["--data-dir", str(schema_data_dir), *cmd_args])

    assert result.exit_code == 0, f"{label} failed: {result.output[:500]}"
    payload = json.loads(result.output)
    schema = _load_schema(schema_file)

    assert payload["_meta"]["privacy"]["profile"] == "compact"
    _validator_for(schema).validate(payload)


def test_schemas_match_filename_convention() -> None:
    """Non-shared schema files use lower-case underscore command paths."""
    pattern = re.compile(r"^[a-z0-9_]+\.schema\.json$")
    schema_files = sorted(SCHEMAS_DIR.glob("*.schema.json"))

    assert schema_files
    for schema_file in schema_files:
        if schema_file.name.startswith("_"):
            continue
        assert pattern.fullmatch(schema_file.name), schema_file.name


def test_markdown_reference_lists_generated_schema_artifacts() -> None:
    """The human-readable reference should be regenerated from schema artifacts."""
    docs_text = (REPO_ROOT / "docs" / "reference" / "json-schemas.md").read_text(encoding="utf-8")

    assert "Generated from `schemas/*.schema.json`" in docs_text
    for schema_file in sorted(REQUIRED_SCHEMA_FILES):
        assert f"`schemas/{schema_file}`" in docs_text
