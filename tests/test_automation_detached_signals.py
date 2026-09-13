"""Detached automation projections preserve legacy signals and connection ownership."""

from copy import deepcopy
from decimal import Decimal

import duckdb
import polars as pl
import pytest

from finjuice.pipeline.automation_large_transactions import (
    _finite_amount,
    large_transactions_from_connection,
)
from finjuice.pipeline.automation_tagging_pressure import tagging_pressure_from_suggestions


def test_tagging_projection_preserves_transfer_counts_and_copies_samples() -> None:
    stats = {
        "total_count": 10,
        "untagged_count": 6,
        "suggestable_untagged_count": 4,
        "transfer_excluded_untagged_count": 2,
        "coverage_before_pct": 40.0,
        "suggestable_coverage_before_pct": 50.0,
    }
    suggestions = [
        {
            "merchant": "sample",
            "transaction_count": 2,
            "total_amount": 20.0,
            "avg_amount": 10.0,
            "sample_memos": ["memo"],
        }
    ]
    before = deepcopy((stats, suggestions))
    signal = tagging_pressure_from_suggestions(stats, suggestions)
    assert signal.status == "present"
    assert signal.total_transactions == 10 and signal.untagged_transactions == 6
    assert signal.suggestable_untagged_transactions == 4
    assert signal.transfer_excluded_untagged_transactions == 2
    assert signal.coverage_pct == 40.0 and signal.suggestable_coverage_pct == 50.0
    signal.merchant_pressure[0].sample_memos.append("new")
    assert (stats, suggestions) == before
    assert tagging_pressure_from_suggestions({}, []).status == "clear"


def test_large_query_preserves_flag_only_exclusion_order_threshold_and_limit() -> None:
    frame = pl.DataFrame(
        {
            "date": [
                "2026-01-01",
                "2026-01-02",
                "2026-01-02",
                "2026-01-03",
                "2026-01-03",
                "2026-01-03",
            ],
            "merchant_raw": ["old", "b", "a", "flag-only", "income", "small"],
            "account": ["card"] * 6,
            "category_final": [""] * 6,
            "amount": [-100.0, -100.0, -100.0, -1000.0, 500.0, -99.0],
            "is_transfer_bool": [False, False, False, True, False, False],
        }
    )
    with duckdb.connect(":memory:") as conn:
        conn.register("transactions", frame.to_arrow())
        signal = large_transactions_from_connection(conn, 100, 2)
        assert signal.count == 3 and signal.status == "present"
        assert [sample.merchant for sample in signal.samples] == ["a", "b"]
        assert all(sample.amount_krw == 100.0 for sample in signal.samples)
        assert all(sample.category is None for sample in signal.samples)
        assert large_transactions_from_connection(conn, 101, 2).status == "clear"
        assert large_transactions_from_connection(conn, 100, 0).samples == []
        assert conn.execute("SELECT 1").fetchone() == (1,)
    assert signal.samples[0].date == "2026-01-02"


def test_nonfinite_query_sample_is_rejected_without_closing_connection() -> None:
    with duckdb.connect(":memory:") as conn:
        conn.execute("""CREATE VIEW transactions AS SELECT '2026-01-01' AS date,
            'sample' AS merchant_raw, NULL AS account, NULL AS category_final,
            '-Infinity'::DOUBLE AS amount, FALSE AS is_transfer_bool""")
        with pytest.raises(ValueError, match="must be finite"):
            large_transactions_from_connection(conn, 100, 1)
        assert conn.execute("SELECT 1").fetchone() == (1,)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), Decimal("NaN"), Decimal("1e999")])
def test_nonfinite_raw_or_converted_amount_is_rejected(value: object) -> None:
    with pytest.raises(ValueError, match="must be finite"):
        _finite_amount(value)
