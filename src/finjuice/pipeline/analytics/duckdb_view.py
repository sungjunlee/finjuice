"""DuckDB transactions-view lifecycle for analytics.

Owns in-memory connection setup, CSV schema validation, and registration of
the centralized ``transactions`` view. Query methods live on
:class:`~finjuice.pipeline.analytics.duckdb_layer.DuckDBAnalytics`, which
subclasses this type so existing callers keep the same public API.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path
from types import TracebackType
from typing import Any, Optional

from finjuice.pipeline.analytics.duckdb_layer_helpers import (
    DUCKDB_INSTALL_HINT,
    detect_analytics_dependencies,
)
from finjuice.pipeline.analytics.query_builder import build_report_filter_duckdb_where
from finjuice.pipeline.analytics.transaction_frame_registration import register_transaction_frame
from finjuice.pipeline.analytics.transactions_view_sql import build_transactions_source_sql
from finjuice.pipeline.sql_utils import (
    quote_duckdb_identifier,
    quote_duckdb_path_pattern,
    quote_duckdb_string_literal,
)
from finjuice.pipeline.storage.authority import ActivationEvidenceProvider
from finjuice.pipeline.storage.read_facade import read_transaction_snapshot, transaction_frame
from finjuice.pipeline.storage.schema_registry import get_current_schema
from finjuice.pipeline.storage.sqlite.errors import RepositoryIntegrityError
from finjuice.pipeline.storage.sqlite.transaction_completeness import (
    require_transaction_completeness,
)
from finjuice.pipeline.tagging.rules import ReportFilters

DUCKDB_AVAILABLE, duckdb, _ = detect_analytics_dependencies()

# Keep the duckdb_layer logger so CLI JSON paths can suppress init/close noise.
logger = logging.getLogger("finjuice.pipeline.analytics.duckdb_layer")


class DuckDBTransactionsView:
    """In-memory DuckDB connection with the centralized transactions view.

    Args:
        data_dir: Path to data directory containing transactions/ partitions
        memory_limit: Optional memory limit for DuckDB (e.g., "1GB")
        report_filters: Optional report filters applied to the transactions view
        require_transactions: If True, missing CSV partitions raise FileNotFoundError
        source_frame: Optional decoded transaction frame (SQLite read-compat).
            When set without repository authority, replaces CSV with this explicit
            detached frame. A frame cannot override a verified repository snapshot.

    Raises:
        ImportError: If duckdb package is not installed
        FileNotFoundError: If no transaction CSV files are found and required
        RuntimeError: If view creation fails
    """

    def __init__(  # noqa: PLR0913 - preserve frame and authority constructor APIs.
        self,
        data_dir: Path,
        memory_limit: Optional[str] = None,
        report_filters: ReportFilters | None = None,
        require_transactions: bool = True,
        source_frame: Any | None = None,
        *,
        evidence_provider: ActivationEvidenceProvider | None = None,
    ) -> None:
        if not DUCKDB_AVAILABLE:
            raise ImportError(DUCKDB_INSTALL_HINT)

        self.data_dir = Path(data_dir)
        self.partitions_path = self.data_dir / "transactions"
        self.report_filters = report_filters or ReportFilters()
        self._source_frame = source_frame

        self.repository_snapshot = read_transaction_snapshot(self.data_dir, evidence_provider)
        if self.repository_snapshot is not None and source_frame is not None:
            raise ValueError("An explicit frame cannot replace repository authority.")

        # Create in-memory connection for speed
        self.conn = duckdb.connect(":memory:")
        self.conn.execute("SET enable_progress_bar=false")

        # Configure memory limit if specified
        if memory_limit:
            self.conn.execute(f"SET memory_limit={quote_duckdb_string_literal(memory_limit)}")

        # DuckDB uses all available cores by default, no need to configure

        try:
            self.register_transactions_view(require_transactions=require_transactions)
        except Exception:
            self.conn.close()
            raise

        logger.info(
            "DuckDB analytics layer initialized (threads: auto, memory: %s)",
            memory_limit or "unlimited",
        )

    def register_transactions_view(self, *, require_transactions: bool = True) -> None:
        """Create centralized transactions view with type normalization (Issue #184).

        This view abstracts CSV partitions or an injected SQLite read-compat
        frame and provides normalized types (e.g., boolean flags) to simplify
        downstream queries.

        Raises:
            FileNotFoundError: If no transaction CSV files are found.
            RuntimeError: If view creation fails.
        """
        if self.repository_snapshot is not None:
            require_transaction_completeness(self.repository_snapshot)
            self._register_repository_transactions(require_transactions=require_transactions)
            return

        if self._source_frame is not None:
            self._register_frame_as_transactions_view()
            return

        has_files = any(self.partitions_path.glob("*/*/*.csv"))
        if not has_files:
            if not require_transactions:
                logger.debug(
                    "No transaction CSV files found; skipping transaction view registration"
                )
                return
            raise FileNotFoundError(f"No transaction data found in {self.partitions_path}")

        csv_path_literal = quote_duckdb_path_pattern(self.partitions_path)
        self._create_normalized_transactions_views(
            f"""
            CREATE OR REPLACE VIEW transactions_raw AS
            SELECT *
            FROM read_csv(
                {csv_path_literal},
                auto_detect=true,
                union_by_name=true,
                parallel=true
            )
            """
        )

    def _register_frame_as_transactions_view(self) -> None:
        """Register the DuckDB view pipeline from a decoded Polars frame."""
        from finjuice.pipeline.storage.csv_transactions_serialize import _serialize_tag_columns

        frame = self._source_frame
        if frame is None:
            raise RuntimeError("SQLite source frame is missing")
        raw_frame = _serialize_tag_columns(frame)
        self.conn.register("_finjuice_sqlite_raw", raw_frame)
        self._create_normalized_transactions_views(
            "CREATE OR REPLACE VIEW transactions_raw AS SELECT * FROM _finjuice_sqlite_raw"
        )

    def _create_normalized_transactions_views(self, raw_sql: str) -> None:
        """Create ``transactions_raw``/``_source``/``transactions`` from raw SQL."""
        try:
            self.conn.execute(raw_sql)
            source_columns = self._view_columns("transactions_raw")

            self._validate_csv_schema(source_columns)

            source_sql = build_transactions_source_sql(source_columns)
            self.conn.execute(source_sql)
            filter_where = build_report_filter_duckdb_where(self.report_filters)
            view_sql = "CREATE OR REPLACE VIEW transactions AS SELECT * FROM transactions_source"
            if filter_where:
                view_sql += f" WHERE NOT ({filter_where})"
            self.conn.execute(view_sql)
            logger.debug("Created 'transactions' view in DuckDB")
        except duckdb.Error as e:
            logger.error(f"Failed to create transactions view: {e}")
            raise RuntimeError(f"Failed to create transactions view: {e}") from e

    def _register_repository_transactions(self, *, require_transactions: bool) -> None:
        """Register a stable Arrow relation sourced only from the verified repository."""
        assert self.repository_snapshot is not None
        snapshot = self.repository_snapshot
        scopes = {scope.transaction_id: scope for scope in snapshot.scopes}
        identifiers = {row["transaction_id"] for row in snapshot.rows}
        if (
            len(scopes) != len(snapshot.scopes)
            or len(identifiers) != len(snapshot.rows)
            or set(scopes) != identifiers
        ):
            raise RepositoryIntegrityError(
                "Transaction snapshot has invalid partition scope evidence."
            )
        rows = tuple(row for row in snapshot.rows if scopes[row["transaction_id"]].included)
        if require_transactions and not rows:
            raise FileNotFoundError("No transaction data found in the active repository.")
        frame = transaction_frame(replace(snapshot, rows=rows))
        register_transaction_frame(self.conn, frame, self.report_filters)

    def _validate_csv_schema(self, detected_columns: list[str]) -> None:
        """Validate detected CSV columns against the expected schema.

        Checks for critical missing columns and unexpected columns that may
        indicate data corruption or malicious CSV injection.

        Args:
            detected_columns: Column names detected by DuckDB read_csv.
        """
        try:
            metadata_dir = self.data_dir / "metadata"
            schema = get_current_schema(metadata_dir)
            expected_columns = [col["name"] for col in schema["partition_schema"]["columns"]]
        except Exception:
            logger.debug("Could not load schema registry; skipping CSV schema validation")
            return

        detected_set = set(detected_columns)
        expected_set = set(expected_columns)

        critical_columns = {"row_hash", "date", "amount", "datetime", "file_id", "source_row"}
        missing_critical = critical_columns - detected_set
        if missing_critical:
            logger.warning(
                "CSV schema validation: missing critical columns: %s",
                ", ".join(sorted(missing_critical)),
            )

        extra_columns = detected_set - expected_set
        if extra_columns:
            logger.warning(
                "CSV schema validation: unexpected columns detected: %s",
                ", ".join(sorted(extra_columns)),
            )

    def _view_columns(self, view_name: str) -> list[str]:
        """Return column names for an internal DuckDB view."""
        rows = self.conn.execute(f"DESCRIBE {quote_duckdb_identifier(view_name)}").fetchall()
        return [str(row[0]) for row in rows]

    def __enter__(self) -> DuckDBTransactionsView:
        """Context manager entry."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Context manager exit - close connection."""
        self.close()

    def close(self) -> None:
        """Close DuckDB connection and free resources."""
        if self.conn:
            self.conn.close()
            logger.info("DuckDB connection closed")
