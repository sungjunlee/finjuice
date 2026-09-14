"""Detached analytics registration preserves repository view semantics."""

from pathlib import Path
from unittest.mock import Mock

import polars as pl
import pytest

from finjuice.pipeline.analytics import duckdb_view
from finjuice.pipeline.analytics.transaction_frame_registration import register_transaction_frame
from finjuice.pipeline.storage.sqlite.transaction_reads import TransactionReadSnapshot
from finjuice.pipeline.storage.sqlite.transaction_scopes import TransactionScope
from finjuice.pipeline.tagging.models import ExcludedCategoryFilter, ReportFilters


def _frame() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "date": ["2026-08-01", None, "2026-08-03", "2026-08-04"],
            "tags_final": [None, "[]", '[""]', '["food","food"]'],
            "is_transfer": ["1", "1", None, "0"],
            "transfer_group_id": ["pair", " ", None, None],
            "category_final": ["keep", "keep", "omit", "keep"],
        }
    )


def test_normalization_and_filter_preserve_unfiltered_source() -> None:
    duckdb = pytest.importorskip("duckdb")
    filters = ReportFilters(excluded_categories=[ExcludedCategoryFilter("omit", "test")])
    with duckdb.connect(":memory:") as conn:
        register_transaction_frame(conn, _frame(), filters)
        assert conn.execute("SELECT typeof(date) FROM transactions_raw LIMIT 1").fetchone() == (
            "DATE",
        )
        assert conn.execute(
            "SELECT tags_list, is_transfer_bool, is_transfer_candidate FROM transactions_source"
        ).fetchall() == [
            (None, True, 1),
            ([], False, 1),
            ([""], False, 0),
            (["food", "food"], False, 0),
        ]
        assert conn.execute("SELECT count(*) FROM transactions").fetchone() == (3,)
        assert conn.execute("SELECT count(*) FROM transactions_source").fetchone() == (4,)


@pytest.mark.parametrize("dates", [["bad", "2026-08-01"], [None, None], []])
def test_invalid_null_and_empty_dates_remain_strings(dates: list[str | None]) -> None:
    duckdb = pytest.importorskip("duckdb")
    frame = pl.DataFrame(
        {"date": dates, "tags_final": [None] * len(dates)},
        schema={"date": pl.String, "tags_final": pl.String},
    )
    with duckdb.connect(":memory:") as conn:
        register_transaction_frame(conn, frame, ReportFilters())
        columns = dict((row[0], row[1]) for row in conn.execute("DESCRIBE transactions").fetchall())
        assert columns["date"] == "VARCHAR"
        assert conn.execute("SELECT date FROM transactions").fetchall() == [(d,) for d in dates]


def test_existing_repository_view_closes_connection_on_registration_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    conn = Mock()
    snapshot = TransactionReadSnapshot(
        info=Mock(),
        rows=({"transaction_id": "present"},),
        rules_content=None,
        scopes=(TransactionScope("present", "2026/08", True),),
    )
    monkeypatch.setattr(duckdb_view, "DUCKDB_AVAILABLE", True)
    monkeypatch.setattr(duckdb_view, "duckdb", Mock(connect=Mock(return_value=conn)))
    monkeypatch.setattr(duckdb_view, "read_transaction_snapshot", Mock(return_value=snapshot))
    monkeypatch.setattr(duckdb_view, "require_transaction_completeness", Mock())
    project = Mock(return_value=_frame())
    monkeypatch.setattr(duckdb_view, "transaction_frame", project)
    register = Mock(side_effect=RuntimeError("registration failed"))
    monkeypatch.setattr(duckdb_view, "register_transaction_frame", register)
    filters = ReportFilters()
    with pytest.raises(RuntimeError, match="registration failed"):
        duckdb_view.DuckDBTransactionsView(tmp_path, report_filters=filters)
    project.assert_called_once_with(snapshot)
    register.assert_called_once_with(conn, project.return_value, filters)
    conn.close.assert_called_once_with()


def test_caller_context_closes_failed_detached_registration() -> None:
    duckdb = pytest.importorskip("duckdb")
    conn = duckdb.connect(":memory:")
    with pytest.raises(duckdb.Error), conn:
        register_transaction_frame(conn, pl.DataFrame({"missing_date": [1]}), ReportFilters())
    with pytest.raises(duckdb.ConnectionException):
        conn.execute("SELECT 1")
