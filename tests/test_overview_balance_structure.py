"""Structure tests for overview balance discovery vs fact/snapshot assembly.

Anchor/table discovery lives in ``overview.balance_table`` and must stay
identity-equal when re-exported from ``overview.balance``. Snapshot/fact
assembly stays defined in ``overview.balance``. Snapshot row mapping stays
in ``overview.snapshot``.
"""

from __future__ import annotations

import importlib
from pathlib import Path

OVERVIEW_DIR = Path("src/finjuice/pipeline/ingest/overview")
BALANCE_MODULE = "finjuice.pipeline.ingest.overview.balance"
TABLE_MODULE = "finjuice.pipeline.ingest.overview.balance_table"

DISCOVERY_NAMES = (
    "_find_balance_table",
    "_collect_balance_anchors",
    "_find_balance_anchor_pair",
    "_balance_anchor_pairs",
    "_detect_side_spec",
)
ASSEMBLY_NAMES = (
    "_parse_balance_block",
    "_build_balance_facts",
)
SNAPSHOT_NAMES = (
    "_assemble_balance_snapshot_row",
    "_BalanceSnapshotFields",
)


def test_balance_reexports_discovery_identity() -> None:
    """Discovery helpers stay on balance as re-exports after the split."""
    balance = importlib.import_module(BALANCE_MODULE)
    table = importlib.import_module(TABLE_MODULE)

    for name in DISCOVERY_NAMES:
        assert getattr(balance, name) is getattr(table, name)

    for name in ASSEMBLY_NAMES:
        assert callable(getattr(balance, name))


def test_balance_table_is_the_unique_home_for_discovery_helpers() -> None:
    """Discovery helpers are defined exactly once, in balance_table."""
    balance = importlib.import_module(BALANCE_MODULE)
    table = importlib.import_module(TABLE_MODULE)

    for name in DISCOVERY_NAMES:
        assert getattr(table, name).__module__ == TABLE_MODULE
        assert getattr(balance, name).__module__ == TABLE_MODULE

    for name in ASSEMBLY_NAMES:
        assert getattr(balance, name).__module__ == BALANCE_MODULE


def test_discovery_bodies_do_not_leak_into_assembly() -> None:
    """Discovery bodies belong to balance_table; assembly bodies stay in balance."""
    balance_text = (OVERVIEW_DIR / "balance.py").read_text(encoding="utf-8")
    table_text = (OVERVIEW_DIR / "balance_table.py").read_text(encoding="utf-8")
    snapshot_text = (OVERVIEW_DIR / "snapshot.py").read_text(encoding="utf-8")

    for name in DISCOVERY_NAMES:
        assert f"def {name}" not in balance_text
        assert f"def {name}" in table_text
        assert name in balance_text
        assert f"def {name}" not in snapshot_text

    for name in ASSEMBLY_NAMES:
        assert f"def {name}" in balance_text
        assert f"def {name}" not in table_text
        assert f"def {name}" not in snapshot_text

    assert "def _assemble_balance_snapshot_row" not in balance_text
    assert "def _assemble_balance_snapshot_row" not in table_text
    assert "def _assemble_balance_snapshot_row" in snapshot_text
    assert "class _BalanceSnapshotFields" not in balance_text
    assert "class _BalanceSnapshotFields" not in table_text
    assert "class _BalanceSnapshotFields" in snapshot_text
    for name in SNAPSHOT_NAMES:
        assert name in balance_text
