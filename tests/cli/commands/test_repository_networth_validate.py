"""Canonical assets validation remains available independently of transaction reads."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from typer.testing import CliRunner

from finjuice.pipeline import networth_validation_repository as validation_source
from finjuice.pipeline.cli.main import app
from finjuice.pipeline.storage.mutation_facade import ConfigDocument, StorageMutationFacade
from tests.cli.commands.test_networth import _build_populated_data_dir
from tests.cli.commands.test_repository_assets import _activate
from tests.cli.commands.test_repository_query import QueryRoot
from tests.pipeline.checkup.helpers import _tx_row, write_transactions


def _invoke(root: QueryRoot, *, legacy: bool = False, human: bool = False):
    return CliRunner().invoke(
        app,
        [
            "--data-dir",
            str(root.legacy if legacy else root.root),
            "networth",
            "validate",
            *([] if human else ["--json"]),
        ],
        obj={} if legacy else {"activation_evidence_provider": root.provider},
    )


@pytest.mark.parametrize("absent", [False, True])
def test_valid_and_absent_preserve_legacy_result(tmp_path: Path, absent: bool) -> None:
    source = _build_populated_data_dir(tmp_path)
    if absent:
        (source / "assets.yaml").unlink()
    root = _activate(source, tmp_path)
    old, new = _invoke(root, legacy=True), _invoke(root)
    assert old.exit_code == new.exit_code == 0, new.output
    expected, actual = json.loads(old.output), json.loads(new.output)
    for key, value in expected.items():
        if key not in {"path", "_meta"}:
            assert actual[key] == value
    assert actual["path"] is None
    assert actual["selection_state"] == ("absent" if absent else "selected")
    assert actual["_meta"]["dataset_revision"] == 0
    assert "_repository_meta" not in actual
    (root.root / "assets.yaml").write_text("PRIVATE_SENTINEL: [")
    repeated = json.loads(_invoke(root).output)
    repeated["_meta"]["timestamp"] = actual["_meta"]["timestamp"]
    assert repeated == actual
    assert "Repository revision 0" in _invoke(root, human=True).output


@pytest.mark.parametrize(
    "content",
    [
        b"PRIVATE_SENTINEL: [",
        b"PRIVATE_SENTINEL: \xff",
        b"version: 1\nmanual_assets: PRIVATE_SENTINEL\n",
    ],
)
def test_invalid_canonical_content_is_static(tmp_path: Path, content: bytes) -> None:
    source = _build_populated_data_dir(tmp_path)
    (source / "assets.yaml").write_bytes(content)
    root = _activate(source, tmp_path)
    (root.root / "assets.yaml").write_text("version: 1\nmanual_assets: []\nliabilities: []\n")
    for human in (False, True):
        result = _invoke(root, human=human)
        assert result.exit_code == 1, result.output
        assert "PRIVATE_SENTINEL" not in result.output
        assert str(source) not in result.output and str(root.root) not in result.output
    payload = json.loads(_invoke(root).output)
    assert payload["status"] == "issues" and payload["errors"] == 1
    assert payload["path"] is None


def test_incomplete_transactions_do_not_block_config_validation(tmp_path: Path) -> None:
    source = _build_populated_data_dir(tmp_path)
    write_transactions(
        source,
        "2026-09",
        [_tx_row("2026-09-01", -1, "private", category_final="food", tags_final="broken[")],
    )
    root = _activate(source, tmp_path)
    result = _invoke(root)
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["valid"]


def test_unselected_and_detached_revision(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _activate(_build_populated_data_dir(tmp_path), tmp_path)
    original = validation_source.read_portfolio_snapshot
    snapshot = original(root.root, root.provider)
    assert snapshot is not None
    unselected = replace(
        snapshot, assets=replace(snapshot.assets, head=None, selection_state="unselected")
    )
    monkeypatch.setattr(validation_source, "read_portfolio_snapshot", lambda *_: unselected)
    result = _invoke(root)
    assert result.exit_code == 1
    assert json.loads(result.output)["exists"]
    assert not json.loads(result.output)["valid"]
    monkeypatch.setattr(validation_source, "read_portfolio_snapshot", lambda *_: snapshot)
    before = json.loads(_invoke(root).output)
    StorageMutationFacade(root.root, root.provider).replace_config(
        ConfigDocument(
            "assets", b"version: 1\nmanual_assets: []\nliabilities: []\n", "parsed", None, "test.v1"
        )
    )
    repeated = json.loads(_invoke(root).output)
    repeated["_meta"]["timestamp"] = before["_meta"]["timestamp"]
    assert repeated == before
    monkeypatch.setattr(validation_source, "read_portfolio_snapshot", original)
    after = json.loads(_invoke(root).output)
    assert after["_meta"]["dataset_revision"] == 1
    assert after["manual_assets"] == 0


def test_authority_failure_cannot_fall_back(tmp_path: Path) -> None:
    root = _activate(_build_populated_data_dir(tmp_path), tmp_path)
    result = CliRunner().invoke(
        app, ["--data-dir", str(root.root), "networth", "validate", "--json"]
    )
    assert result.exit_code != 0
    assert "Canonical assets validation could not be read" in result.output
    assert str(root.root) not in result.output
