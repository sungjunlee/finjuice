"""Suggestion implementation for rules CLI commands."""

import logging
import sys
from pathlib import Path
from typing import Any, Optional

import typer
from rich.table import Table

from finjuice.pipeline.cli.output import ErrorCode, ExitCode, console, emit, emit_error
from finjuice.pipeline.cli.privacy import PrivacyProfile, apply_privacy_profile, privacy_meta
from finjuice.pipeline.cli.utils import get_config
from finjuice.pipeline.config import Config

from .shared import (
    _append_rule_mutation_audit_event,
    _augment_suggestion_stats,
    _rules_suggest_count_payload,
    _stats_float,
    _stats_int,
)

logger = logging.getLogger(__name__)


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


def _compute_rules_suggest_json(
    config: Config,
    top_n: int,
    min_count: int,
    apply: bool,
    yes: bool,
    tag_after: bool,
    preview: bool,
    dry_run: bool,
    json_output: bool,
    privacy: PrivacyProfile = PrivacyProfile.RAW,
    file_id: str | None = None,
) -> dict[str, Any]:
    """Compute JSON payload for `rules suggest`."""
    from finjuice.pipeline.tagging.suggestions import (
        apply_suggestion_to_rules,
        build_rule_dict_from_suggestion,
        generate_merchant_context,
        get_suggestion_coverage_stats,
        is_auto_apply_eligible,
    )

    if not config.csv_base_dir.exists():
        if config.data_dir.exists():
            emit_error(
                f"No transaction data found at {config.csv_base_dir}. "
                "Run 'finjuice ingest' to import XLSX files.",
                error_code=ErrorCode.NO_DATA,
                exit_code=ExitCode.NO_DATA,
                suggestion="finjuice ingest",
                json_output=json_output,
                command="rules suggest",
                privacy=privacy,
            )
        else:
            emit_error(
                f"No transaction data found at {config.csv_base_dir}. "
                "Run 'finjuice init' to set up, then 'finjuice ingest'.",
                error_code=ErrorCode.DATA_DIR_NOT_INITIALIZED,
                exit_code=ExitCode.USAGE_ERROR,
                suggestion="finjuice init",
                json_output=json_output,
                command="rules suggest",
                privacy=privacy,
            )

    if dry_run and not apply:
        emit_error(
            "Cannot use --dry-run without --apply.",
            error_code=ErrorCode.INVALID_ARGS,
            exit_code=ExitCode.USAGE_ERROR,
            json_output=json_output,
            command="rules suggest",
            privacy=privacy,
        )

    if apply and not yes and not dry_run:
        emit_error(
            "Cannot use --apply with --json in interactive mode. "
            "Use --apply --yes for headless operation.",
            error_code=ErrorCode.INVALID_ARGS,
            exit_code=ExitCode.USAGE_ERROR,
            json_output=json_output,
            command="rules suggest",
            privacy=privacy,
        )

    stats = _augment_suggestion_stats(
        get_suggestion_coverage_stats(config.data_dir, file_id=file_id)
    )
    if file_id is not None and _stats_int(stats, "total_count") == 0:
        emit_error(
            f"No transactions found for file_id '{file_id}'.",
            error_code=ErrorCode.NO_DATA,
            exit_code=ExitCode.NO_DATA,
            json_output=json_output,
            command="rules suggest",
            privacy=privacy,
        )
    untagged_count = _stats_int(stats, "untagged_count")
    suggestable_untagged_count = _stats_int(stats, "suggestable_untagged_count")
    coverage_before = _stats_float(stats, "coverage_before_pct")

    if suggestable_untagged_count == 0:
        if untagged_count > 0:
            message = "No suggestable untagged transactions after excluding transfers."
        else:
            message = "All transactions are tagged."
        result: dict[str, Any] = {
            **_rules_suggest_count_payload(stats),
            "suggestions": [],
            "message": message,
        }
        if apply and dry_run:
            result.update(
                {
                    "dry_run": True,
                    "rules_file": str(config.rules_file),
                    "rules_file_modified": False,
                    "would_apply": [],
                    "message": "Dry run: no changes made",
                }
            )
        return result

    suggestions = generate_merchant_context(
        data_dir=config.data_dir,
        rules_file=config.rules_file,
        top_n=top_n,
        min_count=min_count,
        file_id=file_id,
    )
    auto_apply_suggestions = [
        suggestion for suggestion in suggestions if is_auto_apply_eligible(suggestion)
    ]
    auto_apply_skipped = [
        suggestion for suggestion in suggestions if not is_auto_apply_eligible(suggestion)
    ]

    if apply and dry_run:
        return {
            "dry_run": True,
            "rules_file": str(config.rules_file),
            "rules_file_modified": False,
            **_rules_suggest_count_payload(stats),
            "suggestions": suggestions,
            "auto_apply_skipped": [
                {
                    "merchant": suggestion["merchant"],
                    "reason": suggestion.get("ambiguous_reason") or "not_auto_apply_eligible",
                    "default_action": suggestion.get("default_action"),
                }
                for suggestion in auto_apply_skipped
            ],
            "would_apply": [
                {
                    "merchant": suggestion["merchant"],
                    "rule": build_rule_dict_from_suggestion(suggestion),
                }
                for suggestion in auto_apply_suggestions
            ],
            "message": "Dry run: no changes made",
        }

    if apply and yes:
        from finjuice.pipeline.tagging.pipeline import run_tagging

        applied_count = 0
        skipped_count = 0

        for suggestion_idx, suggestion in enumerate(suggestions, start=1):
            if not is_auto_apply_eligible(suggestion):
                skipped_count += 1
                continue
            try:
                applied_rule = apply_suggestion_to_rules(suggestion, config.rules_file)
                _append_rule_mutation_audit_event(
                    config,
                    command="rules suggest",
                    action="applied",
                    rule_name=applied_rule.name,
                    change_summary="suggestion rule applied",
                )
                applied_count += 1
            except (OSError, ValueError) as exc:
                logger.warning(
                    "Failed to auto-apply suggestion %s/%s (%s)",
                    suggestion_idx,
                    len(suggestions),
                    type(exc).__name__,
                )
                skipped_count += 1

        coverage_after = coverage_before
        if tag_after and applied_count > 0:
            tag_result = run_tagging(
                csv_base_dir=config.csv_base_dir,
                rules_path=config.rules_file,
                dry_run=False,
            )
            coverage_after = float(tag_result.get("coverage_pct", coverage_before))

        return {
            "applied": applied_count,
            "skipped": skipped_count,
            "auto_apply_skipped": len(auto_apply_skipped),
            **_rules_suggest_count_payload(stats),
            "coverage_before_pct": round(float(coverage_before), 2),
            "coverage_after_pct": round(float(coverage_after), 2),
        }

    return {
        **_rules_suggest_count_payload(stats),
        "suggestions": suggestions,
    }


