"""Merchant-context DuckDB queries for `finjuice rules suggest`.

This module owns untagged-merchant aggregation SQL, tagged-merchant context
hints, and coverage-stat queries.

Scoring, payment-gateway classification, match-pattern generation, and
suggested-rule candidate payloads live in
:mod:`finjuice.pipeline.tagging.suggestion_scoring`, which re-exports the
public names that existing callers import from that module.
"""

from __future__ import annotations

from pathlib import Path

from finjuice.pipeline.filters import exclude_transfers_sql


def _normalize_suggest_data_dir(path: Path) -> Path:
    """Normalize either a data directory or `transactions/` path to the data dir."""
    candidate = Path(path)
    if candidate.name == "transactions":
        return candidate.parent
    return candidate


def _file_id_filter_sql(file_id: str | None) -> str:
    """Return optional SQL filter for import file_id."""
    if file_id is None:
        return ""
    return " AND file_id = ?"


def _merchant_context_query(file_id: str | None = None) -> str:
    """Return the DuckDB aggregation SQL for untagged merchant context."""
    return f"""
        SELECT
            merchant_raw AS merchant,
            COUNT(*) AS transaction_count,
            SUM(ABS(amount)) AS total_amount,
            AVG(ABS(amount)) AS avg_amount,
            COALESCE(STDDEV_SAMP(ABS(amount)), 0.0) AS amount_stddev,
            LIST(DISTINCT substr(CAST(date AS VARCHAR), 1, 7)) AS active_months,
            MODE(major_raw) AS major_raw,
            MODE(minor_raw) AS minor_raw,
            MODE(account) AS payment_method,
            COUNT(*) FILTER (
                WHERE EXTRACT(DOW FROM CAST(date AS DATE)) BETWEEN 1 AND 5
            ) * 1.0 / COUNT(*) AS weekday_pct,
            COUNT(*) FILTER (
                WHERE TRY_CAST(substr(CAST(time AS VARCHAR), 1, 2) AS INTEGER) BETWEEN 11 AND 13
            ) * 1.0 / COUNT(*) AS lunch_pct,
            COUNT(DISTINCT substr(CAST(date AS VARCHAR), 1, 7)) >= 2 AS is_recurring,
            LIST(DISTINCT memo_raw) FILTER (
                WHERE memo_raw IS NOT NULL AND trim(CAST(memo_raw AS VARCHAR)) != ''
            ) AS sample_memos
        FROM transactions
        WHERE (tags_list IS NULL OR len(tags_list) = 0)
          AND {exclude_transfers_sql()}
          AND merchant_raw IS NOT NULL
          AND trim(CAST(merchant_raw AS VARCHAR)) != ''
          AND NOT regexp_matches(CAST(merchant_raw AS VARCHAR), '^[0-9]+$')
          {_file_id_filter_sql(file_id)}
        GROUP BY merchant_raw
        HAVING COUNT(*) >= ?
        ORDER BY COUNT(*) DESC, merchant_raw ASC
        LIMIT ?
    """


def _similar_merchants_query(file_id: str | None = None) -> str:
    """Return the DuckDB SQL for tagged merchants used as context hints."""
    return f"""
        SELECT
            merchant_raw AS merchant,
            COALESCE(
                NULLIF(trim(CAST(category_rule AS VARCHAR)), ''),
                NULLIF(trim(CAST(minor_raw AS VARCHAR)), ''),
                NULLIF(trim(CAST(major_raw AS VARCHAR)), ''),
                '미분류'
            ) AS category,
            AVG(ABS(amount)) AS avg_amount,
            COUNT(*) AS transaction_count
        FROM transactions
        WHERE (tags_list IS NOT NULL AND len(tags_list) > 0)
          AND {exclude_transfers_sql()}
          AND merchant_raw IS NOT NULL
          AND trim(CAST(merchant_raw AS VARCHAR)) != ''
          AND NOT regexp_matches(CAST(merchant_raw AS VARCHAR), '^[0-9]+$')
          {_file_id_filter_sql(file_id)}
        GROUP BY merchant_raw, category
        HAVING COUNT(*) >= 2
    """


def get_suggestion_coverage_stats(
    data_dir: Path,
    file_id: str | None = None,
) -> dict[str, int | float]:
    """Compute total and untagged counts for `rules suggest` via one DuckDB query."""
    from finjuice.pipeline.analytics.duckdb_layer import DuckDBAnalytics

    normalized_data_dir = _normalize_suggest_data_dir(data_dir)
    untagged_sql = "(tags_list IS NULL OR len(tags_list) = 0)"
    sql = f"""
        SELECT
            COUNT(*) AS total_count,
            COUNT(*) FILTER (WHERE {untagged_sql}) AS untagged_count,
            COUNT(*) FILTER (WHERE {exclude_transfers_sql()}) AS suggestable_total_count,
            COUNT(*) FILTER (
                WHERE {exclude_transfers_sql()}
                  AND {untagged_sql}
            ) AS suggestable_untagged_count,
            COUNT(*) FILTER (WHERE NOT {exclude_transfers_sql()}) AS transfer_excluded_count,
            COUNT(*) FILTER (
                WHERE NOT {exclude_transfers_sql()}
                  AND {untagged_sql}
            ) AS transfer_excluded_untagged_count
        FROM transactions
        {"WHERE file_id = ?" if file_id is not None else ""}
    """

    try:
        with DuckDBAnalytics(normalized_data_dir) as analytics:
            params = [file_id] if file_id is not None else []
            result = analytics.conn.execute(sql, params).pl().to_dicts()
    except FileNotFoundError:
        return {
            "total_count": 0,
            "untagged_count": 0,
            "suggestable_total_count": 0,
            "suggestable_untagged_count": 0,
            "transfer_excluded_count": 0,
            "transfer_excluded_untagged_count": 0,
            "coverage_before_pct": 0.0,
            "suggestable_coverage_before_pct": 0.0,
        }

    if not result:
        return {
            "total_count": 0,
            "untagged_count": 0,
            "suggestable_total_count": 0,
            "suggestable_untagged_count": 0,
            "transfer_excluded_count": 0,
            "transfer_excluded_untagged_count": 0,
            "coverage_before_pct": 0.0,
            "suggestable_coverage_before_pct": 0.0,
        }

    total_count = int(result[0]["total_count"] or 0)
    untagged_count = int(result[0]["untagged_count"] or 0)
    suggestable_total_count = int(result[0]["suggestable_total_count"] or 0)
    suggestable_untagged_count = int(result[0]["suggestable_untagged_count"] or 0)
    transfer_excluded_count = int(result[0]["transfer_excluded_count"] or 0)
    transfer_excluded_untagged_count = int(result[0]["transfer_excluded_untagged_count"] or 0)
    coverage_before = 0.0
    if total_count > 0:
        coverage_before = (total_count - untagged_count) / total_count * 100
    suggestable_coverage_before = 0.0
    if suggestable_total_count > 0:
        suggestable_coverage_before = (
            (suggestable_total_count - suggestable_untagged_count) / suggestable_total_count * 100
        )

    return {
        "total_count": total_count,
        "untagged_count": untagged_count,
        "suggestable_total_count": suggestable_total_count,
        "suggestable_untagged_count": suggestable_untagged_count,
        "transfer_excluded_count": transfer_excluded_count,
        "transfer_excluded_untagged_count": transfer_excluded_untagged_count,
        "coverage_before_pct": round(float(coverage_before), 2),
        "suggestable_coverage_before_pct": round(float(suggestable_coverage_before), 2),
    }
