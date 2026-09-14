"""Canonical rules export inputs and rendering from one detached revision."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import typer

from finjuice.pipeline.analysis_source import analysis_metadata, read_analysis_source
from finjuice.pipeline.cli.output import ErrorCode, ExitCode, emit_error, info
from finjuice.pipeline.cli.utils import get_activation_evidence_provider
from finjuice.pipeline.config import Config
from finjuice.pipeline.tagging.models import TagRule
from finjuice.pipeline.tagging.rules_yaml_io import load_rules_bytes


@dataclass(frozen=True)
class RepositoryRulesExport:
    """Captured source bytes and their validated display projection."""

    content: bytes
    rules: list[TagRule]
    metadata: dict[str, Any]


def load_repository_rules_export(
    ctx: typer.Context, config: Config, *, command: str, json_output: bool
) -> RepositoryRulesExport | None:
    """Select canonical rules once; return None only for legacy authority."""
    metadata: dict[str, Any] | None = None
    try:
        snapshot = read_analysis_source(config.data_dir, get_activation_evidence_provider(ctx))
        if snapshot is None:
            return None
        selection = snapshot.rules
        head = selection.head
        metadata = analysis_metadata(snapshot, "legacy_rules_export.v1")
        metadata["rules_revision_id"] = head.revision_id if head is not None else None
        if head is None and selection.selection_state == "absent" and not selection.revisions:
            emit_error(
                "Canonical rules were not found.",
                error_code=ErrorCode.RULES_FILE_NOT_FOUND,
                exit_code=(
                    1 if command == "rules export" and not json_output else ExitCode.USAGE_ERROR
                ),
                json_output=json_output,
                command=command,
                meta_extras=metadata,
            )
        if head is None or selection.selection_state != "selected":
            raise ValueError("Canonical rules require explicit selection.")
        if head.parsed_status != "parsed":
            raise ValueError("Canonical rules are not marked parsed.")
        rules = load_rules_bytes(head.content)
        return RepositoryRulesExport(head.content, rules, metadata)
    except typer.Exit:
        raise
    except Exception:
        emit_error(
            "Canonical rules could not be exported; inspect the selected rules configuration.",
            error_code=ErrorCode.VALIDATION_FAILED,
            exit_code=ExitCode.VALIDATION_ERROR,
            json_output=json_output,
            command=command,
            meta_extras=metadata,
        )
        raise AssertionError("emit_error must exit") from None


def show_repository_rules_revision(source: RepositoryRulesExport) -> None:
    """Label human output without changing exported file contents."""
    info(
        f"Canonical rules; repository revision {source.metadata['dataset_revision']}; "
        f"generation {source.metadata['dataset_generation']}"
    )


def _render_repository_rules_export(
    source: RepositoryRulesExport,
    config: Config,
    *,
    format_type: str,
    output: Path | None,
    stats: bool,
) -> None:
    """Render the existing human formats, writing only captured derived bytes."""
    from finjuice.pipeline.tagging.suggestions import (
        format_rules_as_banksalad_guide,
        format_rules_as_markdown,
    )

    show_repository_rules_revision(source)
    if not source.rules:
        typer.echo("📋 등록된 규칙이 없습니다.")
        return
    typer.echo(f"📋 {len(source.rules)}개의 규칙을 내보냅니다.\n")
    if format_type == "yaml":
        content = source.content
    elif format_type == "banksalad":
        content = format_rules_as_banksalad_guide(source.rules, include_stats=stats).encode("utf-8")
    elif format_type == "markdown":
        content = format_rules_as_markdown(source.rules, include_stats=stats).encode("utf-8")
    else:
        typer.echo(f"❌ Unknown format: {format_type}", err=True)
        typer.echo("Supported formats: yaml, banksalad, markdown", err=True)
        raise typer.Exit(code=1)
    if output is None:
        typer.echo(content.decode("utf-8"))
        return
    try:
        from finjuice.pipeline.export.canonical_output import write_canonical_output

        write_canonical_output(config, output, content)
    except Exception:
        emit_error(
            "Canonical rules output could not be written to the selected destination.",
            error_code=ErrorCode.FILE_ACCESS_ERROR,
            exit_code=1,
            command="rules export",
            meta_extras=source.metadata,
        )
    typer.echo(f"✅ {output}에 저장되었습니다.")


def render_repository_rules_export(
    source: RepositoryRulesExport,
    config: Config,
    *,
    format_type: str,
    output: Path | None,
    stats: bool,
) -> None:
    """Keep source-derived formatter failures outside legacy exception logging."""
    try:
        _render_repository_rules_export(
            source, config, format_type=format_type, output=output, stats=stats
        )
    except typer.Exit:
        raise
    except Exception:
        emit_error(
            "Canonical rules output could not be rendered.",
            error_code=ErrorCode.VALIDATION_FAILED,
            exit_code=ExitCode.VALIDATION_ERROR,
            command="rules export",
            meta_extras=source.metadata,
        )
