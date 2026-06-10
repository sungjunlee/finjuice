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
    ("assets show", ["assets", "show", "--json"], "assets_show.schema.json"),
    ("assets status", ["assets", "status", "--json"], "assets_status.schema.json"),
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
    ("ingest", ["ingest", "--dry-run", "--json"], "ingest.schema.json"),
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


@pytest.mark.parametrize(("label", "cmd_args", "schema_file"), CATALOGUED_COMMANDS)
def test_command_output_validates_against_schema(
    schema_data_dir: Path,
    label: str,
    cmd_args: list[str],
    schema_file: str,
) -> None:
    """Actual Typer CLI --json output should validate against its artifact."""
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
