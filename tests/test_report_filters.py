"""Tests for declarative report_filters loading and predicate builders."""

from __future__ import annotations

import re
import textwrap
from pathlib import Path

import polars as pl
import pytest

from finjuice.pipeline.analytics.query_builder import (
    build_filter_where_clause,
    build_report_filter_duckdb_where,
)
from finjuice.pipeline.storage.report_filter_exprs import (
    build_filter_expr,
    build_report_filter_polars_expr,
    matched_report_filter_rule_indexes,
)
from finjuice.pipeline.tagging.models import (
    ExcludedCategoryFilter,
    ExcludedDateRangeFilter,
    ExcludedMerchantFilter,
    FiltersValidationError,
    ReportFilters,
)
from finjuice.pipeline.tagging.rules_yaml_io import load_report_filters


def _write_rules_file(tmp_path: Path, body: str) -> Path:
    """Write a rules.yaml fixture and return its path."""
    rules_path = tmp_path / "rules.yaml"
    rules_path.write_text(textwrap.dedent(body).strip() + "\n", encoding="utf-8")
    return rules_path


def _parity_fixture_df() -> pl.DataFrame:
    """Fixture rows that exercise all filter types on both engines."""
    return pl.DataFrame(
        {
            "row_hash": [
                "contains_after_since",
                "exact_match",
                "regex_match",
                "contains_before_since",
                "category_match",
                "date_range_match",
                "keep_row",
            ],
            "date": [
                "2026-03-05",
                "2026-03-06",
                "2026-03-07",
                "2026-01-20",
                "2026-03-08",
                "2025-12-25",
                "2026-03-09",
            ],
            "merchant_raw": [
                "서울종합병원 검진센터",
                "INVEST TRANSFER",
                "MOVE-IN IKEA 1",
                "서울종합병원 검진센터",
                "키움증권",
                "이사센터",
                "스타벅스",
            ],
            "category_final": [
                "의료",
                "기타",
                "생활",
                "의료",
                "이체:투자",
                "생활",
                "카페",
            ],
        }
    )


def test_load_report_filters_missing_or_absent_block_returns_empty(tmp_path: Path) -> None:
    """Missing files or missing blocks should resolve to an empty typed container."""
    missing_filters = load_report_filters(tmp_path / "missing-rules.yaml")
    assert missing_filters.total_rules == 0
    assert build_report_filter_polars_expr(missing_filters) is None
    assert build_report_filter_duckdb_where(missing_filters) is None

    rules_path = _write_rules_file(
        tmp_path,
        """
        version: 1
        rules: []
        """,
    )
    absent_block_filters = load_report_filters(rules_path)
    assert absent_block_filters.total_rules == 0
    assert matched_report_filter_rule_indexes(_parity_fixture_df(), absent_block_filters) == set()


def test_load_report_filters_compiles_regex_and_builds_expected_exclusion_set(
    tmp_path: Path,
) -> None:
    """Three merchant match types plus category/date rules should exclude the expected rows."""
    rules_path = _write_rules_file(
        tmp_path,
        """
        version: 1
        report_filters:
          excluded_merchants:
            - pattern: "서울종합병원"
              match_type: "contains"
              reason: "진료 종료"
              since: "2026-02-01"
            - pattern: "INVEST TRANSFER"
              match_type: "exact"
              reason: "투자 이체"
            - pattern: '^MOVE-IN IKEA \\d+$'
              match_type: "regex"
              reason: "정규식 테스트"
          excluded_categories:
            - name: "이체:투자"
              reason: "이체는 지출 아님"
          excluded_date_ranges:
            - start: "2025-12-20"
              end: "2025-12-31"
              reason: "이사 비용"
        rules: []
        """,
    )

    filters = load_report_filters(rules_path)
    assert filters.total_rules == 5
    assert filters.excluded_merchants[2].compiled_pattern is not None
    assert filters.excluded_merchants[2].compiled_pattern is not None
    assert filters.excluded_merchants[2].compiled_pattern.flags & re.IGNORECASE

    df = _parity_fixture_df()
    exclusion_expr = build_report_filter_polars_expr(filters)
    assert exclusion_expr is not None

    excluded_rows = set(df.filter(exclusion_expr)["row_hash"].to_list())
    assert excluded_rows == {
        "contains_after_since",
        "exact_match",
        "regex_match",
        "category_match",
        "date_range_match",
    }
    assert "contains_before_since" not in excluded_rows


