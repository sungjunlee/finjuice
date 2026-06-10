"""Context command: emit structured prompt context for external AI agents."""

from __future__ import annotations

import json
from typing import Any

import typer

from finjuice.pipeline.cli.utils import get_config
from finjuice.pipeline.context import (
    DEFAULT_JOURNAL_LIMIT,
    collect_context_bundle,
    resolve_context_budget,
)


def register_context_command(app: typer.Typer) -> None:
    """Register the context command with the root Typer app."""

    @app.command(name="context", rich_help_panel="Analysis")
    def context_command(
        ctx: typer.Context,
        journal_count: int = typer.Option(
            DEFAULT_JOURNAL_LIMIT,
            "--journal",
            min=0,
            help="Number of newest journal entries to include (default: 3).",
        ),
        budget: int | None = typer.Option(
            None,
            "--budget",
            min=1,
            help=(
                "Token budget for the emitted context. "
                "Default: FINJUICE_CONTEXT_BUDGET if set, else 5000. "
                "--budget overrides the env var."
            ),
        ),
        verbose: bool = typer.Option(
            False,
            "--verbose",
            help="Write the section-by-section token breakdown to stderr.",
        ),
        json_output: bool = typer.Option(
            False,
            "--json",
            help="Emit structured JSON instead of the default text summary.",
        ),
    ) -> None:
        """
        Emit a read-only context bundle for external AI agents.

        Pattern:
            agent -> `finjuice context --json` -> compose prompt -> call the agent's own LLM

        The finjuice CLI only emits structured data. It does not call external models.
        """
        config = get_config(ctx)
        resolved_budget = resolve_context_budget(budget)
        bundle = collect_context_bundle(
            config,
            journal_limit=journal_count,
            budget=resolved_budget,
        )

        if verbose:
            typer.echo(_format_token_breakdown(bundle["_meta"]), err=True)

        if json_output:
            typer.echo(json.dumps(bundle, ensure_ascii=False, indent=2))
            return

        typer.echo(_render_text(bundle))


def _render_text(bundle: dict[str, Any]) -> str:
    """Render a plain-text summary that remains clean when piped."""
    snapshot = bundle["status_snapshot"]
    meta = bundle["_meta"]
    lines = ["finjuice context", ""]

    lines.append("Journals")
    if bundle["journals"]:
        for entry in bundle["journals"]:
            created = entry.get("created") or "-"
            data_range = entry.get("data_range") or "-"
            lines.append(f"- {entry['topic']} ({entry['filename']}; {created}; {data_range})")
    else:
        lines.append("- none")

    lines.extend(
        [
            "",
            "Status Snapshot",
            f"- data_range: {snapshot.get('data_range') or '-'}",
            f"- monthly_avg_income: {_format_won(snapshot.get('monthly_avg_income'))}",
            f"- monthly_avg_expense: {_format_won(snapshot.get('monthly_avg_expense'))}",
            f"- savings_rate_3mo: {_format_ratio(snapshot.get('savings_rate_3mo'))}",
            (
                "- structural_savings_monthly_avg: "
                f"{_format_won(snapshot.get('structural_savings_monthly_avg'))}"
            ),
            (
                "- monthly_avg_consumption_expense: "
                f"{_format_won(snapshot.get('monthly_avg_consumption_expense'))}"
            ),
            f"- active_filters: {snapshot.get('active_filters', '-')}",
        ]
    )
    top_categories = snapshot.get("top_categories") or []
    if top_categories:
        category_summary = ", ".join(
            f"{item['name']} {_format_won(item['amount'])}" for item in top_categories
        )
        lines.append(f"- top_categories: {category_summary}")

    lines.extend(["", "Active Goals"])
    if bundle["active_goals"]:
        lines.extend(f"- {goal}" for goal in bundle["active_goals"])
    else:
        lines.append("- none")

    lines.extend(["", "Financial Metadata"])
    financial_metadata = bundle.get("financial_metadata") or {}
    metadata_summary = _summarize_financial_metadata(financial_metadata)
    if metadata_summary:
        lines.extend(f"- {item}" for item in metadata_summary)
    else:
        lines.append("- none")

    lines.extend(["", "Rule Notes"])
    rule_notes = bundle.get("rule_notes") or []
    if rule_notes:
        for note in rule_notes:
            lines.append(f"- {note['rule_name']}: {note['notes']}")
    else:
        lines.append("- none")

    lines.extend(["", "Top Patterns"])
    if bundle["top_patterns"]:
        for pattern in bundle["top_patterns"]:
            delta_value = _format_won(abs(int(pattern["delta_krw"])))
            lines.append(f"- {pattern['label']}: {pattern['direction']} {delta_value}")
    else:
        lines.append("- none")

    lines.extend(
        [
            "",
            (
                "Tokens: "
                f"{_format_token_count(meta['total_tokens_est'])} / "
                f"{_format_token_count(meta['budget'])}"
                + (" (truncated)" if meta["truncated"] else "")
            ),
        ]
    )
    if meta["dropped_sections"]:
        lines.append(f"Dropped: {', '.join(meta['dropped_sections'])}")

    return "\n".join(lines)


