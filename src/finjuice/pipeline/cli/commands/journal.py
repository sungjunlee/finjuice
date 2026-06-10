"""Journal command group for snapshot-backed markdown notes."""

from __future__ import annotations

import logging
import os
import shlex
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import typer
import yaml
from rich.table import Table

from finjuice.pipeline.cli.output import (
    ErrorCode,
    ExitCode,
    console,
    emit_error,
    emit_list,
    info,
    warning,
)
from finjuice.pipeline.cli.utils import get_config
from finjuice.pipeline.insights import StatusSnapshot, collect_status_snapshot
from finjuice.pipeline.journal import JournalEntry, load_journal_entries

logger = logging.getLogger(__name__)

DEFAULT_TEMPLATE = "planning"
MAX_TOPIC_LENGTH = 48
_CONTROL_CHARACTERS = {chr(code) for code in range(32)} | {chr(127)}

journal_app = typer.Typer(
    name="journal",
    help="Create and revisit markdown journals with financial snapshots.",
    no_args_is_help=True,
)


@journal_app.command("new")
def new_entry(
    ctx: typer.Context,
    topic: Optional[str] = typer.Option(
        None,
        "--topic",
        help="Journal topic slug. Defaults to an auto-generated session topic.",
    ),
    template: str = typer.Option(
        DEFAULT_TEMPLATE,
        "--template",
        help="Body template: diagnosis, planning, retrospective.",
    ),
    no_gitignore_check: bool = typer.Option(
        False,
        "--no-gitignore-check",
        help="Skip the local gitignore safety prompt.",
    ),
) -> None:
    """Create a journal entry with snapshot front matter."""
    config = get_config(ctx)
    now = _now()
    journal_dir = _ensure_journal_dir(config.journal_dir)
    non_interactive = not sys.stdin.isatty()

    if not no_gitignore_check and not non_interactive:
        _maybe_prompt_for_gitignore(journal_dir)

    normalized_topic = _resolve_topic(topic, now)
    file_path = _resolve_new_entry_path(journal_dir, normalized_topic, now)
    snapshot_result = collect_status_snapshot(config)
    template_body = _load_template_body(template)

    front_matter = {
        "created": now.isoformat(timespec="seconds"),
        "topic": normalized_topic,
        "data_range": snapshot_result.snapshot.data_range,
        "snapshot": _snapshot_front_matter(snapshot_result.snapshot),
    }
    content = (
        "---\n"
        + yaml.safe_dump(front_matter, allow_unicode=True, sort_keys=False).strip()
        + "\n---\n\n"
        + template_body.strip()
        + "\n"
    )
    file_path.write_text(content, encoding="utf-8")

    if snapshot_result.warning:
        warning(snapshot_result.warning)
    typer.echo(str(file_path.resolve()))