def test_invalid_report_filters_raise_structured_validation_errors(tmp_path: Path) -> None:
    """Invalid schema should raise FiltersValidationError with key path details."""
    invalid_match_type_path = _write_rules_file(
        tmp_path,
        """
        version: 1
        report_filters:
          excluded_merchants:
            - pattern: "foo"
              match_type: "wildcard"
              reason: "bad"
        rules: []
        """,
    )

    with pytest.raises(FiltersValidationError) as invalid_match_type:
        load_report_filters(invalid_match_type_path)

    assert "report_filters.excluded_merchants[0].match_type" in str(invalid_match_type.value)
    assert "Accepted values" in str(invalid_match_type.value)
    assert "contains" in str(invalid_match_type.value)

    invalid_date_range_path = _write_rules_file(
        tmp_path,
        """
        version: 1
        report_filters:
          excluded_date_ranges:
            - start: "2026-03-10"
              end: "2026-03-01"
              reason: "bad range"
        rules: []
        """,
    )

    with pytest.raises(FiltersValidationError) as invalid_range:
        load_report_filters(invalid_date_range_path)

    assert "report_filters.excluded_date_ranges[0]" in str(invalid_range.value)
    assert "greater than or equal to 'start'" in str(invalid_range.value)


def test_polars_and_duckdb_report_filter_predicates_exclude_same_rows(tmp_path: Path) -> None:
    """Polars and DuckDB builders must resolve to the same excluded row set."""
    duckdb = pytest.importorskip("duckdb")
    rules_path = _write_rules_file(
        tmp_path,
        """
        version: 1
        report_filters:
          excluded_merchants:
            - pattern: "서울종합병원"
              match_type: "contains"
              reason: "진료 종료"
              since: "2026-02-01"
            - pattern: "INVEST TRANSFER"
              match_type: "exact"
              reason: "투자 이체"
            - pattern: '^MOVE-IN IKEA \\d+$'
              match_type: "regex"
              reason: "정규식 테스트"
          excluded_categories:
            - name: "이체:투자"
              reason: "이체는 지출 아님"
          excluded_date_ranges:
            - start: "2025-12-20"
              end: "2025-12-31"
              reason: "이사 비용"
        rules: []
        """,
    )

    filters = load_report_filters(rules_path)
    df = _parity_fixture_df()

    exclusion_expr = build_filter_expr(filters)
    assert exclusion_expr is not None
    polars_excluded = set(df.filter(exclusion_expr)["row_hash"].to_list())

    where_clause = build_filter_where_clause(filters)
    assert where_clause is not None
    conn = duckdb.connect()
    try:
        conn.register("transactions", df.to_arrow())
        duckdb_excluded = {
            row[0]
            for row in conn.execute(
                f"SELECT row_hash FROM transactions WHERE {where_clause} ORDER BY row_hash"
            ).fetchall()
        }
    finally:
        conn.close()

    assert polars_excluded == duckdb_excluded


def test_duckdb_report_filter_builder_escapes_quote_containing_literals() -> None:
    """DuckDB report filter SQL should keep quoted values inside string literals."""
    filters = ReportFilters(
        excluded_merchants=[
            ExcludedMerchantFilter(
                pattern="Bob's",
                reason="contains quote",
                match_type="contains",
                since="2026-01-01' OR '1'='1",
            ),
            ExcludedMerchantFilter(
                pattern="O'Reilly",
                reason="exact quote",
                match_type="exact",
            ),
            ExcludedMerchantFilter(
                pattern="^A's$",
                reason="regex quote",
                match_type="regex",
            ),
        ],
        excluded_categories=[
            ExcludedCategoryFilter(name="투자's", reason="category quote"),
        ],
        excluded_date_ranges=[
            ExcludedDateRangeFilter(
                start="2026-02-01' OR '1'='1",
                end="2026-02-28' OR '1'='1",
                reason="date quote",
            ),
        ],
    )

    where_clause = build_report_filter_duckdb_where(filters)

    assert where_clause is not None
    assert "Bob''s" in where_clause
    assert "O''Reilly" in where_clause
    assert "^A''s$" in where_clause
    assert "투자''s" in where_clause
    assert "2026-01-01'' OR ''1''=''1" in where_clause
    assert "2026-02-01'' OR ''1''=''1" in where_clause
    assert "2026-02-28'' OR ''1''=''1" in where_clause


def test_matched_report_filter_indexes_count_rules_not_rows(tmp_path: Path) -> None:
    """Matched-rule counting should count filter rules, not excluded rows."""
    rules_path = _write_rules_file(
        tmp_path,
        """
        version: 1
        report_filters:
          excluded_merchants:
            - pattern: "서울종합병원"
              reason: "진료 종료"
          excluded_categories:
            - name: "의료"
              reason: "병원비 제외"
        rules: []
        """,
    )
    filters = load_report_filters(rules_path)
    df = pl.DataFrame(
        {
            "row_hash": ["overlap", "keep"],
            "date": ["2026-03-05", "2026-03-06"],
            "merchant_raw": ["서울종합병원", "스타벅스"],
            "category_final": ["의료", "카페"],
        }
    )

    matched_indexes = matched_report_filter_rule_indexes(df, filters)
    exclusion_expr = build_report_filter_polars_expr(filters)
    assert exclusion_expr is not None

    excluded_row_count = df.filter(exclusion_expr).height
    assert len(matched_indexes) == 2
    assert excluded_row_count == 1
