"""Repository explain searches and simulations pinned to one read snapshot."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import polars as pl
import typer

from finjuice.pipeline.analytics.duckdb_layer_helpers import (
    DUCKDB_INSTALL_HINT,
    detect_analytics_dependencies,
)
from finjuice.pipeline.cli.output import ErrorCode, ExitCode, emit, emit_error, warning
from finjuice.pipeline.cli.utils import get_activation_evidence_provider
from finjuice.pipeline.config import Config
from finjuice.pipeline.storage.read_facade import (
    read_transaction_snapshot,
    snapshot_metadata,
    transaction_frame,
)
from finjuice.pipeline.storage.sqlite.transaction_reads import TransactionReadSnapshot
from finjuice.pipeline.tagging.matcher import _get_rule_match, apply_tagging_rules_v3
from finjuice.pipeline.tagging.models import TagRule
from finjuice.pipeline.tagging.rules_yaml_io import load_rules_bytes

_STORED_FIELDS = (
    "category_manual",
    "category_rule",
    "category_final",
    "tags_rule",
    "tags_ai",
    "tags_manual",
    "tags_final",
    "notes_manual",
)


class _ExplainDateError(ValueError):
    """Public date-format validation failure with a fixed non-sensitive message."""


class _ExplainDependencyError(ImportError):
    """Optional DuckDB dependency is unavailable."""


@dataclass(frozen=True)
class ExplainRequest:
    """Selection options shared by repository search and rendering."""

    query: str
    date: str | None
    pick: int | None
    json_output: bool


def repository_explain(
    ctx: typer.Context,
    config: Config,
    request: ExplainRequest,
) -> bool:
    """Handle repository authority and return False only for a legacy data root."""
    try:
        snapshot = read_transaction_snapshot(config.data_dir, get_activation_evidence_provider(ctx))
        if snapshot is None:
            return False
        rules = _rules(snapshot)
        matches = _search(snapshot, request.query, request.date) if rules else pl.DataFrame()
        _emit_snapshot_result(snapshot, rules, matches, request)
    except _ExplainDateError:
        emit_error(
            "Invalid date format. Use YYYY-MM-DD.",
            error_code=ErrorCode.VALIDATION_FAILED,
            exit_code=ExitCode.VALIDATION_ERROR,
            json_output=request.json_output,
            command="explain",
        )
    except _ExplainDependencyError:
        emit_error(
            DUCKDB_INSTALL_HINT,
            error_code=ErrorCode.QUERY_ERROR,
            suggestion="finjuice doctor",
            json_output=request.json_output,
            command="explain",
        )
    except Exception as exc:
        # Backend/YAML errors can include source values. Do not echo their text.
        if isinstance(exc, (typer.Exit, typer.Abort)):
            raise
        emit_error(
            "Repository explanation could not read validated data and canonical rules.",
            error_code=ErrorCode.QUERY_ERROR,
            json_output=request.json_output,
            command="explain",
        )
        return True
    return True


def _rules(snapshot: TransactionReadSnapshot) -> list[TagRule]:
    if snapshot.rules_content is None:
        return []
    if snapshot.rules_parsed_status != "parsed":
        raise ValueError("Canonical rules head is not parsed.")
    rules = load_rules_bytes(snapshot.rules_content)
    # Reject invalid regex before the matcher can log private rule contents.
    for rule in rules:
        if not rule.enabled:
            continue
        for condition in rule.conditions:
            if condition.op == "regex":
                re.compile(condition.value)
    return rules


def _search(snapshot: TransactionReadSnapshot, query: str, date: str | None) -> pl.DataFrame:
    available, duckdb, _ = detect_analytics_dependencies()
    if not available:
        raise _ExplainDependencyError(DUCKDB_INSTALL_HINT)
    where = "(merchant_raw ILIKE ? OR memo_raw ILIKE ?)"
    parameters = [f"%{query}%", f"%{query}%"]
    if date:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            raise _ExplainDateError("Invalid date format. Use YYYY-MM-DD.")
        where += " AND date = ?"
        parameters.append(date)
    with duckdb.connect(":memory:") as connection:
        connection.register("rows", transaction_frame(snapshot).to_arrow())
        result: pl.DataFrame = connection.execute(
            "SELECT row_hash, date, merchant_raw, memo_raw, amount, major_raw, minor_raw, "
            "category_final, transaction_id FROM rows WHERE "
            + where
            + " ORDER BY date DESC, transaction_id LIMIT 10",
            parameters,
        ).pl()
        return result


def _emit_snapshot_result(
    snapshot: TransactionReadSnapshot,
    rules: list[TagRule],
    matches: pl.DataFrame,
    request: ExplainRequest,
) -> None:
    from finjuice.pipeline.cli.commands.explain import _selected_row_or_error, render_explain

    query, date, pick, json_output = (
        request.query,
        request.date,
        request.pick,
        request.json_output,
    )
    metadata = {
        **snapshot_metadata(snapshot),
        "calculation_policy": "current_rules_simulation.v1",
    }
    base: dict[str, Any] = {"query": query, "date_filter": date}
    if not rules:
        emit(
            {**base, "transaction": None, "classification": None, "rule_trace": []},
            json_output,
            lambda _: warning("No rules found. Nothing to explain."),
            command="explain",
            meta_extras=metadata,
        )
        return
    if matches.is_empty():
        emit(
            {**base, "match_count": 0, "matches": []},
            json_output,
            lambda _: warning("No matching transactions found."),
            command="explain",
            meta_extras=metadata,
        )
        return
    selected = _selected_row_or_error(matches, json_output, pick)
    if selected is None:
        return
    target, index = selected
    raw = next(row for row in snapshot.rows if row["transaction_id"] == target["transaction_id"])
    matcher_row = dict(raw)
    for name in ("tags_rule", "tags_ai", "tags_manual", "tags_final"):
        matcher_row[name] = json.loads(raw[name])
    stored = {name: matcher_row[name] for name in _STORED_FIELDS}
    stored["tags_manual"] = [
        tag
        for tag in stored["tags_manual"]
        if not tag.strip().startswith("__finjuice_category_override__:")
    ]
    emit(
        {
            **base,
            "match_count": len(matches),
            "selected_index": index,
            "candidates": [
                {"index": i, **row}
                for i, row in enumerate(matches.head(5).iter_rows(named=True), 1)
            ]
            if len(matches) > 1
            else [],
            "transaction": target,
            "classification_basis": "current_rules_simulation",
            "stored_classification": stored,
            **_simulation(matcher_row, rules),
        },
        json_output,
        render_explain,
        command="explain",
        meta_extras=metadata,
    )


def _simulation(row: dict[str, Any], rules: list[TagRule]) -> dict[str, Any]:
    result = apply_tagging_rules_v3(row, rules)
    category = (
        result.category_rule
        or row.get("category_final")
        or row.get("minor_raw")
        or row.get("major_raw")
        or "미분류"
    )
    return {
        "classification": {
            "matched_rules": result.matching_rules,
            "tags": result.tags,
            "category": category,
            "category_rule": result.category_rule or None,
        },
        "rule_trace": [
            {
                "priority": rule.priority,
                "rule_name": rule.name,
                "matched_field": rule.match,
                "tags_added": rule.tags,
                "category_set": rule.category or None,
            }
            for rule in rules
            if rule.enabled and _get_rule_match(row, rule)
        ],
    }
