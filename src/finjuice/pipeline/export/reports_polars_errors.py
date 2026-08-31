"""Error translation helpers for Polars report generation.

Owns the shared exception-to-``RuntimeError`` translation that every public
export function in :mod:`finjuice.pipeline.export.reports_polars` applies to
its aggregation body. That module re-exports :func:`_translate_export_errors`
so existing callers can keep importing it from there.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager

try:
    import polars as pl
except ImportError:
    pl = None  # type: ignore[assignment]  # optional dep fallback; guarded before use

logger = logging.getLogger(__name__)


@contextmanager
def _translate_export_errors(report_name: str) -> Iterator[None]:
    """Translate report export failures into the public ``RuntimeError`` contract.

    Args:
        report_name: Report identifier embedded in log/error messages
            (e.g. ``"monthly_spend"``, ``"by_tag"``).

    Yields:
        None: The wrapped aggregation/export body runs unchanged.

    Raises:
        RuntimeError: With the same messages the export functions raised
            before the helper split:

            - PermissionError/OSError -> ``Failed to export {report_name} report: ...``
            - ValueError/KeyError -> ``Data validation failed for {report_name}: ...``
            - polars.exceptions.PolarsError -> ``Polars computation failed for {report_name}: ...``
    """
    try:
        yield
    except (PermissionError, OSError) as e:
        logger.error("Cannot write %s report (%s)", report_name, type(e).__name__)
        raise RuntimeError(f"Failed to export {report_name} report: {e}") from e
    except (ValueError, KeyError) as e:
        logger.error(f"Invalid data for {report_name} aggregation: {e}", exc_info=True)
        raise RuntimeError(f"Data validation failed for {report_name}: {e}") from e
    except pl.exceptions.PolarsError as e:
        logger.error(
            f"Polars error in {report_name} export: {type(e).__name__}: {e}", exc_info=True
        )
        raise RuntimeError(f"Polars computation failed for {report_name}: {e}") from e
