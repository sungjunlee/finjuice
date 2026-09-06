"""Structure tests for the reports_polars remaining helper-cluster split.

Spend/transfer frame construction, Polars availability, transfer source
loading, and the mkdir/write/log/return path live in
``reports_polars_cluster`` and must stay identity-equal when re-exported
from ``reports_polars``. CSV load/write helpers stay in
``reports_polars_helpers``. Error translation stays in
``reports_polars_errors``. Public export functions stay in
``reports_polars``.
"""

from __future__ import annotations

import importlib
from pathlib import Path

EXPORT_DIR = Path("src/finjuice/pipeline/export")
CLUSTER_MODULE = "finjuice.pipeline.export.reports_polars_cluster"
REPORTS_MODULE = "finjuice.pipeline.export.reports_polars"
HELPERS_MODULE = "finjuice.pipeline.export.reports_polars_helpers"
ERRORS_MODULE = "finjuice.pipeline.export.reports_polars_errors"

PUBLIC_EXPORT_NAMES = (
    "export_monthly_spend_polars",
    "export_by_tag_polars",
    "export_by_category_polars",
    "export_by_account_polars",
    "export_transfers_polars",
)
CLUSTER_HELPER_NAMES = (
    "_require_polars",
    "_write_report_output",
    "_aggregate_monthly_spend",
    "_aggregate_by_tag",
    "_aggregate_by_category",
    "_aggregate_by_account",
    "_load_transfer_source_df",
    "_aggregate_transfers",
)
HELPERS_NAMES = (
    "_write_csv_with_bom",
    "_load_report_source_df",
)
ERRORS_NAMES = ("_translate_export_errors",)


def test_reports_polars_reexports_cluster_identity() -> None:
    """Cluster helpers stay on reports_polars as re-exports after the split."""
    reports = importlib.import_module(REPORTS_MODULE)
    cluster = importlib.import_module(CLUSTER_MODULE)

    for name in CLUSTER_HELPER_NAMES:
        assert getattr(reports, name) is getattr(cluster, name)

    assert reports.POLARS_AVAILABLE is cluster.POLARS_AVAILABLE
    for name in PUBLIC_EXPORT_NAMES:
        assert callable(getattr(reports, name))


def test_reports_polars_cluster_is_the_unique_home_for_moved_helpers() -> None:
    """The moved cluster is defined exactly once, in reports_polars_cluster."""
    reports = importlib.import_module(REPORTS_MODULE)
    cluster = importlib.import_module(CLUSTER_MODULE)

    for name in CLUSTER_HELPER_NAMES:
        assert getattr(cluster, name).__module__ == CLUSTER_MODULE
        assert getattr(reports, name).__module__ == CLUSTER_MODULE

    for name in PUBLIC_EXPORT_NAMES:
        assert getattr(reports, name).__module__ == REPORTS_MODULE


def test_cluster_lives_in_cluster_module() -> None:
    """Frame construction and export glue should not live in the public module."""
    reports_text = (EXPORT_DIR / "reports_polars.py").read_text(encoding="utf-8")
    cluster_text = (EXPORT_DIR / "reports_polars_cluster.py").read_text(encoding="utf-8")
    helpers_text = (EXPORT_DIR / "reports_polars_helpers.py").read_text(encoding="utf-8")
    errors_text = (EXPORT_DIR / "reports_polars_errors.py").read_text(encoding="utf-8")

    for name in PUBLIC_EXPORT_NAMES:
        assert f"def {name}" in reports_text
        assert f"def {name}" not in cluster_text

    for name in CLUSTER_HELPER_NAMES:
        assert f"def {name}" not in reports_text
        assert f"def {name}" in cluster_text
        assert name in reports_text

    for name in HELPERS_NAMES:
        assert f"def {name}" in helpers_text
        assert f"def {name}" not in cluster_text
        assert f"def {name}" not in reports_text

    for name in ERRORS_NAMES:
        assert f"def {name}" in errors_text
        assert f"def {name}" not in cluster_text
        assert f"def {name}" not in reports_text


def test_export_modules_do_not_import_cli() -> None:
    """Polars report modules must not import finjuice.pipeline.cli.*."""
    for path in (
        EXPORT_DIR / "reports_polars.py",
        EXPORT_DIR / "reports_polars_cluster.py",
        EXPORT_DIR / "reports_polars_helpers.py",
        EXPORT_DIR / "reports_polars_errors.py",
    ):
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            assert "from finjuice.pipeline.cli" not in stripped
            assert "import finjuice.pipeline.cli" not in stripped
