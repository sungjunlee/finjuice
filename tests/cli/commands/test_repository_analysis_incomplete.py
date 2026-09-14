"""Unmaterialized canonical evidence must not look like complete zero totals."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app
from tests.cli.commands.test_repository_assets import _activate
from tests.cli.commands.test_repository_checkup import _source
from tests.cli.commands.test_repository_query import QueryRoot
from tests.pipeline.checkup.helpers import _tx_row, write_transactions


@pytest.fixture
def incomplete_root(tmp_path: Path) -> QueryRoot:
    source = _source(tmp_path)
    write_transactions(
        source,
        "2026-09",
        [
            _tx_row(
                "2026-09-01",
                -20000,
                "PRIVATE_UNMATERIALIZED",
                category_final="food",
                tags_final="broken[",
            )
        ],
    )
    return _activate(source, tmp_path)


@pytest.mark.parametrize(
    "args",
    [
        ["budget", "status"],
        ["review"],
        ["review", "--all-history"],
        ["checkup"],
        ["checkup", "--fast"],
    ],
)
def test_incomplete_selection_fails_without_partial_or_zero_success(
    incomplete_root: QueryRoot, args: list[str]
) -> None:
    result = CliRunner().invoke(
        app,
        ["--data-dir", str(incomplete_root.root), *args, "--json"],
        obj={"activation_evidence_provider": incomplete_root.provider},
    )
    assert result.exit_code != 0, result.output
    payload = json.loads(result.output)
    assert "error" in payload
    assert "summary" not in payload and "transactions" not in payload and "domains" not in payload
    assert "PRIVATE_UNMATERIALIZED" not in result.output
    assert "20000" not in result.output


@pytest.mark.parametrize(
    "args",
    [
        ["budget", "status", "--month", "2026-08"],
        ["review", "--month", "2026-08"],
        ["budget", "validate"],
    ],
)
def test_unrelated_complete_selection_and_config_validation_remain_available(
    incomplete_root: QueryRoot, args: list[str]
) -> None:
    result = CliRunner().invoke(
        app,
        ["--data-dir", str(incomplete_root.root), *args, "--json"],
        obj={"activation_evidence_provider": incomplete_root.provider},
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["_meta"]["dataset_revision"] == 0
