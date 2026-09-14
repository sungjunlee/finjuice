"""Authority selection and safe presentation for raw portfolio commands."""

from pathlib import Path
from typing import Any, Literal

import polars as pl
import typer

from finjuice.pipeline.cli.output import info
from finjuice.pipeline.cli.utils import get_activation_evidence_provider
from finjuice.pipeline.portfolio_display import PortfolioDisplay
from finjuice.pipeline.storage.read_facade import read_portfolio_snapshot


class PortfolioReadError(ValueError):
    """An active portfolio could not be read without fallback."""


def load_portfolio_display(ctx: typer.Context, data_dir: Path) -> PortfolioDisplay | None:
    """Select authority once and detach all subsequent display inputs."""
    try:
        snapshot = read_portfolio_snapshot(data_dir, get_activation_evidence_provider(ctx))
        return None if snapshot is None else PortfolioDisplay(snapshot)
    except Exception as exc:
        raise PortfolioReadError("Repository portfolio evidence could not be read.") from exc


def portfolio_meta(display: PortfolioDisplay | None) -> dict[str, object] | None:
    """Preserve revision metadata even for supported empty results."""
    return None if display is None else display.metadata()


def render_portfolio_identity(display: PortfolioDisplay | None, *, json_output: bool) -> None:
    """Identify the calculation source in human output."""
    if display is not None and not json_output:
        meta = display.metadata()
        info(f"Repository revision {meta['dataset_revision']} ({meta['dataset_generation']})")


def safe_portfolio_error(exc: Exception, display: PortfolioDisplay | None) -> str:
    """Keep source rows and parser details out of active CLI errors and logs."""
    if display is not None or isinstance(exc, PortfolioReadError):
        return "Verify repository activation and preserved portfolio source completeness."
    return str(exc)


def latest_portfolio_partition(
    display: PortfolioDisplay, kind: Literal["snapshot", "balance"]
) -> tuple[pl.DataFrame | None, str | None]:
    """Select the latest partition including a latest empty month."""
    months = display.snapshot_months if kind == "snapshot" else display.balance_months
    if not months:
        return None, None
    load = display.snapshot_partition if kind == "snapshot" else display.balance_partition
    return load(months[-1]), months[-1]


def portfolio_holding_evidence(row: dict[str, Any]) -> dict[str, Any]:
    """Expose canonical identity and exact values beside legacy display fields."""
    fields = (
        "asset_snapshot_id",
        "account_entity_id",
        "resource_entity_id",
        "quantity_coefficient",
        "quantity_scale",
        "quantity_lexical",
        "market_value_coefficient",
        "market_value_scale",
        "market_value_lexical",
        "currency_unknown",
    )
    return {key: row[key] for key in fields if key in row}
