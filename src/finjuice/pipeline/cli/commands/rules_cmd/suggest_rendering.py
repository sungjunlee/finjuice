"""Human-readable Rich rendering for ``finjuice rules suggest``.

Owns merchant-context formatting, the suggestion table, and apply dry-run
previews. The Typer command, JSON payloads, and interactive apply stay in
:mod:`finjuice.pipeline.cli.commands.rules_cmd.suggest`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rich.table import Table

from finjuice.pipeline.cli.output import console


def _format_suggestion_category(suggestion: dict[str, Any]) -> str:
    """Format the major/minor Banksalad category pair."""
    category = suggestion.get("banksalad_category") or {}
    parts = [category.get("major"), category.get("minor")]
    normalized = [part for part in parts if part]
    return " / ".join(normalized) if normalized else "미분류"


def _format_time_patterns(suggestion: dict[str, Any]) -> str:
    """Format time pattern percentages for terminal display."""
    time_patterns = suggestion.get("time_patterns") or {}
    weekday_pct = float(time_patterns.get("weekday_pct") or 0.0)
    lunch_pct = float(time_patterns.get("lunch_pct") or 0.0)
    return f"평일 {weekday_pct:.0%}\n점심 {lunch_pct:.0%}"


def _format_similar_merchants(suggestion: dict[str, Any]) -> str:
    """Format similar merchant hints for terminal display."""
    similar_merchants = suggestion.get("similar_merchants") or []
    if not similar_merchants:
        return "-"

    return "\n".join(
        f"{candidate['merchant']} ({candidate['category']}, ₩{candidate['avg_amount']:,.0f})"
        for candidate in similar_merchants
    )


def _format_signal_summary(suggestion: dict[str, Any]) -> str:
    """Format memo and recurrence signals for terminal display."""
    sample_memos = suggestion.get("sample_memos") or []
    recurring = "반복" if suggestion.get("is_recurring") else "단발성"
    memo_text = ", ".join(sample_memos) if sample_memos else "-"
    return f"{recurring}\n메모: {memo_text}"


def _format_default_action(suggestion: dict[str, Any]) -> str:
    """Format the recommended curation action for terminal display."""
    if suggestion.get("default_action") == "skip_rule":
        return "규칙 생성 비추천\nskip_rule"
    return "규칙 후보\ncreate_rule"


def _render_suggestion_context_table(
    suggestions: list[dict[str, Any]],
    *,
    title: str = "Merchant Context",
) -> None:
    """Render a Rich table with merchant context fields."""
    if not suggestions:
        return

    table = Table(title=title, show_header=True)
    table.add_column("Merchant")
    table.add_column("Stats", justify="right")
    table.add_column("Active")
    table.add_column("Banksalad")
    table.add_column("Payment")
    table.add_column("Time")
    table.add_column("Signals")
    table.add_column("Similar")
    table.add_column("Pattern")
    table.add_column("Action")

    for suggestion in suggestions:
        active_months = suggestion.get("active_months") or []
        active_text = ", ".join(active_months) if active_months else "-"
        table.add_row(
            suggestion["merchant"],
            (
                f"{int(suggestion['transaction_count']):,}건\n"
                f"평균 ₩{float(suggestion['avg_amount']):,.0f}\n"
                f"총액 ₩{float(suggestion['total_amount']):,.0f}"
            ),
            active_text,
            _format_suggestion_category(suggestion),
            suggestion.get("payment_method") or "-",
            _format_time_patterns(suggestion),
            _format_signal_summary(suggestion),
            _format_similar_merchants(suggestion),
            suggestion["pattern"],
            _format_default_action(suggestion),
        )

    console.print()
    console.print(table)

    for suggestion in suggestions:
        console.print(
            (
                f"[bold]{suggestion['merchant']}[/bold] | "
                f"avg ₩{float(suggestion['avg_amount']):,.0f} | "
                f"months {', '.join(suggestion.get('active_months') or ['-'])}"
            )
        )
        console.print(
            f"  Banksalad: {_format_suggestion_category(suggestion)} | "
            f"Payment: {suggestion.get('payment_method') or '-'}"
        )
        console.print(
            f"  Time: {_format_time_patterns(suggestion).replace(chr(10), ', ')} | "
            f"Pattern: {suggestion['pattern']}"
        )
        console.print(f"  Samples: {', '.join(suggestion.get('sample_memos') or ['-'])}")
        console.print(f"  Similar: {_format_similar_merchants(suggestion).replace(chr(10), ', ')}")
        if suggestion.get("default_action") == "skip_rule":
            console.print("  Action: 규칙 생성 비추천 (payment_gateway)")
        console.print()


def _render_apply_dry_run(suggestions: list[dict[str, Any]], rules_file: Path) -> None:
    """Show what would be added to rules.yaml without persisting changes."""
    import yaml

    from finjuice.pipeline.tagging.suggestions import (
        build_rule_dict_from_suggestion,
        is_auto_apply_eligible,
    )

    console.print()
    console.print(f"[bold cyan]🔍 Dry Run[/bold cyan] [dim]Would update {rules_file}[/dim]")

    if suggestions:
        _render_suggestion_context_table(suggestions, title="Dry-Run Merchant Context")
        auto_apply_suggestions = [
            suggestion for suggestion in suggestions if is_auto_apply_eligible(suggestion)
        ]
        auto_apply_skipped = [
            suggestion for suggestion in suggestions if not is_auto_apply_eligible(suggestion)
        ]

        if auto_apply_suggestions:
            console.print("\n[bold]Would add these rules:[/bold]")
            for suggestion in auto_apply_suggestions:
                snippet = yaml.safe_dump(
                    [build_rule_dict_from_suggestion(suggestion)],
                    allow_unicode=True,
                    sort_keys=False,
                ).strip()
                console.print(snippet, style="dim")
                console.print()
        else:
            console.print("\n[bold]Would add these rules:[/bold] -")

        if auto_apply_skipped:
            console.print("\n[bold]Auto-apply skipped:[/bold]")
            for suggestion in auto_apply_skipped:
                reason = suggestion.get("ambiguous_reason") or "not_auto_apply_eligible"
                console.print(f"- {suggestion['merchant']} ({reason})")
            console.print()

    console.print("[yellow]Dry run: no changes made[/yellow]")