def _format_token_breakdown(meta: dict[str, Any]) -> str:
    """Format the stderr token summary used by --verbose."""
    sections = meta["sections"]
    return (
        "context: "
        f"{_format_token_count(meta['total_tokens_est'])} tokens "
        f"(journal {_format_token_count(sections['journals']['tokens'])} / "
        f"status {_format_token_count(sections['status_snapshot']['tokens'])} / "
        f"goals {_format_token_count(sections['active_goals']['tokens'])} / "
        f"metadata {_format_token_count(sections['financial_metadata']['tokens'])} / "
        f"rule_notes {_format_token_count(sections['rule_notes']['tokens'])} / "
        f"patterns {_format_token_count(sections['top_patterns']['tokens'])})"
    )


def _format_token_count(count: int) -> str:
    """Render token counts compactly for summaries."""
    if count >= 1000:
        return f"{count / 1000:.1f}K"
    return str(count)


def _format_won(value: Any) -> str:
    """Format KRW values for plain text."""
    if value is None:
        return "-"
    amount = int(value)
    sign = "-" if amount < 0 else ""
    return f"{sign}₩{abs(amount):,}"


def _format_ratio(value: Any) -> str:
    """Format a snapshot ratio as a percentage string."""
    if value is None:
        return "-"
    return f"{float(value) * 100:.1f}%"


def _summarize_financial_metadata(metadata: dict[str, Any]) -> list[str]:
    """Render compact metadata lines for text context output."""
    lines: list[str] = []
    financial_context = metadata.get("financial_context") or {}
    if isinstance(financial_context, dict):
        income = financial_context.get("income") or {}
        if isinstance(income, dict) and income.get("monthly_estimate") is not None:
            lines.append(f"income monthly_estimate: {_format_won(income['monthly_estimate'])}")

        family = financial_context.get("family") or {}
        if isinstance(family, dict):
            family_parts = []
            if family.get("household_size") is not None:
                family_parts.append(f"household_size={family['household_size']}")
            if family.get("dependents_count") is not None:
                family_parts.append(f"dependents={family['dependents_count']}")
            if family_parts:
                lines.append(f"family: {', '.join(family_parts)}")

        housing = financial_context.get("housing") or {}
        if isinstance(housing, dict):
            housing_parts = []
            if housing.get("status"):
                housing_parts.append(f"status={housing['status']}")
            if housing.get("monthly_payment") is not None:
                housing_parts.append(f"monthly_payment={_format_won(housing['monthly_payment'])}")
            if housing_parts:
                lines.append(f"housing: {', '.join(housing_parts)}")

    obligations = metadata.get("known_obligations") or []
    if isinstance(obligations, list) and obligations:
        monthly_total = sum(
            int(item.get("monthly_amount") or 0) for item in obligations if isinstance(item, dict)
        )
        lines.append(
            f"known_obligations: {len(obligations)} item(s), {_format_won(monthly_total)}/mo"
        )

    return lines
