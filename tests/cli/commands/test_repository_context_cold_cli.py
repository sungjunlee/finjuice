"""Cold CLI startup must not require optional DuckDB for canonical context."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

import pytest

import finjuice
from tests.cli.commands.test_repository_assets import _activate
from tests.cli.commands.test_repository_context import _financial_source
from tests.cli.commands.test_typed_json_payload_contracts import _validate_command_schema

# Executed before any CLI imports; the child must use the parent package origin.
_COLD_CONTEXT = r"""
import builtins
import importlib.util
import json
from pathlib import Path
import sys

expected = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(expected.parent))
assert "duckdb" not in sys.modules
original_import = builtins.__import__

def without_duckdb(name, *args, **kwargs):
    if name == "duckdb" or name.startswith("duckdb."):
        raise ImportError("PRIVATE_COLD_DUCKDB_EXCEPTION")
    return original_import(name, *args, **kwargs)

builtins.__import__ = without_duckdb
spec = importlib.util.find_spec("finjuice")
assert spec is not None and spec.origin is not None
assert Path(spec.origin).resolve().parent == expected, (spec.origin, str(expected))
from typer.testing import CliRunner
from finjuice.pipeline.cli.main import app
from finjuice.pipeline.storage.authority import ActivationEvidence, StaticActivationEvidenceProvider
import finjuice.pipeline.cli.main as main_module
assert Path(main_module.__file__).resolve().is_relative_to(expected)
provider = StaticActivationEvidenceProvider(ActivationEvidence(**json.loads(sys.argv[3])))
arguments = ["--data-dir", sys.argv[2], "context", "--journal", "0", "--budget", "100000"]
if sys.argv[4] == "json":
    arguments.append("--json")
result = CliRunner().invoke(app, arguments, obj={"activation_evidence_provider": provider})
print(json.dumps({"origin": spec.origin, "exit_code": result.exit_code, "output": result.output}))
"""


@pytest.mark.parametrize("human", [False, True])
def test_cold_context_without_duckdb_uses_expected_package(tmp_path, human):
    root = _activate(_financial_source(tmp_path), tmp_path)
    expected_package = Path(finjuice.__file__).resolve().parent
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            _COLD_CONTEXT,
            str(expected_package),
            str(root.root),
            json.dumps(asdict(root.provider.evidence)),
            "human" if human else "json",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    envelope = json.loads(result.stdout)
    assert Path(envelope["origin"]).resolve().parent == expected_package
    assert envelope["exit_code"] == 0, envelope["output"]
    output = envelope["output"]
    assert "PRIVATE_COLD_DUCKDB_EXCEPTION" not in output + result.stderr
    if human:
        assert "Repository revision: 0" in output
        assert "Top Patterns\n- unavailable" in output
        assert "Monthly budget:" in output
        assert "finjuice doctor" in output
    else:
        payload = json.loads(output)
        assert payload["active_goals"]
        assert payload["top_patterns"] is None
        assert payload["_meta"]["repository"]["dataset_generation"] == root.generation
        assert payload["_meta"]["repository"]["dataset_revision"] == 0
        assert payload["_meta"]["repository"]["top_patterns_state"] == "unavailable"
        assert any("finjuice doctor" in warning for warning in payload["_meta"]["warnings"])
        _validate_command_schema(payload, command="context", schema_file="context.schema.json")
