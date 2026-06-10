"""E2E coverage test for the agent-facing CLI rule loop."""

from __future__ import annotations

import json
import re
from pathlib import Path

import polars as pl
import pytest
from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app

runner = CliRunner()


def _build_transaction(
    row_hash: str,
    date: str,
    merchant_raw: str,
    amount: float,
    *,
    tags_final: str,
    tags_rule: str = "[]",
    category_final: str = "미분류",
    source_row: int,
) -> dict[str, object]:
    """Build a complete transaction row for CLI status/suggest/tag flows."""
    time = f"0{source_row}:00" if source_row < 10 else f"{source_row}:00"
    return {
        "row_hash": row_hash,
        "date": date,
        "time": time,
        "type_raw": "지출",
        "type_norm": "expense",
        "major_raw": "식비",
        "minor_raw": "카페",
        "merchant_raw": merchant_raw,
        "memo_raw": "커피",
        "amount": amount,
        "account": "신한카드",
        "currency": "KRW",
        "counterparty": "",
        "datetime": f"{date}T{time}:00",
        "category_rule": "",
        "category_final": category_final,
        "tags_rule": tags_rule,
        "tags_ai": "[]",
        "tags_manual": "[]",
        "tags_final": tags_final,
        "confidence": 1.0 if tags_final != "[]" else None,
        "needs_review": 0,
        "is_transfer": 0,
        "transfer_group_id": "",
        "file_id": "241001_1",
        "source_row": source_row,
    }


def _write_agent_loop_fixture(data_dir: Path) -> None:
    """Create transactions with one tagged row and two repeated untagged merchants."""
    partition_dir = data_dir / "transactions" / "2024" / "10"
    partition_dir.mkdir(parents=True, exist_ok=True)

    pl.DataFrame(
        [
            _build_transaction(
                "row1",
                "2024-10-01",
                "이디야커피",
                -4500.0,
                tags_final='["카페"]',
                tags_rule='["카페"]',
                category_final="카페",
                source_row=1,
            ),
            _build_transaction(
                "row2",
                "2024-10-02",
                "스타벅스 강남점",
                -6200.0,
                tags_final="[]",
                source_row=2,
            ),
            _build_transaction(
                "row3",
                "2024-10-03",
                "스타벅스 강남점",
                -5800.0,
                tags_final="[]",
                source_row=3,
            ),
        ]
    ).write_csv(partition_dir / "transactions.csv")

    (data_dir / "rules.yaml").write_text(
        """version: 1
rules:
  - name: coffee_idiya
    match: "이디야커피"
    fields: [merchant_raw]
    tags: ["카페"]
    priority: 90
    category: "카페"
""",
        encoding="utf-8",
    )


def _suggested_rule_name(merchant: str) -> str:
    """Mirror the CLI-compatible suggestion naming used by rules suggest."""
    name_base = re.sub(r"\W+", "_", merchant.lower(), flags=re.UNICODE).strip("_")
    return f"suggested_{name_base or 'unknown'}"


@pytest.mark.e2e
def test_agent_loop_status_suggest_add_tag_improves_coverage(tmp_path: Path) -> None:
    """Exercise the public CLI loop an agent would use to improve tag coverage."""
    data_dir = tmp_path / "data"
    _write_agent_loop_fixture(data_dir)

    status_before = runner.invoke(app, ["--data-dir", str(data_dir), "status", "--json"])
    assert status_before.exit_code == 0
    status_before_payload = json.loads(status_before.output)
    before_coverage = status_before_payload["tagging"]["tagging_rate"]
    assert status_before_payload["tagging"]["untagged_count"] == 2

    suggest_result = runner.invoke(app, ["--data-dir", str(data_dir), "rules", "suggest", "--json"])
    assert suggest_result.exit_code == 0
    suggest_payload = json.loads(suggest_result.output)
    assert suggest_payload["untagged_count"] == 2
    assert len(suggest_payload["suggestions"]) == 1

    suggestion = suggest_payload["suggestions"][0]
    assert suggestion["merchant"] == "스타벅스 강남점"
    assert suggestion["banksalad_category"] == {"major": "식비", "minor": "카페"}
    suggested_tags = [
        suggestion["banksalad_category"]["minor"],
        suggestion["banksalad_category"]["major"],
    ]

    add_result = runner.invoke(
        app,
        [
            "--data-dir",
            str(data_dir),
            "rules",
            "add",
            "--name",
            _suggested_rule_name(suggestion["merchant"]),
            "--match",
            suggestion["pattern"],
            "--tags",
            ",".join(tag for tag in suggested_tags if tag),
            "--category",
            suggestion["banksalad_category"]["minor"],
            "--priority",
            "80",
            "--json",
        ],
    )
    assert add_result.exit_code == 0
    add_payload = json.loads(add_result.output)
    assert add_payload["action"] == "added"
    assert add_payload["rule"]["name"] == "suggested_스타벅스_강남점"

    tag_result = runner.invoke(app, ["--data-dir", str(data_dir), "tag", "--json"])
    assert tag_result.exit_code == 0
    tag_payload = json.loads(tag_result.output)
    assert tag_payload["coverage_pct"] > before_coverage
    assert tag_payload["untagged"] == 0

    status_after = runner.invoke(app, ["--data-dir", str(data_dir), "status", "--json"])
    assert status_after.exit_code == 0
    status_after_payload = json.loads(status_after.output)
    assert status_after_payload["tagging"]["tagging_rate"] > before_coverage
    assert status_after_payload["tagging"]["tagging_rate"] == pytest.approx(100.0)
    assert status_after_payload["tagging"]["untagged_count"] == 0
