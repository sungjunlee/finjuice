"""Contract matrix for failure-mode ``--json`` envelopes (Issue #697).

Success JSON contracts are already exercised broadly by
``tests/test_json_schemas.py`` and ``tests/cli/commands/test_typed_json_payload_contracts.py``.
This module pins the **failure** shape: every major command group must
produce a structured \\_error.schema.json envelope when invoked with
``--json`` against a representative failure case, with explicit error-code
and exit-code expectations.

Why this matters: for agent-facing CLI usage, the failure envelope is part
of the public API. A regression that turns a structured error into a
plain traceback or a free-form string would silently break agent
orchestration loops that branch on ``error.code``.

The matrix intentionally avoids any private financial data — every case
uses an isolated ``tmp_path`` data directory and triggers errors through
missing/invalid inputs, not real user transactions.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from referencing import Registry, Resource
from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMAS_DIR = REPO_ROOT / "schemas"


def _build_schema_registry() -> Registry[Any]:
    """Pre-register every schema by bare filename for cross-schema ``$ref`` resolution."""
    resources = [
        (
            schema_file.name,
            Resource.from_contents(json.loads(schema_file.read_text(encoding="utf-8"))),
        )
        for schema_file in SCHEMAS_DIR.glob("*.schema.json")
    ]
    return Registry().with_resources(resources)


_SCHEMA_REGISTRY: Registry[Any] = _build_schema_registry()
_ERROR_SCHEMA = json.loads((SCHEMAS_DIR / "_error.schema.json").read_text(encoding="utf-8"))
_ERROR_VALIDATOR = jsonschema.Draft202012Validator(_ERROR_SCHEMA, registry=_SCHEMA_REGISTRY)

runner = CliRunner()


def _extract_error_payload(stdout: str) -> dict[str, Any]:
    """Parse the last JSON object emitted to stdout.

    Some commands print preamble text before the JSON payload (e.g. a Rich
    panel for legacy-data warnings). The actual ``--json`` payload is the
    final top-level JSON object on stdout.
    """
    stripped = stdout.strip()
    if stripped.startswith("{"):
        return json.loads(stripped)
    # Find the last `{` that opens a top-level JSON object.
    last_open = stripped.rfind("\n{")
    assert last_open >= 0, f"No JSON object found in stdout:\n{stdout}"
    return json.loads(stripped[last_open + 1 :])


# Matrix of representative failure cases.
#
# Each case triggers an error and asserts the envelope shape:
# - (label, cli_args_factory, expected_error_code, expected_exit_code)
#
# ``cli_args_factory`` takes the ``tmp_path`` data directory and returns the
# full argv list passed to ``runner.invoke(app, …)``.
ERROR_MATRIX = [
    pytest.param(
        lambda data_dir: [
            "--data-dir",
            str(data_dir),
            "template",
            "show",
            "__definitely_not_a_real_template__",
            "--json",
        ],
        "INVALID_ARGS",
        2,
        id="template-show-unknown-name",
    ),
    pytest.param(
        lambda data_dir: [
            "--data-dir",
            str(data_dir),
            "template",
            "run",
            "__definitely_not_a_real_template__",
            "--json",
        ],
        "INVALID_ARGS",
        2,
        id="template-run-unknown-name",
    ),
    pytest.param(
        lambda data_dir: [
            "--data-dir",
            str(data_dir),
            "query",
            "--json",
            "SELECT * FROM __no_such_table__",
        ],
        "QUERY_ERROR",
        1,
        id="query-bad-sql",
    ),
    pytest.param(
        lambda data_dir: [
            "--data-dir",
            str(data_dir),
            "query",
            "--json",
            "DROP TABLE transactions",
        ],
        "VALIDATION_FAILED",
        3,
        id="query-rejects-non-readonly-sql",
    ),
]


# Separate matrix for cases that need the rules.yaml fixture removed.
NO_RULES_MATRIX = [
    pytest.param(
        lambda data_dir: [
            "--data-dir",
            str(data_dir),
            "tag",
            "--json",
        ],
        "RULES_FILE_NOT_FOUND",
        2,
        id="tag-missing-rules-yaml",
    ),
]


@pytest.fixture
def empty_data_dir(tmp_path: Path) -> Path:
    """Provide an initialized-but-empty finjuice data directory.

    The directory has the expected partition layout but no actual transactions,
    rules, or assets — enough for commands to start without auto-init dialog
    but bare enough to trigger NO_DATA / unknown-resource failures.
    """
    data_dir = tmp_path / "data"
    (data_dir / "transactions").mkdir(parents=True)
    (data_dir / "imports").mkdir()
    (data_dir / "exports").mkdir()
    (data_dir / "metadata").mkdir()
    # Minimal empty rules file so commands that require one don't bail on a
    # different code path before the case under test.
    (data_dir / "rules.yaml").write_text("rules: []\n", encoding="utf-8")
    return data_dir


@pytest.mark.parametrize("args_factory,expected_error_code,expected_exit_code", ERROR_MATRIX)
def test_error_envelope_matches_contract(
    empty_data_dir: Path,
    args_factory: Any,
    expected_error_code: str,
    expected_exit_code: int,
) -> None:
    """Each representative failure invocation must emit a schema-conformant envelope."""
    args = args_factory(empty_data_dir)

    result = runner.invoke(app, args)

    # The command must have failed with the expected exit code.
    assert result.exit_code == expected_exit_code, (
        f"args={args!r} → exit_code={result.exit_code}, expected={expected_exit_code}\n"
        f"stdout:\n{result.stdout}"
    )

    # The stdout must contain a JSON object that validates against _error.schema.json.
    payload = _extract_error_payload(result.stdout)
    _ERROR_VALIDATOR.validate(payload)

    # And the error.code field must match the expected machine-readable code.
    assert payload["error"]["code"] == expected_error_code, (
        f"args={args!r} → error.code={payload['error']['code']!r}, "
        f"expected={expected_error_code!r}\nfull payload: {payload!r}"
    )

    # exit_code field inside the payload must mirror the process exit code.
    assert payload["exit_code"] == expected_exit_code, (
        f"payload.exit_code={payload['exit_code']} != process exit_code={result.exit_code}"
    )


@pytest.fixture
def no_rules_data_dir(tmp_path: Path) -> Path:
    """Same shape as ``empty_data_dir`` but deliberately omits ``rules.yaml``."""
    data_dir = tmp_path / "data"
    (data_dir / "transactions").mkdir(parents=True)
    (data_dir / "imports").mkdir()
    (data_dir / "exports").mkdir()
    (data_dir / "metadata").mkdir()
    return data_dir


@pytest.mark.parametrize("args_factory,expected_error_code,expected_exit_code", NO_RULES_MATRIX)
def test_error_envelope_no_rules_cases(
    no_rules_data_dir: Path,
    args_factory: Any,
    expected_error_code: str,
    expected_exit_code: int,
) -> None:
    """Failure envelopes for commands that require rules.yaml but find none."""
    args = args_factory(no_rules_data_dir)
    result = runner.invoke(app, args)
    assert result.exit_code == expected_exit_code, (
        f"args={args!r} → exit_code={result.exit_code}, expected={expected_exit_code}\n"
        f"stdout:\n{result.stdout}"
    )
    payload = _extract_error_payload(result.stdout)
    _ERROR_VALIDATOR.validate(payload)
    assert payload["error"]["code"] == expected_error_code
    assert payload["exit_code"] == expected_exit_code


def test_error_envelope_meta_includes_command_field(empty_data_dir: Path) -> None:
    """Every failure envelope must carry a `_meta.command` field for agent routing.

    Without `_meta.command`, an agent observing an error JSON has no
    machine-readable handle on which command produced it. This guards the
    contract that error envelopes are namespaced.
    """
    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(empty_data_dir),
            "template",
            "show",
            "__definitely_not_a_real_template__",
            "--json",
        ],
    )

    assert result.exit_code == 2
    payload = _extract_error_payload(result.stdout)
    _ERROR_VALIDATOR.validate(payload)
    assert "_meta" in payload
    assert "command" in payload["_meta"]
    assert payload["_meta"]["command"] != ""
