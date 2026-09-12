"""CLI tests for finjuice reconcile."""

import json
from pathlib import Path

from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app

runner = CliRunner()


def test_reconcile_json_unmatched_without_ledger(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "transactions").mkdir()
    (data_dir / "imports").mkdir()
    (data_dir / "rules.yaml").write_text("version: 1\nrules: []\n", encoding="utf-8")
    evidence = tmp_path / "evidence.json"
    evidence.write_text(
        json.dumps(
            {
                "evidence": [
                    {
                        "evidence_id": "e1",
                        "occurred_on": "2023-02-11",
                        "amount": "52000",
                        "currency": "KRW",
                        "source_kind": "email_export",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        ["--data-dir", str(data_dir), "reconcile", "--evidence", str(evidence), "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["command"] == "reconcile"
    assert payload["evidence_count"] == 1
    assert payload["payment_count"] == 0
    assert payload["unmatched"] == 1
    assert payload["groups"][0]["reason"] == "missing_ledger_coverage"
    assert payload["groups"][0]["payment_ids"] == []
