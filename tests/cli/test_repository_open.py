"""Canonical open aliases require intact current local export receipts."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from finjuice.pipeline.cli.commands import open_cmd
from finjuice.pipeline.cli.main import app
from finjuice.pipeline.config import Config
from finjuice.pipeline.storage import read_facade
from tests.cli.commands.test_repository_export import _export, _files, _payload, _replace_rules
from tests.cli.commands.test_repository_query import query_root as _query_fixture
from tests.conftest import cli_text

query_root = _query_fixture


@pytest.fixture
def opener(monkeypatch):
    mocked = Mock()
    monkeypatch.setattr(open_cmd, "open_path", mocked)
    return mocked


def _open(root, target, *, evidence=True):
    return CliRunner().invoke(
        app,
        ["--data-dir", str(root.root), "open", target],
        obj={"activation_evidence_provider": root.provider} if evidence else {},
    )


def _legacy_artifacts(root):
    export_dir = Config(data_dir=root.root).export_dir
    export_dir.mkdir(parents=True, exist_ok=True)
    (export_dir / "master_99991231.xlsx").write_bytes(b"PRIVATE_LEGACY_MASTER")
    reports = export_dir / "reports"
    reports.mkdir(exist_ok=True)
    (reports / "legacy.txt").write_text("PRIVATE_LEGACY_REPORT")


@pytest.mark.parametrize("target", ["master", "reports"])
def test_open_uses_current_receipt_instead_of_legacy_artifacts(
    query_root, opener, monkeypatch, target
):
    exported = _payload(_export(query_root))
    _legacy_artifacts(query_root)
    original = read_facade.read_transaction_snapshot
    reader = Mock(wraps=original)
    monkeypatch.setattr(read_facade, "read_transaction_snapshot", reader)

    result = _open(query_root, target)

    assert result.exit_code == 0, cli_text(result)
    expected = (
        _files(exported)["master_xlsx"]
        if target == "master"
        else Path(exported["manifest_path"]).parent / "reports"
    )
    opener.assert_called_once_with(expected)
    reader.assert_called_once()
    assert "filesystem" in cli_text(result).lower()
    assert "receipt" in cli_text(result).lower()
    assert "PRIVATE" not in cli_text(result)


@pytest.mark.parametrize("target", ["master", "reports"])
@pytest.mark.parametrize("failure", ["missing", "stale", "malformed"])
def test_open_rejects_unusable_receipt_without_legacy_fallback(query_root, opener, target, failure):
    if failure != "missing":
        exported = _payload(_export(query_root))
        if failure == "stale":
            _replace_rules(query_root, b"rules: []\nreport_filters: {}\n")
        else:
            Path(exported["manifest_path"]).write_text("PRIVATE_MALFORMED_RECEIPT: [")
    _legacy_artifacts(query_root)

    result = _open(query_root, target)

    assert result.exit_code != 0
    opener.assert_not_called()
    assert "PRIVATE" not in cli_text(result)
    assert "finjuice export" in cli_text(result)


@pytest.mark.parametrize("target", ["master", "reports"])
def test_open_missing_authority_evidence_never_launches_legacy_or_canonical(
    query_root, opener, target
):
    _payload(_export(query_root))
    _legacy_artifacts(query_root)

    result = _open(query_root, target, evidence=False)

    assert result.exit_code != 0
    opener.assert_not_called()
    assert "PRIVATE" not in cli_text(result)