def _compact_suggested_rule(rule: dict[str, Any] | None) -> dict[str, Any]:
    """Return non-PII fields from a suggested rule payload."""
    if not rule:
        return {}
    compact: dict[str, Any] = {}
    for key in ("category", "tags", "priority"):
        if key in rule:
            compact[key] = rule[key]
    return compact


def _compact_rule_suggestion(suggestion: dict[str, Any]) -> dict[str, Any]:
    """Return compact workflow cues for one rule suggestion."""
    similar_merchants = suggestion.get("similar_merchants") or []
    active_months = suggestion.get("active_months") or []
    return {
        "transaction_count": int(suggestion.get("transaction_count") or 0),
        "active_month_count": len(active_months),
        "is_recurring": bool(suggestion.get("is_recurring")),
        "banksalad_category": suggestion.get("banksalad_category"),
        "time_patterns": suggestion.get("time_patterns"),
        "similar_merchant_count": len(similar_merchants),
        "merchant_kind": suggestion.get("merchant_kind"),
        "ambiguous_reason": suggestion.get("ambiguous_reason"),
        "default_action": suggestion.get("default_action"),
        "auto_apply_eligible": bool(suggestion.get("auto_apply_eligible", True)),
        "suggested_rule": _compact_suggested_rule(suggestion.get("suggested_rule")),
    }


def _compact_rules_suggest_result(result: dict[str, Any]) -> dict[str, Any]:
    """Return `rules suggest` JSON without merchant-level PII samples."""
    compact = {
        key: value
        for key, value in result.items()
        if key not in {"rules_file", "suggestions", "would_apply"}
    }
    suggestions = result.get("suggestions")
    if isinstance(suggestions, list):
        compact["suggestion_count"] = len(suggestions)
        compact["suggestions"] = [
            _compact_rule_suggestion(suggestion)
            for suggestion in suggestions
            if isinstance(suggestion, dict)
        ]

    would_apply = result.get("would_apply")
    if isinstance(would_apply, list):
        compact["would_apply"] = [
            {"rule": _compact_suggested_rule(item.get("rule"))}
            for item in would_apply
            if isinstance(item, dict)
        ]
    auto_apply_skipped = result.get("auto_apply_skipped")
    if isinstance(auto_apply_skipped, list):
        compact["auto_apply_skipped"] = [
            {
                "reason": item.get("reason"),
                "default_action": item.get("default_action"),
            }
            for item in auto_apply_skipped
            if isinstance(item, dict)
        ]
    return compact


