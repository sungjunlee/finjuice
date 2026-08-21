"""Compose-policy tests for named checkup collectors."""

from __future__ import annotations

import ast
from datetime import date
from pathlib import Path

import pytest

from finjuice.pipeline.checkup.compose import (
    NAMED_COLLECTORS,
    collect_checkup_bundle,
    run_named_collector,
)
from finjuice.pipeline.config import Config
from tests.pipeline.checkup.helpers import init_data_dir

_COMPOSE_PATH = (
    Path(__file__).resolve().parents[3] / "src" / "finjuice" / "pipeline" / "checkup" / "compose.py"
)
_COLLECTOR_MODULES = (
    "freshness.py",
    "review.py",
    "budget.py",
    "networth.py",
    "obligations.py",
    "recurring.py",
)


def _imported_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.append(node.module)
    return modules


def test_named_collectors_cover_every_posture_domain() -> None:
    """The composer registry must name every posture collector."""
    assert set(NAMED_COLLECTORS) == {
        "pipeline",
        "review",
        "budget",
        "networth",
        "obligations",
    }


def test_collect_checkup_bundle_only_invokes_named_collectors() -> None:
    """The composer function must call run_named_collector, not inline posture rules."""
    source = Path(_COMPOSE_PATH).read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "collect_checkup_bundle"
    )
    called: set[str] = set()
    for node in ast.walk(function):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            called.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            called.add(node.func.attr)

    assert "run_named_collector" in called
    assert "collect_pipeline_freshness" not in called
    assert "collect_review_pressure" not in called
    assert "collect_budget_posture" not in called
    assert "collect_networth_posture" not in called
    assert "collect_obligation_confirmation" not in called
    assert "_detect_large_recurring_outflow_candidates" not in called


def test_composer_does_not_inline_collector_rule_helpers() -> None:
    """Collector-owned helpers must not be redefined in the composer module."""
    tree = ast.parse(_COMPOSE_PATH.read_text(encoding="utf-8"))
    defined = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert defined.isdisjoint(
        {
            "collect_pipeline_freshness",
            "collect_review_pressure",
            "collect_budget_posture",
            "collect_networth_posture",
            "collect_obligation_confirmation",
            "_detect_large_recurring_outflow_candidates",
        }
    )


def test_collector_modules_do_not_import_composer() -> None:
    """Collector tests stay valid if the composer module is deleted."""
    package_dir = _COMPOSE_PATH.parent
    violations: dict[str, list[str]] = {}
    for filename in _COLLECTOR_MODULES:
        path = package_dir / filename
        imports = [
            module
            for module in _imported_modules(path)
            if module == "finjuice.pipeline.checkup.compose" or module.endswith(".compose")
        ]
        if imports:
            violations[filename] = imports
    assert violations == {}


def test_package_init_does_not_eagerly_import_composer() -> None:
    """Package import must not load compose.py, or deleting it breaks collectors."""
    init_path = _COMPOSE_PATH.parent / "__init__.py"
    tree = ast.parse(init_path.read_text(encoding="utf-8"), filename=str(init_path))
    runtime_imports: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.If):
            continue
        if isinstance(node, ast.Import):
            runtime_imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            runtime_imports.append(node.module)
    assert "finjuice.pipeline.checkup.compose" not in runtime_imports
    assert not any(module.endswith(".compose") for module in runtime_imports)


def test_collector_submodule_import_does_not_load_composer() -> None:
    """Importing a collector must not execute compose.py via package init."""
    import importlib
    import sys

    package = "finjuice.pipeline.checkup"
    sys.modules.pop(f"{package}.compose", None)
    sys.modules.pop(f"{package}.budget", None)
    module = importlib.import_module(f"{package}.budget")
    assert hasattr(module, "collect_budget_posture")
    assert f"{package}.compose" not in sys.modules


def test_run_named_collector_propagates_collector_failures() -> None:
    """A collector exception must abort instead of returning a stand-in result."""

    def boom() -> str:
        raise RuntimeError("collector exploded")

    with pytest.raises(RuntimeError, match="collector exploded"):
        run_named_collector("pipeline", boom)


def test_collector_failure_does_not_mark_partial_bundle_green(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fail-closed compose: a raised collector must not produce a healthy bundle."""

    def boom(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("pipeline collector exploded")

    monkeypatch.setitem(NAMED_COLLECTORS, "pipeline", boom)
    config = Config(data_dir=init_data_dir(tmp_path, "fail-closed"))

    with pytest.raises(RuntimeError, match="pipeline collector exploded"):
        collect_checkup_bundle(config, today=date(2026, 4, 18))
