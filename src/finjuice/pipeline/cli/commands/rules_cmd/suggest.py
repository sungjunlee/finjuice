"""Suggestion implementation for rules CLI commands.

Human rendering lives in
:mod:`finjuice.pipeline.cli.commands.rules_cmd.suggest_rendering`.
Interactive apply lives in
:mod:`finjuice.pipeline.cli.commands.rules_cmd.suggest_apply` and is
re-exported here so existing callers can keep importing from this module.
"""

import logging
import sys
from pathlib import Path
from typing import Any, Optional

import typer

from finjuice.pipeline.cli.output import ErrorCode, ExitCode, emit, emit_error
from finjuice.pipeline.cli.privacy import PrivacyProfile, apply_privacy_profile, privacy_meta
from finjuice.pipeline.cli.utils import get_config
from finjuice.pipeline.config import Config
from finjuice.pipeline.tagging.suggest_compute import (
    SuggestComputeError,
    _augment_suggestion_stats,
    _compact_rules_suggest_result,
    _compute_rules_suggest_json,
    _stats_float,
    _stats_int,
)

from .shared import _append_rule_mutation_audit_event
from .suggest_apply import _interactive_apply_suggestions
from .suggest_rendering import _render_apply_dry_run, _render_suggestion_context_table

logger = logging.getLogger(__name__)


def _audit_applied_suggestion(config: Config, rule_name: str) -> None:
    _append_rule_mutation_audit_event(
        config,
        command="rules suggest",
        action="applied",
        rule_name=rule_name,
        change_summary="suggestion rule applied",
    )


def _emit_suggest_compute_error(
    exc: SuggestComputeError,
    *,
    json_output: bool,
    privacy: PrivacyProfile,
) -> None:
    emit_error(
        exc.message,
        error_code=ErrorCode(exc.error_code),
        exit_code=ExitCode(exc.exit_code),
        suggestion=exc.suggestion,
        json_output=json_output,
        command="rules suggest",
        privacy=privacy,
    )


def _rules_suggest_json_payload(
    config: Config,
    privacy: PrivacyProfile,
    json_output: bool,
    compute_kwargs: dict[str, Any],
) -> dict[str, Any]:
    try:
        return _compute_rules_suggest_json(
            config=config,
            json_output=json_output,
            on_applied=lambda rule_name: _audit_applied_suggestion(config, rule_name),
            **compute_kwargs,
        )
    except SuggestComputeError as exc:
        _emit_suggest_compute_error(exc, json_output=json_output, privacy=privacy)
        raise


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
            result = _rules_suggest_json_payload(
                config,
                privacy,
                json_output,
                {
                    "top_n": top_n,
                    "min_count": min_count,
                    "apply": apply,
                    "yes": yes,
                    "tag_after": tag_after,
                    "preview": preview,
                    "dry_run": dry_run,
                    "file_id": file_id,
                },
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
