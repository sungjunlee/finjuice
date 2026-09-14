"""Canonical suggestion rendering and read-only dry runs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import typer

from finjuice.pipeline.cli.output import ErrorCode, ExitCode, emit, emit_error, info
from finjuice.pipeline.cli.privacy import PrivacyProfile, apply_privacy_profile, privacy_meta
from finjuice.pipeline.cli.utils import get_activation_evidence_provider
from finjuice.pipeline.config import Config
from finjuice.pipeline.export.canonical_output import write_canonical_output
from finjuice.pipeline.tagging.suggest_compute_compact import _compact_rules_suggest_result
from finjuice.pipeline.tagging.suggest_compute_stats import _stats_int
from finjuice.pipeline.tagging.suggest_preview import build_suggestion_preview
from finjuice.pipeline.tagging.suggestion_repository import (
    RepositorySuggestions,
    SuggestionReadOptions,
    read_repository_suggestions,
)

from .suggest_rendering import _render_apply_dry_run, _render_suggestion_context_table


@dataclass(frozen=True)
class RepositorySuggestOptions:
    """Existing CLI read and display choices; no writer callbacks."""

    read: SuggestionReadOptions
    output: Path | None
    apply: bool
    dry_run: bool
    preview: bool
    json_output: bool
    privacy: PrivacyProfile


def try_repository_suggest(
    ctx: typer.Context, config: Config, options: RepositorySuggestOptions
) -> bool:
    """Handle canonical authority and return False only for legacy mode."""
    try:
        source = read_repository_suggestions(
            config.data_dir, get_activation_evidence_provider(ctx), options.read
        )
        if source is None:
            return False
        _validate_options(source, options)
        payload = build_suggestion_preview(
            source.stats, source.suggestions, dry_run=options.apply and options.dry_run
        )
        emit(
            apply_privacy_profile(payload, options.privacy, compact=_compact_rules_suggest_result),
            options.json_output,
            lambda _: _render_repository_suggestions(source, config, options),
            command="rules suggest",
            meta_extras={**source.metadata, **privacy_meta(options.privacy)},
        )
        return True
    except typer.Exit:
        raise
    except Exception:
        emit_error(
            "Canonical suggestions could not be evaluated from complete validated data.",
            error_code=ErrorCode.VALIDATION_FAILED,
            exit_code=ExitCode.VALIDATION_ERROR,
            json_output=options.json_output,
            command="rules suggest",
            privacy=options.privacy,
        )
        raise AssertionError("emit_error must exit") from None


def _validate_options(source: RepositorySuggestions, options: RepositorySuggestOptions) -> None:
    if options.dry_run and not options.apply:
        emit_error(
            "Cannot use --dry-run without --apply.",
            error_code=ErrorCode.INVALID_ARGS,
            exit_code=ExitCode.USAGE_ERROR,
            json_output=options.json_output,
            command="rules suggest",
            privacy=options.privacy,
        )
    if options.apply and not options.dry_run:
        raise ValueError("Canonical suggestion application is unavailable.")
    if options.read.file_id is not None and _stats_int(source.stats, "total_count") == 0:
        emit_error(
            "No transactions found for the selected file_id.",
            error_code=ErrorCode.NO_DATA,
            exit_code=ExitCode.NO_DATA,
            json_output=options.json_output,
            command="rules suggest",
            privacy=options.privacy,
            meta_extras=source.metadata,
        )


def _render_repository_suggestions(
    source: RepositorySuggestions, config: Config, options: RepositorySuggestOptions
) -> None:
    info(
        f"Repository revision {source.metadata['dataset_revision']} "
        f"({source.metadata['dataset_generation']})"
    )
    count = _stats_int(source.stats, "suggestable_untagged_count")
    excluded = _stats_int(source.stats, "transfer_excluded_untagged_count")
    if count == 0:
        if _stats_int(source.stats, "untagged_count") > 0:
            typer.echo(f"✅ 규칙 제안 대상 미태그 거래가 없습니다 (이체 제외 미태그 {excluded}건).")
        else:
            typer.echo("✅ 모든 거래가 태그되었습니다! 규칙 제안이 없습니다.")
        if options.dry_run:
            typer.echo("Dry run: no changes made")
        return
    typer.echo(f"🔍 {count}건의 규칙 제안 대상 미태그 거래 분석 중...")
    if excluded:
        typer.echo(f"   이체 제외 미태그: {excluded}건\n")
    if not source.suggestions:
        typer.echo("ℹ️  제안할 규칙이 없습니다.")
        if options.dry_run:
            typer.echo("Dry run: no changes made")
        return
    if options.apply and options.dry_run:
        _render_apply_dry_run(source.suggestions, None)
        return
    _render_suggestion_context_table(
        source.suggestions,
        title="Merchant Context Preview" if options.preview else "Merchant Context",
    )
    _save_repository_report(source, config, options.output)
    typer.echo("\n💡 Next Steps:")
    typer.echo("  1. Review the merchant context and choose tags/category")
    typer.echo("  2. finjuice rules add --help  →  정본 규칙 추가 방법 확인")
    typer.echo("  3. finjuice tag  →  Apply new rules to transactions")


def _save_repository_report(
    source: RepositorySuggestions, config: Config, output: Path | None
) -> None:
    if output is None:
        return
    from finjuice.pipeline.tagging.suggestions import format_suggestions_report

    report = (
        "Authority: repository\n"
        f"Dataset generation: {source.metadata['dataset_generation']}\n"
        f"Dataset revision: {source.metadata['dataset_revision']}\n"
        f"Calculation policy: {source.metadata['calculation_policy']}\n\n"
        + format_suggestions_report(source.suggestions)
    )
    write_canonical_output(config, output, report.encode("utf-8"))
    typer.echo(f"✅ 제안사항이 {output}에 저장되었습니다.")
