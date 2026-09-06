"""Structure tests for the remaining networth partition-selection split.

Snapshot/balance month discovery, partition loading, and as-of selection
live in ``networth_cluster`` and must stay identity-equal when re-exported
from ``networth``. Aggregation compute helpers stay in ``networth_helpers``.
Public ``build_networth_position`` stays in ``networth``.
"""

from __future__ import annotations

import importlib
from pathlib import Path

PIPELINE_DIR = Path("src/finjuice/pipeline")
NETWORTH_MODULE = "finjuice.pipeline.networth"
CLUSTER_MODULE = "finjuice.pipeline.networth_cluster"
HELPERS_MODULE = "finjuice.pipeline.networth_helpers"

PUBLIC_ENTRY_NAMES = (
    "build_networth_position",
    "build_breakdown_rows",
)
CLUSTER_HELPER_NAMES = (
    "discover_snapshot_months",
    "discover_balance_months",
    "load_snapshot_partition",
    "load_latest_snapshot_partition",
    "load_balance_partition",
    "load_latest_balance_partition",
    "select_snapshot_as_of",
    "select_balance_as_of",
    "list_history_snapshots",
)
HELPERS_NAMES = (
    "snapshot_assets_from_selection",
    "balance_assets_from_selection",
    "balance_liabilities_from_selection",
    "merge_asset_sources",
    "merge_liability_sources",
    "normalize_asset_name",
)


def test_networth_reexports_cluster_identity() -> None:
    """Partition-selection helpers stay on networth as re-exports after the split."""
    networth = importlib.import_module(NETWORTH_MODULE)
    cluster = importlib.import_module(CLUSTER_MODULE)

    for name in CLUSTER_HELPER_NAMES:
        assert getattr(networth, name) is getattr(cluster, name)

    for name in PUBLIC_ENTRY_NAMES:
        assert callable(getattr(networth, name))


def test_networth_cluster_is_the_unique_home_for_moved_helpers() -> None:
    """The moved cluster is defined exactly once, in networth_cluster."""
    networth = importlib.import_module(NETWORTH_MODULE)
    cluster = importlib.import_module(CLUSTER_MODULE)

    for name in CLUSTER_HELPER_NAMES:
        assert getattr(cluster, name).__module__ == CLUSTER_MODULE
        assert getattr(networth, name).__module__ == CLUSTER_MODULE

    assert networth.build_networth_position.__module__ == NETWORTH_MODULE
    assert networth.build_breakdown_rows.__module__ == NETWORTH_MODULE
    assert networth.NetWorthPosition.__module__ == NETWORTH_MODULE


def test_cluster_lives_in_cluster_module() -> None:
    """Partition discovery/loading/selection should not live in the public module."""
    networth_text = (PIPELINE_DIR / "networth.py").read_text(encoding="utf-8")
    cluster_text = (PIPELINE_DIR / "networth_cluster.py").read_text(encoding="utf-8")
    helpers_text = (PIPELINE_DIR / "networth_helpers.py").read_text(encoding="utf-8")

    assert "class NetWorthPosition" in networth_text
    for name in PUBLIC_ENTRY_NAMES:
        assert f"def {name}" in networth_text
        assert f"def {name}" not in cluster_text

    for name in CLUSTER_HELPER_NAMES:
        assert f"def {name}" not in networth_text
        assert f"def {name}" in cluster_text
        assert name in networth_text

    for name in HELPERS_NAMES:
        assert f"def {name}" in helpers_text
        assert f"def {name}" not in cluster_text
        assert f"def {name}" not in networth_text
        assert name in networth_text
