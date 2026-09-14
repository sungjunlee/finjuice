"""Query/explain SQLite read-path parity against the CSV DuckDB baseline (#436)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from polars.testing import assert_frame_equal
from typer.testing import CliRunner

from finjuice.pipeline.analytics.duckdb_layer import DuckDBAnalytics
from finjuice.pipeline.cli.main import app
from finjuice.pipeline.storage.sqlite.read_compat import (
    GENERATION_ENV_VAR,
    read_transactions_frame,
)
from tests.cli.commands.test_repository_assets import _activate
from tests.cli.commands.test_repository_query import QueryRoot
from tests.conftest import cli_text
from tests.sqlite_compat_data import build_generation, write_csv_mirror

runner = CliRunner()

REPRESENTATIVE_SQL = (
    "SELECT row_hash, date, merchant_raw, amount, category_final, "
    "is_transfer_bool, list_contains(tags_list, '카페') AS has_cafe "
    "FROM transactions ORDER BY datetime, row_hash"
)

EXPLAIN_RULES = """
version: 1
rules:
  - name: cafe
    match: "스타벅스"
    fields: ["merchant_raw"]
    tags: ["카페"]
    category: "카페"
    priority: 50
    enabled: true
"""


@pytest.fixture
def mirrored_dataset(tmp_path: Path) -> dict[str, Path]:
    """Build the same logical dataset as CSV partitions and a SQLite generation."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    write_csv_mirror(data_dir)
    (data_dir / "rules.yaml").write_text(EXPLAIN_RULES, encoding="utf-8")
    database = build_generation(tmp_path / "generation")
    return {"data_dir": data_dir, "database": database, "root": tmp_path}


@pytest.fixture
def activated_dataset(mirrored_dataset: dict[str, Path]) -> QueryRoot:
    """Activate an actual migration of the mirrored CSV/rules input."""
    return _activate(mirrored_dataset["data_dir"], mirrored_dataset["root"])


def _payload_without_volatile_meta(payload: dict[str, Any]) -> dict[str, Any]:
    """Drop timestamp so same-revision JSON envelopes can be compared."""
    meta = dict(payload.get("_meta") or {})
    meta.pop("timestamp", None)
    return {**payload, "_meta": meta}


def _invoke_query_json(data_dir: Path, sql: str, *, provider=None) -> dict[str, Any]:
    """Run ``finjuice query --json`` and return the parsed envelope."""
    result = runner.invoke(
        app,
        ["--data-dir", str(data_dir), "query", sql, "--json", "--limit", "10000"],
        obj={"activation_evidence_provider": provider} if provider else {},
    )
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def _invoke_explain_json(data_dir: Path, query: str, *extra: str, provider=None) -> dict[str, Any]:
    """Run ``finjuice explain --json`` and return the parsed envelope."""
    result = runner.invoke(
        app,
        ["--data-dir", str(data_dir), "explain", query, "--json", *extra],
        obj={"activation_evidence_provider": provider} if provider else {},
    )
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def test_duckdb_queries_match_csv_baseline(mirrored_dataset: dict[str, Path]) -> None:
    """SQLite-backed DuckDB views match CSV DuckDB results on representative SQL."""
    # Arrange
    data_dir = mirrored_dataset["data_dir"]
    sqlite_frame = read_transactions_frame(mirrored_dataset["database"])
    queries = [
        "SELECT COUNT(*) AS n FROM transactions",
        REPRESENTATIVE_SQL,
        "SELECT category_final, COUNT(*) AS n, SUM(amount) AS total "
        "FROM transactions GROUP BY category_final ORDER BY category_final",
        "SELECT row_hash, merchant_raw FROM transactions "
        "WHERE merchant_raw ILIKE '%스타벅스%' ORDER BY row_hash",
    ]

    # Act
    with (
        DuckDBAnalytics(data_dir) as csv_analytics,
        DuckDBAnalytics(
            data_dir,
            require_transactions=False,
            source_frame=sqlite_frame,
        ) as sqlite_analytics,
    ):
        # Assert
        for sql in queries:
            csv_df = csv_analytics.query_readonly(sql).pl()
            sqlite_df = sqlite_analytics.query_readonly(sql).pl()
            assert_frame_equal(csv_df, sqlite_df, check_dtypes=False)