@journal_app.command("list")
def list_entries(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """List journal entries sorted newest first."""
    config = get_config(ctx)
    entries = [entry.to_dict() for entry in load_journal_entries(config.journal_dir)]

    emit_list(
        entries,
        json_output,
        _render_journal_entries,
        command="journal list",
        items_key="entries",
    )


def _render_journal_entries(entries: list[Any]) -> None:
    """Render journal entries as a Rich table."""
    if not entries:
        info("No journal entries found.")
        return

    table = Table(title="Journal Entries")
    table.add_column("Filename", style="cyan")
    table.add_column("Topic", style="green")
    table.add_column("Created")
    table.add_column("Size", justify="right")

    for entry in entries:
        table.add_row(
            str(entry.get("filename", "")),
            str(entry.get("topic", "")),
            str(entry.get("created") or "-"),
            f"{int(entry.get('size_bytes') or 0):,} B",
        )

    console.print(table)


@journal_app.command("resume")
def resume_entry(
    ctx: typer.Context,
    slug_or_date: Optional[str] = typer.Argument(
        None,
        help="Newest entry by default, or match by filename substring / exact YYYY-MM-DD.",
    ),
    open_in_editor: bool = typer.Option(
        False,
        "--open",
        help="Open the matched file in $EDITOR.",
    ),
) -> None:
    """Resolve the latest or matching journal entry."""
    config = get_config(ctx)
    entries = load_journal_entries(config.journal_dir)
    if not entries:
        emit_error(
            "No journal entries found.",
            error_code=ErrorCode.FILE_NOT_FOUND,
            exit_code=ExitCode.GENERAL_ERROR,
            command="journal resume",
        )

    entry = _select_entry(entries, slug_or_date)
    if entry is None:
        emit_error(
            f"No journal entry matched: {slug_or_date}",
            error_code=ErrorCode.FILE_NOT_FOUND,
            exit_code=ExitCode.GENERAL_ERROR,
            command="journal resume",
        )

    if open_in_editor:
        _open_in_editor(entry.path)

    typer.echo(str(entry.path.resolve()))


def _snapshot_front_matter(snapshot: StatusSnapshot) -> dict[str, Any]:
    """Convert the shared snapshot to the front matter shape."""
    return {
        "monthly_avg_income": snapshot.monthly_avg_income,
        "monthly_avg_expense": snapshot.monthly_avg_expense,
        "savings_rate_3mo": snapshot.savings_rate_3mo,
        "residual_savings_rate_3mo": snapshot.residual_savings_rate_3mo,
        "monthly_avg_consumption_expense": snapshot.monthly_avg_consumption_expense,
        "consumption_savings_rate_3mo": snapshot.consumption_savings_rate_3mo,
        "structural_savings_monthly_avg": snapshot.structural_savings_monthly_avg,
        "structural_savings_transaction_monthly_avg": (
            snapshot.structural_savings_transaction_monthly_avg
        ),
        "recurring_savings_monthly_amount": snapshot.recurring_savings_monthly_amount,
        "structural_savings_sources": snapshot.structural_savings_sources,
        "top_categories": (
            [{"name": item.name, "amount": item.amount} for item in snapshot.top_categories]
            if snapshot.top_categories is not None
            else None
        ),
        "active_filters": snapshot.active_filters,
        "active_goals": snapshot.active_goals,
    }


def _load_template_body(template_name: str) -> str:
    """Load a packaged journal template body."""
    from importlib.resources import files

    safe_name = template_name.strip().lower()
    if safe_name not in {"diagnosis", "planning", "retrospective"}:
        raise typer.BadParameter(f"Unknown template: {template_name}")
    return (
        files("finjuice.templates.journal").joinpath(f"{safe_name}.md").read_text(encoding="utf-8")
    )


def _resolve_topic(topic: Optional[str], now: datetime) -> str:
    """Return a safe topic slug for filename/front matter use."""
    if topic is None or not sys.stdin.isatty():
        if topic is None:
            return f"session-{now.strftime('%Y%m%d-%H%M%S')}"
        return _normalize_slug(topic, now)
    return _normalize_slug(topic, now)


def _normalize_slug(raw_topic: str, now: datetime) -> str:
    """Normalize user input into a safe filename slug."""
    sanitized = "".join(ch if ch not in _CONTROL_CHARACTERS else " " for ch in raw_topic)
    sanitized = sanitized.replace("/", "-").replace("\\", "-")
    sanitized = sanitized.strip().strip(".").lower()
    sanitized = sanitized.replace(".", "-")
    normalized_chars: list[str] = []
    previous_was_dash = False

    for ch in sanitized:
        if ch.isalnum() or ch in {"-", "_"}:
            normalized_chars.append(ch)
            previous_was_dash = False
            continue
        if ch.isspace() or ch in {":", ","}:
            if not previous_was_dash:
                normalized_chars.append("-")
                previous_was_dash = True
            continue

    slug = "".join(normalized_chars).strip("-_")
    while "--" in slug:
        slug = slug.replace("--", "-")
    slug = slug[:MAX_TOPIC_LENGTH].rstrip("-_")
    if not slug:
        return f"session-{now.strftime('%Y%m%d-%H%M%S')}"
    return slug


def _resolve_new_entry_path(journal_dir: Path, topic: str, now: datetime) -> Path:
    """Return a collision-safe journal path for today/topic."""
    date_prefix = now.strftime("%Y-%m-%d")
    base_name = f"{date_prefix}_{topic}"
    candidate = journal_dir / f"{base_name}.md"
    counter = 2

    while candidate.exists():
        candidate = journal_dir / f"{base_name}_{counter}.md"
        counter += 1

    return candidate


def _ensure_journal_dir(path: Path) -> Path:
    """Create the journal directory if needed and reject symlink targets."""
    path.mkdir(parents=True, exist_ok=True)
    if not path.is_dir() or path.is_symlink():
        raise typer.BadParameter(f"Journal directory must be a real directory: {path}")
    return path


def _select_entry(entries: list[JournalEntry], query: Optional[str]) -> Optional[JournalEntry]:
    """Pick the newest entry or the newest matching entry."""
    if query is None:
        return entries[0]

    query_text = query.strip().lower()
    if _looks_like_iso_date(query_text):
        matches = [entry for entry in entries if entry.filename.startswith(f"{query_text}_")]
        return matches[0] if matches else None

    matches = [entry for entry in entries if query_text in entry.filename.lower()]
    return matches[0] if matches else None


def _looks_like_iso_date(value: str) -> bool:
    """Return True for exact YYYY-MM-DD strings."""
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return False
    return True


def _open_in_editor(path: Path) -> None:
    """Launch $EDITOR with the selected path when configured."""
    editor = os.getenv("EDITOR", "")
    if not editor.strip():
        warning("$EDITOR is not set; printing the path instead.")
        return

    try:
        command = shlex.split(editor)
        if not command:
            warning("$EDITOR is empty; printing the path instead.")
            return
        subprocess.run([*command, str(path)], check=False)
    except FileNotFoundError:
        warning(f"Editor not found: {editor}")


def _maybe_prompt_for_gitignore(journal_dir: Path) -> None:
    """Offer to add a local ignore rule for underscore-prefixed journal dirs."""
    git_root = _find_git_root(journal_dir)
    if git_root is None:
        return

    gitignore_path = git_root / ".gitignore"
    if _gitignore_covers_journal_dir(gitignore_path, journal_dir.name):
        return

    prompt = f"Add '_*/' to {gitignore_path} so private journals stay out of git?"
    if not typer.confirm(prompt, default=True):
        return

    existing = gitignore_path.read_text(encoding="utf-8") if gitignore_path.exists() else ""
    prefix = "" if not existing or existing.endswith("\n") else "\n"
    gitignore_path.write_text(f"{existing}{prefix}_*/\n", encoding="utf-8")


def _find_git_root(start: Path) -> Optional[Path]:
    """Return the nearest git root for the journal directory."""
    current = start.resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def _gitignore_covers_journal_dir(gitignore_path: Path, journal_dir_name: str) -> bool:
    """Detect `_*/` or explicit journal dir ignore entries."""
    if not gitignore_path.exists():
        return False

    expected_names = {
        "_*/",
        "/_*/",
        "**/_*/",
        f"{journal_dir_name}/",
        f"/{journal_dir_name}/",
        f"**/{journal_dir_name}/",
    }

    for raw_line in gitignore_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("!"):
            continue
        if line in expected_names:
            return True

    return False


def _now() -> datetime:
    """Return the current local time with timezone."""
    return datetime.now().astimezone()
