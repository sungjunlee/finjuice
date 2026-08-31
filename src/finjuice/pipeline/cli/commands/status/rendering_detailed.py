"""Detailed snapshot rendering for the ``finjuice status`` command."""

from __future__ import annotations

from typing import Any

from finjuice.pipeline.cli.output import console


def _render_detailed_stats(
    detailed_stats: dict[str, Any],
    detailed_warning: Any,
    top_n: int,
) -> None:
    """Render the optional detailed status snapshot."""
    console.print("[bold cyan]📈 Detailed Snapshot[/bold cyan]")
    if detailed_stats.get("data_range"):
        console.print(f"  Data range: {detailed_stats['data_range']}")
    console.print(f"  Active filters: {detailed_stats.get('active_filters', 0)}")
    console.print(f"  Active goals: {len(detailed_stats.get('active_goals', []))}")

    if detailed_warning:
        console.print(f"  [yellow]{detailed_warning}[/yellow]")
        return

    _render_detailed_amounts(detailed_stats)
    _render_structural_sources(detailed_stats, top_n)
    _render_top_categories(detailed_stats, top_n)


def _render_detailed_amounts(detailed_stats: dict[str, Any]) -> None:
    """Render detailed averages, rates, and structural total."""
    if detailed_stats.get("monthly_avg_income") is not None:
        console.print(f"  월평균 수입: {_format_currency(detailed_stats['monthly_avg_income'])}")
    if detailed_stats.get("monthly_avg_expense") is not None:
        console.print(f"  월평균 지출: {_format_currency(detailed_stats['monthly_avg_expense'])}")
    if detailed_stats.get("monthly_avg_consumption_expense") is not None:
        console.print(
            "  월평균 소비성 지출: "
            f"{_format_currency(detailed_stats['monthly_avg_consumption_expense'])}"
        )
    if detailed_stats.get("residual_savings_rate_3mo") is not None:
        console.print(
            f"  최근 3개월 잔여 현금흐름 저축률: {detailed_stats['residual_savings_rate_3mo']:.0%}"
        )
    if detailed_stats.get("consumption_savings_rate_3mo") is not None:
        console.print(
            f"  최근 3개월 소비 기준 저축률: {detailed_stats['consumption_savings_rate_3mo']:.0%}"
        )
    structural_avg = int(detailed_stats.get("structural_savings_monthly_avg") or 0)
    if structural_avg > 0:
        console.print(f"  월평균 구조적 저축: {_format_currency(structural_avg)}")
    console.print()


def _render_structural_sources(detailed_stats: dict[str, Any], top_n: int) -> None:
    """Render detailed structural savings sources."""
    structural_sources = detailed_stats.get("structural_savings_sources") or []
    if not structural_sources:
        return

    console.print("[bold cyan]💾 구조적 저축[/bold cyan]")
    for source in structural_sources[:top_n]:
        label = str(source.get("label") or source.get("source") or "-")
        monthly_amount = _format_currency(float(source.get("monthly_amount") or 0))
        provenance = str(source.get("source") or "-")
        tags = ", ".join(source.get("tags") or [])
        suffix = f" [{tags}]" if tags else ""
        console.print(f"  - {label}: {monthly_amount}/월 ({provenance}){suffix}")
    console.print()


def _render_top_categories(detailed_stats: dict[str, Any], top_n: int) -> None:
    """Render detailed top categories."""
    top_categories = detailed_stats.get("top_categories") or []
    if not top_categories:
        return

    console.print(f"[bold cyan]📂 Top {top_n} 카테고리[/bold cyan]")
    for index, category in enumerate(top_categories, 1):
        console.print(
            f"  {index}. {category['name']:16} {_format_currency(float(category['amount'])):>12}"
        )
    console.print()


def _format_currency(amount: float) -> str:
    """Format amount as Korean won."""
    if amount >= 100_000_000:
        return f"₩{amount / 100_000_000:.1f}억"
    if amount >= 10_000_000:
        return f"₩{amount / 10_000:.0f}만"
    if amount >= 1_000_000:
        return f"₩{amount / 10_000:.1f}만"
    return f"₩{amount:,.0f}"