def suggest_rules_command(
    ctx: typer.Context,
    top_n: int = typer.Option(
        10,
        "--top",
        "-n",
        help="Number of suggestions to show (default: 10)",
    ),
    min_count: int = typer.Option(
        1,
        "--min-count",
        "-m",
        help="Minimum transaction count for a merchant (default: 1)",
    ),
    output: Optional[Path] = typer.Option(
        None,
        "--output",
        "-o",
        help="Save merchant context report to file",
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        "-a",
        help="Interactively apply suggested rules to rules.yaml",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Apply all suggestions without prompts (use with --apply)",
    ),
    preview: bool = typer.Option(
        False,
        "--preview",
        help="Show merchant context table before next steps",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Preview rules that would be added without modifying rules.yaml",
    ),
    file_id: str | None = typer.Option(
        None,
        "--file-id",
        help="Limit suggestions to transactions imported from a specific file_id",
    ),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
    privacy: PrivacyProfile = typer.Option(
        PrivacyProfile.RAW,
        "--privacy",
        help="Privacy profile for JSON output: raw, redacted, or compact",
    ),
    tag_after: bool = typer.Option(
        True,
        "--tag-after/--no-tag-after",
        help="Re-tag transactions after applying rules (default: True)",
    ),
) -> None:
    """
    Suggest rule patterns with rich merchant context.

    Analyzes untagged merchants with DuckDB and shows context that helps users
    or AI agents decide how to tag them. `--apply --yes` still creates rules
    from the generated pattern plus Banksalad category context.

    Examples:
        finjuice rules suggest              # Show top 10 suggestions
        finjuice rules suggest --top 20     # Show top 20 suggestions
        finjuice rules suggest -o rules.txt # Save to file
        finjuice rules suggest --apply      # Interactively add rules
        finjuice rules suggest --apply --yes   # Auto-apply all suggestions
    """
    from finjuice.pipeline.tagging.suggestions import (
        format_suggestions_report,
        generate_merchant_context,
        get_suggestion_coverage_stats,
    )

    # Get config from context
    config = get_config(ctx)

    try:
        if json_output:
            result = _compute_rules_suggest_json(
                config=config,
                top_n=top_n,
                min_count=min_count,
                apply=apply,
                yes=yes,
                tag_after=tag_after,
                preview=preview,
                dry_run=dry_run,
                json_output=json_output,
                privacy=privacy,
                file_id=file_id,
            )
            emit(
                apply_privacy_profile(
                    result,
                    privacy,
                    compact=_compact_rules_suggest_result,
                ),
                json_output,
                lambda _: None,
                command="rules suggest",
                meta_extras=privacy_meta(privacy),
            )
            return

        if dry_run and not apply:
            typer.echo("Cannot use --dry-run without --apply.", err=True)
            raise typer.Exit(code=2)

        # Check if data directory structure exists
        if not config.csv_base_dir.exists():
            typer.echo(f"❌ No transaction data found at {config.csv_base_dir}", err=True)
            # Check if parent data_dir exists to give correct guidance
            if config.data_dir.exists():
                typer.echo("Run 'finjuice ingest' to import XLSX files.", err=True)
            else:
                typer.echo("Run 'finjuice init' to set up, then 'finjuice ingest'.", err=True)
            raise typer.Exit(code=1)

        stats = _augment_suggestion_stats(
            get_suggestion_coverage_stats(config.data_dir, file_id=file_id)
        )
        if file_id is not None and _stats_int(stats, "total_count") == 0:
            typer.echo(f"❌ No transactions found for file_id '{file_id}'.", err=True)
            raise typer.Exit(code=4)
        untagged_count = _stats_int(stats, "untagged_count")
        suggestable_untagged_count = _stats_int(stats, "suggestable_untagged_count")
        transfer_excluded_untagged_count = _stats_int(stats, "transfer_excluded_untagged_count")

        if suggestable_untagged_count == 0:
            if untagged_count > 0:
                typer.echo(
                    "✅ 규칙 제안 대상 미태그 거래가 없습니다 "
                    f"(이체 제외 미태그 {transfer_excluded_untagged_count}건)."
                )
            else:
                typer.echo("✅ 모든 거래가 태그되었습니다! 규칙 제안이 없습니다.")
            if dry_run:
                typer.echo("Dry run: no changes made")
            return

        total_count = _stats_int(stats, "total_count")
        before_coverage = _stats_float(stats, "coverage_before_pct")

        typer.echo(f"🔍 {suggestable_untagged_count}건의 규칙 제안 대상 미태그 거래 분석 중...")
        if transfer_excluded_untagged_count > 0:
            typer.echo(f"   이체 제외 미태그: {transfer_excluded_untagged_count}건\n")
        else:
            typer.echo()

        suggestions = generate_merchant_context(
            data_dir=config.data_dir,
            rules_file=config.rules_file,
            top_n=top_n,
            min_count=min_count,
            file_id=file_id,
        )

        if not suggestions:
            typer.echo("ℹ️  제안할 규칙이 없습니다.")
            if dry_run:
                typer.echo("Dry run: no changes made")
            return

        if not (apply and dry_run):
            _render_suggestion_context_table(
                suggestions,
                title="Merchant Context Preview" if preview else "Merchant Context",
            )

        # Interactive apply mode
        if apply:
            if dry_run:
                _render_apply_dry_run(suggestions, config.rules_file)
                return

            if not yes and not sys.stdin.isatty():
                typer.echo(
                    "Cannot use --apply in non-interactive mode. "
                    "Use --apply --yes for headless operation.",
                    err=True,
                )
                raise typer.Exit(code=1)
            _interactive_apply_suggestions(
                suggestions=suggestions,
                config=config,
                yes=yes,
                tag_after=tag_after,
                before_coverage=before_coverage,
                total_count=total_count,
            )
            return

        report = format_suggestions_report(suggestions)

        # Save to file if requested
        if output:
            try:
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(report, encoding="utf-8")
                typer.echo(f"✅ 제안사항이 {output}에 저장되었습니다.")
            except OSError as e:
                typer.echo(f"❌ 파일 저장 실패: {e}", err=True)
                raise typer.Exit(code=1)
        # Next steps guidance
        typer.echo("\n💡 Next Steps:")
        typer.echo("  1. Review the merchant context and choose tags/category")
        typer.echo("  2. finjuice rules suggest --apply  →  인터랙티브 적용")
        typer.echo("  3. finjuice rules suggest --apply --yes  →  Banksalad 카테고리로 자동 적용")
        typer.echo("  4. finjuice tag  →  Apply new rules to transactions")

    except typer.Exit:
        raise
    except (FileNotFoundError, PermissionError) as e:
        logger.error("Suggest rules failed (%s)", type(e).__name__)
        emit_error(
            f"File access error: {e}",
            error_code=ErrorCode.FILE_ACCESS_ERROR,
            json_output=json_output,
            command="rules suggest",
            privacy=privacy,
        )
    except KeyboardInterrupt:
        emit_error(
            "Cancelled by user.",
            error_code=ErrorCode.USER_CANCELLED,
            exit_code=ExitCode.USER_CANCELLED,
            json_output=json_output,
            command="rules suggest",
            privacy=privacy,
        )
    except Exception as e:  # CLI top-level handler - keep broad
        logger.error(f"Unexpected error: {type(e).__name__}: {e}", exc_info=True)
        emit_error(
            f"Unexpected error: {e}",
            error_code=ErrorCode.UNEXPECTED_ERROR,
            json_output=json_output,
            command="rules suggest",
            privacy=privacy,
        )


