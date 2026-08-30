"""JSON health/action guidance helpers for ``finjuice networth``.

Owns source flags, snapshot-status labels, signals, and the additive
health/next-step envelope. Typer commands and JSON emission stay in
:mod:`finjuice.pipeline.cli.commands.networth`, which re-exports the
names used by existing callers.
"""

from __future__ import annotations

from typing import Any


def _build_networth_guidance(
    *,
    assets: list[Any],
    liabilities: list[Any],
    net_worth: float,
    primary_source: str = "manual",
) -> dict[str, Any]:
    """Build additive health/action cues for top-level networth JSON."""
    source_flags = _build_source_flags(assets=assets, primary_source=primary_source)
    has_manual_assets = any(getattr(asset, "source", None) == "manual" for asset in assets)
    has_liabilities = bool(liabilities)
    snapshot_status = _resolve_snapshot_status(
        has_overview_data=source_flags["has_overview_data"],
        has_snapshot_data=source_flags["has_snapshot_data"],
        has_manual_assets=has_manual_assets,
        has_liabilities=has_liabilities,
    )

    reasons: list[str] = []
    if snapshot_status in {"manual_only", "liabilities_only"}:
        reasons.append("snapshot_missing")
    elif snapshot_status == "snapshot_only":
        reasons.append("snapshot_only")
    elif snapshot_status == "empty":
        reasons.append("no_asset_data")

    if net_worth < 0:
        reasons.append("negative_net_worth")

    next_steps: list[dict[str, str]] = []
    if snapshot_status in {"snapshot_only", "manual_only", "liabilities_only", "empty"}:
        message = (
            "Add manual assets or liabilities if snapshots do not cover the full balance sheet."
            if snapshot_status == "snapshot_only"
            else "Capture an asset snapshot or confirm assets.yaml coverage."
        )
        next_steps.append(
            {
                "signal": reasons[0],
                "message": message,
                "command": "finjuice assets status --json",
            }
        )
    if net_worth < 0:
        next_steps.append(
            {
                "signal": "negative_net_worth",
                "message": "Inspect the balance-sheet mix behind the negative position.",
                "command": "finjuice networth breakdown --by category --json",
            }
        )

    return {
        "health": {
            "status": "critical" if snapshot_status == "empty" else "warning" if reasons else "ok",
            "reasons": reasons,
        },
        "actionable": bool(reasons),
        "signals": _build_networth_signals(
            snapshot_status=snapshot_status,
            source_flags=source_flags,
            assets=assets,
            liabilities=liabilities,
            net_worth=net_worth,
        ),
        "next_steps": next_steps,
    }


def _build_source_flags(*, assets: list[Any], primary_source: str) -> dict[str, bool]:
    """Return source booleans for networth guidance."""
    return {
        "has_overview_data": primary_source == "overview"
        or any(getattr(asset, "source", None) == "overview" for asset in assets),
        "has_snapshot_data": any(getattr(asset, "source", None) == "snapshot" for asset in assets),
    }


def _resolve_snapshot_status(
    *,
    has_overview_data: bool,
    has_snapshot_data: bool,
    has_manual_assets: bool,
    has_liabilities: bool,
) -> str:
    """Resolve the public networth source status label."""
    candidates = (
        (has_overview_data and has_manual_assets, "overview_and_manual"),
        (has_overview_data, "overview_only"),
        (has_snapshot_data and has_manual_assets, "snapshot_and_manual"),
        (has_snapshot_data, "snapshot_only"),
        (has_manual_assets, "manual_only"),
        (has_liabilities, "liabilities_only"),
    )
    return next((status for condition, status in candidates if condition), "empty")


def _build_networth_signals(
    *,
    snapshot_status: str,
    source_flags: dict[str, bool],
    assets: list[Any],
    liabilities: list[Any],
    net_worth: float,
) -> dict[str, Any]:
    """Build JSON signals while preserving legacy keys when overview is absent."""
    signals = {
        "snapshot_status": snapshot_status,
        "has_snapshot_data": source_flags["has_snapshot_data"],
        "has_manual_assets": any(getattr(asset, "source", None) == "manual" for asset in assets),
        "has_liabilities": bool(liabilities),
        "asset_count": len(assets),
        "liability_count": len(liabilities),
        "net_worth_negative": net_worth < 0,
    }
    if source_flags["has_overview_data"]:
        signals["has_overview_balance_data"] = True
    return signals
