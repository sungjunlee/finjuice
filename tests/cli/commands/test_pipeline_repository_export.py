"""Pipeline export obtains read authority from its host context."""

from types import SimpleNamespace

import pytest
import typer

from finjuice.pipeline.cli.commands.full_pipeline_orchestrator import compute_full_pipeline_export
from finjuice.pipeline.cli.main import app
from finjuice.pipeline.export.source import RepositoryExportError
from tests.cli.commands.test_repository_mutation_fences import _ActiveRoot
from tests.cli.commands.test_repository_mutation_fences import active_root as _active_root_fixture

active_root = _active_root_fixture


def test_supplied_mutation_facade_cannot_substitute_for_missing_host_read_evidence(
    active_root: _ActiveRoot,
) -> None:
    before = {p: p.read_bytes() for p in (active_root.root / "exports").rglob("*") if p.is_file()}
    ctx = typer.Context(typer.main.get_command(app), obj={})
    with pytest.raises(RepositoryExportError, match="validated source"):
        compute_full_pipeline_export(
            ctx,
            SimpleNamespace(data_dir=active_root.root),
            emit_text=False,
            facade=active_root.facade,
        )
    assert before == {
        p: p.read_bytes() for p in (active_root.root / "exports").rglob("*") if p.is_file()
    }


def test_export_explicitly_forwards_host_evidence(
    active_root: _ActiveRoot, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = active_root.provider
    ctx = typer.Context(typer.main.get_command(app), obj={"activation_evidence_provider": provider})
    captured = {}

    def compute(*args, **kwargs):
        captured.update(kwargs)
        return {"complete": True}

    monkeypatch.setattr("finjuice.pipeline.export.result._compute_export_result", compute)
    result = compute_full_pipeline_export(
        ctx,
        SimpleNamespace(data_dir=active_root.root),
        emit_text=False,
        facade=active_root.facade,
    )
    assert result == {"complete": True}
    assert captured["evidence_provider"] is provider
    assert captured["format_lower"] == "xlsx"