def _interactive_apply_suggestions(
    suggestions: list,
    config: Config,
    yes: bool,
    tag_after: bool,
    before_coverage: float,
    total_count: int,
) -> None:
    """
    Interactively prompt user to apply suggested rules.

    Args:
        suggestions: List of merchant context suggestion dictionaries
        config: CLI config with paths
        yes: If True, apply all without prompts
        tag_after: If True, re-tag after applying
        before_coverage: Coverage percentage before applying
        total_count: Total transaction count
    """
    from finjuice.pipeline.tagging.pipeline import run_tagging
    from finjuice.pipeline.tagging.suggestions import (
        apply_suggestion_to_rules,
        build_rule_dict_from_suggestion,
        is_auto_apply_eligible,
    )

    applied_count = 0
    skipped_count = 0

    typer.echo(f"📋 {len(suggestions)}개의 규칙 제안을 검토합니다.\n")
    typer.echo("  [y] 적용  [n] 건너뛰기  [e] 태그 편집  [s] 나머지 모두 건너뛰기  [q] 종료\n")

    for i, suggestion in enumerate(suggestions, 1):
        default_rule = build_rule_dict_from_suggestion(suggestion)

        # Display suggestion
        typer.echo(f"[{i}/{len(suggestions)}] {suggestion['merchant']}")
        typer.echo(
            f"     거래: {int(suggestion['transaction_count'])}건, "
            f"₩{float(suggestion['total_amount']):,.0f}"
        )
        typer.echo(f'     패턴: "{suggestion["pattern"]}"')
        typer.echo(f"     카테고리: {default_rule.get('category') or '미분류'}")
        typer.echo(f"     기본 태그: {default_rule['tags']}")
        if not is_auto_apply_eligible(suggestion):
            typer.echo("     권장: 규칙 생성 비추천 (payment_gateway)")

        if yes:
            if not is_auto_apply_eligible(suggestion):
                typer.echo("     - auto-apply 제외됨\n")
                skipped_count += 1
                continue
            # Auto mode: apply without prompting
            try:
                applied_rule = apply_suggestion_to_rules(suggestion, config.rules_file)
                _append_rule_mutation_audit_event(
                    config,
                    command="rules suggest",
                    action="applied",
                    rule_name=applied_rule.name,
                    change_summary="suggestion rule applied",
                )
                typer.echo("     ✓ 규칙 추가됨\n")
                applied_count += 1
            except (OSError, ValueError) as e:
                typer.echo(f"     ✗ 실패: {e}\n", err=True)
                skipped_count += 1
            continue

        # Interactive mode
        try:
            response = (
                typer.prompt(
                    "     적용?",
                    default="n",
                    show_default=True,
                )
                .lower()
                .strip()
            )
        except (EOFError, KeyboardInterrupt):
            typer.echo("\n⚠️  중단됨.", err=True)
            break

        if response == "y":
            # Apply as-is
            try:
                applied_rule = apply_suggestion_to_rules(suggestion, config.rules_file)
                _append_rule_mutation_audit_event(
                    config,
                    command="rules suggest",
                    action="applied",
                    rule_name=applied_rule.name,
                    change_summary="suggestion rule applied",
                )
                typer.echo("     ✓ 규칙 추가됨\n")
                applied_count += 1
            except (OSError, ValueError) as e:
                typer.echo(f"     ✗ 실패: {e}\n", err=True)
                skipped_count += 1

        elif response == "e":
            # Edit tags
            tags_input = typer.prompt(
                "     태그 수정 (쉼표 구분)",
                default=", ".join(default_rule["tags"]),
            )
            modified_tags = [t.strip() for t in tags_input.split(",") if t.strip()]

            if not modified_tags:
                typer.echo("     ✗ 태그가 비어있습니다. 건너뜁니다.\n")
                skipped_count += 1
                continue

            try:
                applied_rule = apply_suggestion_to_rules(
                    suggestion, config.rules_file, modified_tags=modified_tags
                )
                _append_rule_mutation_audit_event(
                    config,
                    command="rules suggest",
                    action="applied",
                    rule_name=applied_rule.name,
                    change_summary="suggestion rule applied",
                )
                typer.echo(f"     ✓ 규칙 추가됨 (태그: {modified_tags})\n")
                applied_count += 1
            except (OSError, ValueError) as e:
                typer.echo(f"     ✗ 실패: {e}\n", err=True)
                skipped_count += 1

        elif response == "s":
            # Skip all remaining
            remaining = len(suggestions) - i
            typer.echo(f"     ℹ️  나머지 {remaining}개 건너뜁니다.\n")
            skipped_count += remaining
            break

        elif response == "q":
            # Quit
            typer.echo("\n⚠️  종료합니다.")
            break

        else:
            # n or anything else: skip this one
            typer.echo("     - 건너뜀\n")
            skipped_count += 1

    # Summary
    typer.echo("─" * 50)
    typer.echo(f"📊 결과: {applied_count}개 적용, {skipped_count}개 건너뜀")

    if applied_count == 0:
        typer.echo("\nℹ️  적용된 규칙이 없습니다.")
        return

    # Re-tag if requested
    if tag_after:
        typer.echo("\n🔄 트랜잭션 재태깅 중...")
        try:
            result = run_tagging(
                csv_base_dir=config.csv_base_dir,
                rules_path=config.rules_file,
                dry_run=False,
            )
            after_coverage = result.get("coverage_pct", 0)

            typer.echo("\n📈 커버리지 변화:")
            typer.echo(f"   이전: {before_coverage:.1f}%")
            typer.echo(f"   이후: {after_coverage:.1f}%")
            typer.echo(f"   개선: +{after_coverage - before_coverage:.1f}%p")

        except (ValueError, KeyError, OSError) as e:
            typer.echo(f"\n⚠️  재태깅 실패: {e}", err=True)
            typer.echo("수동으로 'finjuice tag'를 실행하세요.")
    else:
        typer.echo("\n💡 재태깅을 위해 'finjuice tag'를 실행하세요.")
