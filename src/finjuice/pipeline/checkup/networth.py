"""Net worth posture collector for the checkup bundle."""

from __future__ import annotations

from pathlib import Path

from finjuice.pipeline.checkup.models import NetWorthPostureSummary
from finjuice.pipeline.config import Config
from finjuice.pipeline.goals import load_goals_file
from finjuice.pipeline.networth import (
    build_networth_position,
    discover_snapshot_months,
    validate_assets_config_file,
)


def collect_networth_posture(config: Config) -> NetWorthPostureSummary:
    """Summarize aggregated net worth from snapshots, assets.yaml, and goals.yaml."""
    snapshots_dir = config.data_dir / "assets" / "snapshots"
    snapshot_months = discover_snapshot_months(snapshots_dir)
    assets_validation = validate_assets_config_file(config.assets_file, allow_missing_file=True)
    assets_warning: str | None = None

    if not assets_validation.is_valid:
        formatted = "; ".join(issue.format() for issue in assets_validation.issues)
        assets_warning = (
            f"assets.yaml is invalid. {formatted}" if formatted else "assets.yaml is invalid."
        )
        return NetWorthPostureSummary(
            status="invalid",
            actionable=True,
            as_of=None,
            snapshot_months=len(snapshot_months),
            assets_file_exists=assets_validation.exists,
            asset_count=0,
            liability_count=0,
            total_assets=0.0,
            total_liabilities=0.0,
            net_worth=0.0,
            target=_load_networth_target(config.goals_file),
            gap_to_target=None,
            warning=assets_warning,
        )

    position = build_networth_position(snapshots_dir, config.assets_file)
    target = _load_networth_target(config.goals_file)
    gap_to_target = float(target - position.net_worth) if target is not None else None

    warning: str | None = None
    if (
        not snapshot_months
        and not assets_validation.config.manual_assets
        and not assets_validation.config.liabilities
    ):
        warning = "No asset snapshots or assets.yaml entries found for net worth posture."
        status = "missing_data"
        actionable = True
    elif position.net_worth < 0:
        status = "negative"
        actionable = True
    elif target is not None and position.net_worth >= target:
        status = "on_target"
        actionable = False
    elif target is not None:
        status = "tracking"
        actionable = False
    else:
        status = "healthy"
        actionable = False

    return NetWorthPostureSummary(
        status=status,
        actionable=actionable,
        as_of=position.as_of.isoformat() if position.as_of is not None else None,
        snapshot_months=len(snapshot_months),
        assets_file_exists=assets_validation.exists,
        asset_count=len(position.assets),
        liability_count=len(position.liabilities),
        total_assets=position.total_assets,
        total_liabilities=position.total_liabilities,
        net_worth=position.net_worth,
        target=target,
        gap_to_target=gap_to_target,
        warning=warning,
    )


def _load_networth_target(goals_file: Path) -> int | None:
    """Return the optional net worth target from goals.yaml when valid."""
    result = load_goals_file(goals_file)
    if result.document is None:
        return None
    return result.document.net_worth_target
