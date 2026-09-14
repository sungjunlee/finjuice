"""Actual activation journal output keeps canonical snapshots and external notes distinct."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from finjuice.pipeline.cli.commands import journal as command
from finjuice.pipeline.cli.main import app
from finjuice.pipeline.config import Config
from finjuice.pipeline.insights import collect_status_snapshot
from finjuice.pipeline.storage.mutation_facade import ConfigDocument, StorageMutationFacade
from tests.cli.commands.test_repository_query import QueryRoot
from tests.cli.test_journal import _body, _front_matter, _path_from_output
from tests.pipeline.test_journal_repository import active as _active_fixture

active = _active_fixture


@pytest.fixture(autouse=True)
def fixed_journal_destination(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    destination = tmp_path / "notes"
    monkeypatch.setenv("FINJUICE_JOURNAL_DIR", str(destination))
    monkeypatch.setattr(command, "_now", lambda: datetime(2026, 9, 14, 3, tzinfo=timezone.utc))
    return destination


def _invoke(active: QueryRoot, args: list[str], *, evidence: bool = True):
    return CliRunner().invoke(
        app,
        ["--data-dir", str(active.root), "journal", *args],
        obj={"activation_evidence_provider": active.provider} if evidence else {},
    )


@pytest.mark.parametrize("template", ["diagnosis", "planning", "retrospective"])
def test_new_note_preserves_snapshot_parity_and_template(active: QueryRoot, template: str) -> None:
    baseline = command._snapshot_front_matter(
        collect_status_snapshot(Config(data_dir=active.legacy)).snapshot
    )
    baseline["active_goals"] = None
    result = _invoke(
        active, ["new", "--topic", "sample", "--template", template, "--no-gitignore-check"]
    )
    assert result.exit_code == 0, result.output
    path = _path_from_output(result)
    payload = _front_matter(path)
    assert payload["snapshot"] == baseline
    assert payload["snapshot_metadata"]["dataset_generation"] == active.generation
    assert payload["snapshot_metadata"]["dataset_revision"] == 0
    assert payload["snapshot_metadata"]["calculation_as_of"] is None
    assert payload["snapshot_metadata"]["active_goals_state"] == "not_computed"
    assert _body(path).strip() == command._load_template_body(template).strip()


def test_invalid_goals_persist_nulls_and_static_warning(active: QueryRoot) -> None:
    StorageMutationFacade(active.root, active.provider).replace_config(
        ConfigDocument("goals", b"PRIVATE_GOALS: [", "invalid", None, "test.v1")
    )
    result = _invoke(active, ["new", "--topic", "invalid-goals", "--no-gitignore-check"])
    assert result.exit_code == 0, result.output
    path = _path_from_output(result)
    payload = _front_matter(path)
    fields = payload["snapshot_metadata"]["unavailable_fields"]
    assert len(fields) == 7
    assert all(payload["snapshot"][field] is None for field in fields)
    assert payload["snapshot"]["monthly_avg_income"] == 1000
    assert payload["snapshot_metadata"]["goals_state"] == "unavailable"
    assert payload["snapshot_metadata"]["warning"]
    assert "PRIVATE_GOALS" not in path.read_text() + result.output


@pytest.mark.parametrize("failure", ["authority", "rules"])
def test_failure_creates_no_note_or_directory(
    active: QueryRoot,
    fixed_journal_destination: Path,
    failure: str,
) -> None:
    if failure == "rules":
        StorageMutationFacade(active.root, active.provider).replace_config(
            ConfigDocument("rules", b"PRIVATE_RULES: [", "invalid", None, "test.v1")
        )
    result = _invoke(active, ["new", "--topic", "blocked"], evidence=failure != "authority")
    assert result.exit_code == 3
    assert not fixed_journal_destination.exists()
    assert "PRIVATE_RULES" not in result.output
    assert "Canonical journal could not be created" in result.output


def test_live_poison_and_collision_never_clobber(active: QueryRoot) -> None:
    args = ["new", "--topic", "same", "--no-gitignore-check"]
    first = _invoke(active, args)
    assert first.exit_code == 0
    original_path = _path_from_output(first)
    original_bytes = original_path.read_bytes()
    original_payload = _front_matter(original_path)
    (active.root / "rules.yaml").write_text("PRIVATE: [")
    (active.root / "goals.yaml").write_text("PRIVATE: [")
    second = _invoke(active, args)
    assert second.exit_code == 0
    new_path = _path_from_output(second)
    assert new_path != original_path
    assert original_path.read_bytes() == original_bytes
    assert _front_matter(new_path) == original_payload


def test_list_and_resume_do_not_resolve_repository_authority(
    active: QueryRoot, monkeypatch
) -> None:
    created = _invoke(active, ["new", "--topic", "historical", "--no-gitignore-check"])
    assert created.exit_code == 0
    path = _path_from_output(created)

    def forbidden(*args, **kwargs):
        raise AssertionError("Historical notes must not query current repository authority.")

    monkeypatch.setattr(command, "collect_repository_journal_snapshot", forbidden)
    listed = _invoke(active, ["list", "--json"], evidence=False)
    assert listed.exit_code == 0
    assert path.name in str(json.loads(listed.output))
    resumed = _invoke(active, ["resume"], evidence=False)
    assert resumed.exit_code == 0
    assert _path_from_output(resumed) == path


def test_interactive_canonical_gitignore_callback_writes_regular_file(
    active: QueryRoot,
    fixed_journal_destination: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = fixed_journal_destination.parent
    (parent / ".git").mkdir()
    ignore = parent / ".gitignore"
    ignore.write_text("# existing")
    monkeypatch.setattr(command, "sys", SimpleNamespace(stdin=SimpleNamespace(isatty=lambda: True)))
    monkeypatch.setattr(command.typer, "confirm", lambda *args, **kwargs: True)
    result = _invoke(active, ["new", "--topic", "interactive"])
    assert result.exit_code == 0, result.output
    assert _path_from_output(result).is_file()
    assert ignore.read_text() == "# existing\n_*/\n"


def test_interactive_protected_gitignore_symlink_fails_before_mkdir(
    active: QueryRoot,
    fixed_journal_destination: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = fixed_journal_destination.parent
    (parent / ".git").mkdir()
    protected = active.root / "rules.yaml"
    protected.write_bytes(b"rules: []\n")
    ignore = parent / ".gitignore"
    ignore.symlink_to(protected)
    monkeypatch.setattr(command, "sys", SimpleNamespace(stdin=SimpleNamespace(isatty=lambda: True)))
    monkeypatch.setattr(command.typer, "confirm", lambda *args, **kwargs: True)
    result = _invoke(active, ["new", "--topic", "blocked"])
    assert result.exit_code == 3, result.output
    assert not fixed_journal_destination.exists()
    assert protected.read_bytes() == b"rules: []\n"
    assert ignore.is_symlink()
