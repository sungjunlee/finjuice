"""Whole-source consumers refuse partial summaries of preserved opaque transactions."""

import json

import pytest
from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app
from tests.cli.commands.test_repository_assets import _activate
from tests.cli.commands.test_repository_checkup import _source
from tests.pipeline.checkup.helpers import _tx_row, write_transactions


@pytest.fixture
def incomplete_summary_root(tmp_path):
    source = _source(tmp_path)
    write_transactions(
        source,
        "2026-09",
        [
            _tx_row(
                "2026-09-01",
                -987654,
                "PRIVATE_INCOMPLETE_MERCHANT",
                category_final="food",
                tags_final="PRIVATE_INVALID_TAG[",
            ),
        ],
    )
    # Empty rules must not short-circuit explanation before completeness validation.
    (source / "rules.yaml").write_text("version: 1\nrules: []\n")
    return _activate(source, tmp_path)


@pytest.mark.parametrize("human", [False, True])
@pytest.mark.parametrize(
    "command",
    [
        ["status"],
        ["status", "--detailed"],
        ["explain", "absent-merchant"],
        ["export", "--format", "xlsx"],
        ["export", "--format", "html", "--period", "2026-08"],
    ],
)
def test_whole_source_summaries_reject_incomplete_month(incomplete_summary_root, command, human):
    root = incomplete_summary_root
    export_dir = root.root / "exports"
    export_dir.mkdir(parents=True)
    previous = export_dir / "previous-report.csv"
    previous.write_bytes(b"previous artifact\n")
    result = CliRunner().invoke(
        app,
        ["--data-dir", str(root.root), "--no-filter", *command, *([] if human else ["--json"])],
        obj={"activation_evidence_provider": root.provider},
    )
    assert result.exit_code != 0, result.output
    assert "PRIVATE_INCOMPLETE" not in result.output
    assert "PRIVATE_INVALID" not in result.output
    assert "987654" not in result.output
    if not human:
        payload = json.loads(result.output)
        assert "error" in payload
        assert (
            payload["error"]["code"]
            == {
                "status": "INSPECTION_FAILED",
                "explain": "QUERY_ERROR",
                "export": "EXPORT_FAILED",
            }[command[0]]
        )
        assert "transactions" not in payload
    assert previous.read_bytes() == b"previous artifact\n"
    assert sorted(path.name for path in export_dir.iterdir()) == [previous.name]


def test_export_dry_run_does_not_claim_partial_plan(incomplete_summary_root):
    root = incomplete_summary_root
    result = CliRunner().invoke(
        app,
        ["--data-dir", str(root.root), "export", "--dry-run", "--json"],
        obj={"activation_evidence_provider": root.provider},
    )
    assert result.exit_code != 0, result.output
    assert json.loads(result.output)["error"]["code"] == "EXPORT_FAILED"
    assert not (root.root / "exports").exists()
