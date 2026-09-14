"""Caller-owned query and scoring seams preserve suggestion behavior."""

from copy import deepcopy

import duckdb
import polars as pl

from finjuice.pipeline.tagging.models import TagRule
from finjuice.pipeline.tagging.suggestion_existing_rules import existing_rule_context
from finjuice.pipeline.tagging.suggestion_queries import (
    coverage_stats_from_connection,
    merchant_context_from_connection,
)
from finjuice.pipeline.tagging.suggestion_scoring import score_merchant_contexts


def _row(merchant: str, **overrides: object) -> dict[str, object]:
    return {
        "merchant_raw": merchant,
        "amount": -100.0,
        "date": "2026-01-01",
        "time": "12:00:00",
        "major_raw": "expense",
        "minor_raw": "shop",
        "account": "card",
        "memo_raw": "sample",
        "category_rule": "",
        "tags_list": [],
        "is_transfer": 0,
        "transfer_group_id": "",
        "file_id": "legacy",
        **overrides,
    }


def _register(conn, rows: list[dict[str, object]]) -> None:
    frame = pl.DataFrame(rows, schema_overrides={"tags_list": pl.List(pl.String)})
    conn.register("transactions", frame.to_arrow())


def test_connection_helpers_preserve_scope_alias_transfer_and_tag_semantics() -> None:
    rows = [
        _row("plain"),
        _row("confirmed", is_transfer=1, transfer_group_id="pair"),
        _row("flag-only", is_transfer=1),
        _row("tagged", tags_list=["tag"]),
        _row("native", file_id=None),
        _row("blank-tag", tags_list=[""]),
    ]
    with duckdb.connect(":memory:") as conn:
        _register(conn, rows)
        stats = coverage_stats_from_connection(conn)
        assert stats["total_count"] == 6
        assert stats["untagged_count"] == 4
        assert stats["suggestable_untagged_count"] == 3
        assert stats["transfer_excluded_untagged_count"] == 1
        assert coverage_stats_from_connection(conn, "legacy")["total_count"] == 5
        assert coverage_stats_from_connection(conn, "' OR 1=1 --")["total_count"] == 0
        contexts, tagged = merchant_context_from_connection(conn, 10, 1)
        assert {item["merchant"] for item in contexts} == {"plain", "flag-only", "native"}
        assert tagged == []  # Existing tagged hint threshold is at least two rows.
        assert conn.execute("SELECT 1").fetchone() == (1,)
    assert contexts[0]["sample_memos"] == ["sample"]


def test_scoring_preserves_498_clusters_and_does_not_mutate_inputs() -> None:
    truncated = "롯데쇼핑(주) 프리"
    full = "롯데쇼핑(주) 프리미엄아울렛 의왕점"
    rows = [
        _row(merchant)
        for merchant in [
            truncated,
            truncated,
            full,
            full,
            full,
            "네이버페이",
            "네이버페이",
            "*****",
            "*****",
        ]
    ]
    with duckdb.connect(":memory:") as conn:
        _register(conn, rows)
        contexts, tagged = merchant_context_from_connection(conn)
    before = deepcopy((contexts, tagged))
    names = {"existing"}
    suggestions = score_merchant_contexts(contexts, tagged, set(), names)
    cluster = next(item for item in suggestions if item["merchant"] == full)
    assert cluster["transaction_count"] == 5
    assert cluster["name_variants"] == [truncated, full]
    assert cluster["merchant_cluster"]["reason"] == "truncated_store_prefix"
    for item in suggestions:
        if item["merchant"] in {"네이버페이", "*****"}:
            assert item["default_action"] == "skip_rule"
            assert item["auto_apply_eligible"] is False
    assert len(suggestions) == 3
    assert (contexts, tagged) == before and names == {"existing"}
    cluster["sample_memos"].append("changed")
    assert (contexts, tagged) == before
    assert (
        score_merchant_contexts(contexts, tagged, {truncated.lower()}, names)[0]["merchant"] != full
    )


def test_existing_rule_context_keeps_disabled_patterns_and_all_names() -> None:
    rules = [
        TagRule(name="duplicate", match=" Shop | [ | ", tags=["x"], enabled=False),
        TagRule(name="duplicate", match="shop", tags=["x"]),
        TagRule(name="condition-only", tags=["x"]),
    ]
    patterns, names = existing_rule_context(iter(rules))
    assert patterns == {"shop", "["}
    assert names == {"duplicate", "condition-only"}
    patterns.add("new")
    assert existing_rule_context(rules)[0] == {"shop", "["}