def test_query_environment_cannot_replace_verified_legacy_csv_authority(
    mirrored_dataset: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A generation environment hint is not authority for an inactive legacy root."""
    # Arrange
    data_dir = mirrored_dataset["data_dir"]
    sql = (
        "SELECT merchant_raw, amount, category_final FROM transactions ORDER BY datetime, row_hash"
    )
    csv_json = _invoke_query_json(data_dir, sql)
    csv_human = runner.invoke(app, ["--data-dir", str(data_dir), "query", sql])
    assert csv_human.exit_code == 0, csv_human.output
    monkeypatch.setenv(GENERATION_ENV_VAR, str(mirrored_dataset["root"] / "not-a-generation"))

    # Act
    hinted_json = _invoke_query_json(data_dir, sql)
    hinted_human = runner.invoke(app, ["--data-dir", str(data_dir), "query", sql])

    # Assert
    assert hinted_human.exit_code == 0, hinted_human.output
    assert _payload_without_volatile_meta(hinted_json) == _payload_without_volatile_meta(csv_json)
    assert cli_text(hinted_human) == cli_text(csv_human)
    assert "스타벅스" in cli_text(hinted_human)
    assert "수동분류" in json.dumps(hinted_json["rows"], ensure_ascii=False)


def test_explain_environment_cannot_replace_verified_legacy_csv_authority(
    mirrored_dataset: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both explain output modes retain legacy authority despite an environment hint."""
    # Arrange
    data_dir = mirrored_dataset["data_dir"]
    csv_json = _invoke_explain_json(data_dir, "스타벅스")
    csv_human = runner.invoke(app, ["--data-dir", str(data_dir), "explain", "스타벅스"])
    assert csv_human.exit_code == 0, csv_human.output
    monkeypatch.setenv(GENERATION_ENV_VAR, str(mirrored_dataset["root"] / "not-a-generation"))

    # Act
    hinted_json = _invoke_explain_json(data_dir, "스타벅스")
    hinted_human = runner.invoke(app, ["--data-dir", str(data_dir), "explain", "스타벅스"])

    # Assert
    assert hinted_human.exit_code == 0, hinted_human.output
    assert _payload_without_volatile_meta(hinted_json) == _payload_without_volatile_meta(csv_json)
    assert cli_text(hinted_human) == cli_text(csv_human)
    assert hinted_json["transaction"]["merchant_raw"] == "스타벅스"
    assert hinted_json["transaction"]["row_hash"] == "abc1234567890001"
    assert hinted_json["classification"]["matched_rules"] == ["cafe"]


def test_query_ignores_live_csv_after_verified_activation(
    activated_dataset: QueryRoot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A mutated CSV partition must not change SQLite-backed query results."""
    # Arrange
    data_dir = activated_dataset.root
    csv_path = data_dir / "transactions" / "2024" / "10" / "transactions.csv"
    csv_path.parent.mkdir(parents=True)
    original = activated_dataset.legacy / "transactions" / "2024" / "10" / "transactions.csv"
    stale = original.read_text(encoding="utf-8").replace("스타벅스", "STALE")
    csv_path.write_text(stale, encoding="utf-8")
    monkeypatch.setenv(GENERATION_ENV_VAR, str(activated_dataset.legacy / "not-a-generation"))

    # Act
    payload = _invoke_query_json(
        data_dir,
        "SELECT merchant_raw FROM transactions WHERE row_hash = 'abc1234567890001'",
        provider=activated_dataset.provider,
    )

    # Assert
    assert payload["rows"] == [{"merchant_raw": "스타벅스"}]


def test_query_and_explain_work_without_csv_partitions(
    activated_dataset: QueryRoot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SQLite is the read source of truth even when CSV partitions are absent."""
    # Arrange
    data_dir = activated_dataset.root
    assert not (data_dir / "transactions").exists()
    monkeypatch.setenv(GENERATION_ENV_VAR, str(activated_dataset.legacy / "not-a-generation"))

    # Act
    query_payload = _invoke_query_json(
        data_dir, "SELECT COUNT(*) AS n FROM transactions", provider=activated_dataset.provider
    )
    explain_payload = _invoke_explain_json(
        data_dir, "스타벅스", provider=activated_dataset.provider
    )

    # Assert
    assert query_payload["rows"] == [{"n": 6}]
    assert query_payload["_meta"]["dataset_generation"] == activated_dataset.generation
    assert explain_payload["transaction"]["merchant_raw"] == "스타벅스"


def test_same_revision_query_and_explain_are_deterministic(
    activated_dataset: QueryRoot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Re-running query/explain against one revision yields identical JSON."""
    # Arrange
    data_dir = activated_dataset.root
    monkeypatch.setenv(GENERATION_ENV_VAR, str(activated_dataset.legacy / "not-a-generation"))

    # Act
    first_query = _invoke_query_json(
        data_dir, REPRESENTATIVE_SQL, provider=activated_dataset.provider
    )
    second_query = _invoke_query_json(
        data_dir, REPRESENTATIVE_SQL, provider=activated_dataset.provider
    )
    first_explain = _invoke_explain_json(data_dir, "스타벅스", provider=activated_dataset.provider)
    second_explain = _invoke_explain_json(data_dir, "스타벅스", provider=activated_dataset.provider)

    # Assert
    assert _payload_without_volatile_meta(first_query) == _payload_without_volatile_meta(
        second_query
    )
    assert _payload_without_volatile_meta(first_explain) == _payload_without_volatile_meta(
        second_explain
    )


def test_canonical_query_preserves_manual_category_as_typed_field(
    activated_dataset: QueryRoot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Canonical migration separates the hidden marker into its typed category field."""
    # Arrange
    data_dir = activated_dataset.root
    monkeypatch.setenv(GENERATION_ENV_VAR, str(activated_dataset.legacy / "not-a-generation"))

    # Act
    payload = _invoke_query_json(
        data_dir,
        "SELECT row_hash, category_final, category_manual, tags_manual FROM transactions "
        "WHERE row_hash = 'abc1234567890006'",
        provider=activated_dataset.provider,
    )

    # Assert
    assert payload["row_count"] == 1
    row = payload["rows"][0]
    assert row["category_final"] == "수동분류"
    assert row["category_manual"] == "수동분류"
    assert row["tags_manual"] == "[]"


def test_explicit_source_frame_cannot_override_repository_authority(
    activated_dataset: QueryRoot, mirrored_dataset: dict[str, Path]
) -> None:
    frame = read_transactions_frame(mirrored_dataset["database"])
    with pytest.raises(ValueError, match="explicit frame cannot replace repository authority"):
        DuckDBAnalytics(
            activated_dataset.root,
            source_frame=frame,
            evidence_provider=activated_dataset.provider,
        )


def test_explicit_compat_frame_preserves_legacy_manual_category_marker(
    mirrored_dataset: dict[str, Path],
) -> None:
    """Keep PR502's legacy marker projection coverage on its explicit-frame surface."""
    frame = read_transactions_frame(mirrored_dataset["database"])
    with DuckDBAnalytics(mirrored_dataset["data_dir"], source_frame=frame) as analytics:
        row = (
            analytics.query_readonly(
                "SELECT category_final, tags_manual FROM transactions "
                "WHERE row_hash = 'abc1234567890006'"
            )
            .pl()
            .to_dicts()[0]
        )
    assert row["category_final"] == "수동분류"
    assert "__finjuice_category_override__:수동분류" in str(row["tags_manual"])
