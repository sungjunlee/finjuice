"""Canonical assets initialization preserves existing configuration and concurrency."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from finjuice.pipeline import networth_initialization_repository as initialization
from finjuice.pipeline.cli.main import app
from finjuice.pipeline.storage.mutation_facade import ConfigDocument, StorageMutationFacade
from finjuice.pipeline.storage.read_facade import read_portfolio_snapshot
from tests.cli.commands.test_repository_assets import _activate
from tests.cli.commands.test_repository_query import QueryRoot


@pytest.fixture
def absent_root(tmp_path: Path) -> QueryRoot:
    source = tmp_path / "source"
    source.mkdir()
    (source / "rules.yaml").write_text("rules: []\n")
    return _activate(source, tmp_path)


def _invoke(root: QueryRoot, *, human: bool = False, evidence: bool = True):
    return CliRunner().invoke(
        app,
        ["--data-dir", str(root.root), "networth", "init", *([] if human else ["--json"])],
        obj={"activation_evidence_provider": root.provider} if evidence else {},
    )


@pytest.mark.parametrize("human", [False, True])
def test_init_registers_empty_config_once_and_never_writes_live_yaml(
    absent_root: QueryRoot, human: bool
) -> None:
    # Arrange: a stray derived/live file must not decide canonical existence.
    live = absent_root.root / "assets.yaml"
    live.write_bytes(b"PRIVATE LIVE SENTINEL\n")
    before = read_portfolio_snapshot(absent_root.root, absent_root.provider)
    assert before is not None and before.assets.selection_state == "absent"

    # Act: initialize, then repeat against the resulting selected revision.
    first = _invoke(absent_root, human=human)
    after = read_portfolio_snapshot(absent_root.root, absent_root.provider)
    second = _invoke(absent_root, human=human)

    # Assert: no fictitious example holdings, no second mutation or legacy edit.
    assert first.exit_code == second.exit_code == 0, first.output + second.output
    assert after is not None and after.assets.head is not None
    assert after.info.dataset_revision == before.info.dataset_revision + 1
    assert after.assets.head.content == b"version: 1\nmanual_assets: []\nliabilities: []\n"
    assert read_portfolio_snapshot(absent_root.root, absent_root.provider) == after
    assert live.read_bytes() == b"PRIVATE LIVE SENTINEL\n"
    assert "PRIVATE LIVE SENTINEL" not in first.output + second.output
    if not human:
        created, existing = json.loads(first.output), json.loads(second.output)
        assert created["created"] is True and existing["created"] is False
        assert created["path"] is existing["path"] is None
        assert created["revision_id"] == existing["revision_id"]
        assert created["_meta"]["dataset_revision"] == after.info.dataset_revision
        assert "_repository_meta" not in created
        from tests.test_json_schemas import _load_schema, _validator_for

        _validator_for(_load_schema("networth_init.schema.json")).validate(created)
    validated = CliRunner().invoke(
        app,
        ["--data-dir", str(absent_root.root), "networth", "validate", "--json"],
        obj={"activation_evidence_provider": absent_root.provider},
    )
    assert validated.exit_code == 0, validated.output
    assert json.loads(validated.output)["manual_assets"] == 0


@pytest.mark.parametrize("content", [b"version: 1\nmanual_assets: []\n", b"PRIVATE INVALID: ["])
def test_existing_selected_bytes_are_never_replaced(tmp_path: Path, content: bytes) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "assets.yaml").write_bytes(content)
    root = _activate(source, tmp_path)
    before = read_portfolio_snapshot(root.root, root.provider)
    result = _invoke(root)
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["created"] is False
    assert read_portfolio_snapshot(root.root, root.provider) == before
    assert "PRIVATE INVALID" not in result.output


def test_concurrent_config_write_wins_without_initializer_overwrite(
    absent_root: QueryRoot, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = initialization.read_portfolio_snapshot
    content = b"version: 1\nmanual_assets: []\nliabilities: []\n# concurrent owner\n"

    def read_then_write(*args, **kwargs):
        snapshot = original(*args, **kwargs)
        StorageMutationFacade(absent_root.root, absent_root.provider).replace_config(
            ConfigDocument.from_validated_yaml("assets", content, parser_version="test")
        )
        return snapshot

    monkeypatch.setattr(initialization, "read_portfolio_snapshot", read_then_write)
    result = _invoke(absent_root)
    assert result.exit_code != 0
    after = original(absent_root.root, absent_root.provider)
    assert after is not None and after.assets.head is not None
    assert after.assets.head.content == content and after.info.dataset_revision == 1
    assert "concurrent owner" not in result.output
    assert not (absent_root.root / "assets.yaml").exists()


def test_missing_activation_evidence_cannot_initialize_or_fall_back(absent_root: QueryRoot) -> None:
    before = read_portfolio_snapshot(absent_root.root, absent_root.provider)
    result = _invoke(absent_root, evidence=False)
    assert result.exit_code != 0
    assert read_portfolio_snapshot(absent_root.root, absent_root.provider) == before
    assert not (absent_root.root / "assets.yaml").exists()


def test_preserved_unselected_configuration_is_not_treated_as_absent(tmp_path: Path) -> None:
    source = tmp_path / "source"
    nested = source / "nested/assets.yaml"
    nested.parent.mkdir(parents=True)
    nested.write_bytes(b"version: 1\nmanual_assets: []\n# PRIVATE PRESERVED\n")
    root = _activate(source, tmp_path)
    before = read_portfolio_snapshot(root.root, root.provider)
    assert before is not None and before.assets.selection_state == "unselected"
    result = _invoke(root)
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["created"] is False and payload["selection_state"] == "unselected"
    assert read_portfolio_snapshot(root.root, root.provider) == before
    validated = CliRunner().invoke(
        app,
        ["--data-dir", str(root.root), "networth", "validate", "--json"],
        obj={"activation_evidence_provider": root.provider},
    )
    assert validated.exit_code == 1, validated.output
    invalid = json.loads(validated.output)
    assert invalid["exists"] is True and invalid["valid"] is False
    assert invalid["selection_state"] == "unselected"
    assert "PRIVATE PRESERVED" not in result.output + validated.output
    from tests.test_json_schemas import _load_schema, _validator_for

    _validator_for(_load_schema("networth_validate.schema.json")).validate(invalid)
