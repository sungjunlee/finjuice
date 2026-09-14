"""Merged compatibility helpers cannot select a CLI authority by environment."""

import json

import pytest
from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app
from tests.cli.commands.test_repository_query import query_root as _query_fixture
from tests.sqlite_compat_data import build_generation

query_root = _query_fixture


@pytest.mark.parametrize("command", ["show", "status"])
@pytest.mark.parametrize("authority", ["canonical", "legacy", "missing_evidence"])
def test_environment_generation_cannot_replace_selected_authority(
    query_root, tmp_path, monkeypatch, command, authority
):
    data_dir = query_root.legacy if authority == "legacy" else query_root.root
    argv = ["--data-dir", str(data_dir), command, "--json"]
    obj = {"activation_evidence_provider": query_root.provider} if authority == "canonical" else {}
    monkeypatch.delenv("FINJUICE_SQLITE_GENERATION", raising=False)
    baseline = CliRunner().invoke(app, argv, obj=obj)
    unrelated = build_generation(tmp_path / "unrelated-generation")
    monkeypatch.setenv("FINJUICE_SQLITE_GENERATION", str(unrelated.parent))
    result = CliRunner().invoke(app, argv, obj=obj)
    assert result.exit_code == baseline.exit_code
    if authority == "missing_evidence":
        assert result.exit_code != 0
        assert json.loads(result.output)["error"] == json.loads(baseline.output)["error"]
        return
    assert result.exit_code == 0, result.output
    expected, actual = json.loads(baseline.output), json.loads(result.output)
    expected["_meta"].pop("timestamp", None)
    actual["_meta"].pop("timestamp", None)
    assert actual == expected
    if authority == "canonical":
        assert actual["_meta"]["dataset_generation"] == query_root.generation
