"""Query/template guard whole input while show guards its selected partition."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from finjuice.pipeline.analytics.duckdb_layer import DuckDBAnalytics
from finjuice.pipeline.cli.main import app
from finjuice.pipeline.storage.sqlite.errors import RepositoryIntegrityError
from tests.cli.commands.test_repository_analysis_incomplete import (
    incomplete_root as _incomplete_fixture,
)
from tests.cli.commands.test_repository_assets import _activate
from tests.cli.commands.test_repository_checkup import _source
from tests.cli.commands.test_repository_query import QueryRoot
from tests.pipeline.checkup.helpers import _tx_row, write_transactions

incomplete_root = _incomplete_fixture


def _invoke(root: QueryRoot, args: list[str], *, human: bool = False):
    return CliRunner().invoke(
        app,
        ["--data-dir", str(root.root), *args, *([] if human else ["--json"])],
        obj={"activation_evidence_provider": root.provider},
    )


@pytest.mark.parametrize(
    "args",
    [
        ["query", "SELECT count(*) FROM transactions"],
        ["template", "run", "monthly_spend"],
        ["show"],
        ["show", "--month", "2026-09"],
        ["show", "--untagged"],
        ["show", "--merchant", "does-not-match"],
    ],
)
@pytest.mark.parametrize("human", [False, True])
def test_incomplete_scope_fails_before_empty_or_filters(
    incomplete_root: QueryRoot, args: list[str], human: bool
) -> None:
    result = _invoke(incomplete_root, args, human=human)
    assert result.exit_code != 0, result.output
    assert "PRIVATE_UNMATERIALIZED" not in result.output
    assert "20000" not in result.output
    assert str(incomplete_root.root) not in result.output
    if not human:
        payload = json.loads(result.output)
        assert "error" in payload
        assert "rows" not in payload and "transactions" not in payload


@pytest.mark.parametrize(
    "args",
    [
        ["show", "--month", "2026-08"],
        ["show", "--month", "2026-08", "--untagged"],
    ],
)
def test_explicit_complete_month_wins_over_search_all(
    incomplete_root: QueryRoot, args: list[str]
) -> None:
    result = _invoke(incomplete_root, args)
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["_meta"]["dataset_revision"] == 0


def test_complete_latest_does_not_inspect_older_opaque_month(tmp_path: Path) -> None:
    source = _source(tmp_path)
    write_transactions(
        source,
        "2026-07",
        [
            _tx_row(
                "2026-07-01",
                -123,
                "PRIVATE_UNMATERIALIZED",
                category_final="food",
                tags_final="broken[",
            )
        ],
    )
    root = _activate(source, tmp_path)
    result = _invoke(root, ["show"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["_meta"]["dataset_revision"] == 0
    assert _invoke(root, ["show", "--untagged"]).exit_code != 0


@pytest.mark.parametrize("required", [False, True])
def test_duckdb_guard_cannot_be_disabled_by_allow_empty(
    incomplete_root: QueryRoot, required: bool
) -> None:
    with pytest.raises(RepositoryIntegrityError):
        DuckDBAnalytics(
            incomplete_root.root,
            require_transactions=required,
            evidence_provider=incomplete_root.provider,
        )


def test_opaque_only_rows_are_not_no_data(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "rules.yaml").write_text("version: 1\nrules: []\n")
    write_transactions(
        source,
        "2026-09",
        [
            _tx_row(
                "2026-09-01",
                -123,
                "PRIVATE_UNMATERIALIZED",
                category_final="food",
                tags_final="broken[",
            )
        ],
    )
    root = _activate(source, tmp_path)
    for required in (True, False):
        with pytest.raises(RepositoryIntegrityError):
            DuckDBAnalytics(
                root.root, require_transactions=required, evidence_provider=root.provider
            )
    for args in (["query", "SELECT count(*) FROM transactions"], ["show"]):
        result = _invoke(root, args)
        assert result.exit_code != 0
        assert "No transaction data found" not in result.output
        assert "PRIVATE_UNMATERIALIZED" not in result.output
