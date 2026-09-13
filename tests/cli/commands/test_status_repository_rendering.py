"""Canonical status rendering never presents live CSV configuration as authority."""

from dataclasses import replace
from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console

from finjuice.pipeline.cli.commands.status import rendering
from finjuice.pipeline.cli.commands.status.compute import StatusFacts
from finjuice.pipeline.cli.commands.status.detector import diagnose_status
from finjuice.pipeline.cli.commands.status.rendering import build_status_result
from finjuice.pipeline.cli.commands.status.rendering_table import _build_status_table


def _facts(tmp_path: Path, rules_status: str = "parsed") -> StatusFacts:
    return StatusFacts(
        data_dir=tmp_path,
        data_dir_resolved=str(tmp_path),
        data_dir_source="cli",
        total_rows=0,
        min_date=None,
        max_date=None,
        partition_count=0,
        schema_summary=None,
        last_import_date=None,
        last_import_file=None,
        rules_path=tmp_path / "rules.yaml",
        rules_exists=False,
        rules_modified=None,
        tagged_count=0,
        untagged_count=0,
        tagging_rate=0,
        suggestable_transaction_count=0,
        suggestable_tagged_count=0,
        suggestable_untagged_count=0,
        suggestable_tagging_rate=0,
        transfer_candidate_count=0,
        transfer_excluded_count=0,
        transfer_excluded_untagged_count=0,
        unconfirmed_transfer_candidate_count=0,
        untagged_merchants=[],
        untagged_merchants_total=0,
        filters_applied=0,
        detailed_requested=False,
        top_n=5,
        repository={
            "metadata": {
                "authority": "repository",
                "dataset_generation": "generation",
                "dataset_revision": 7,
                "calculation_policy": "legacy_status.v1",
            },
            "schema_version": 5,
            "rules_head": {
                "revision_id": "rules-revision",
                "parsed_status": rules_status,
                "updated_at": None,
            },
            "goals_head": {"revision_id": None, "parsed_status": "missing", "updated_at": None},
            "source_counts": {
                "total_rows": 0,
                "primary_scope_rows": 0,
                "out_of_scope_rows": 0,
                "unknown_month_rows": 0,
            },
            "last_import": {
                "imported_at": "2026-09-13",
                "file_id": None,
                "occurrence_id": "native-occurrence",
                "origin": "native_import",
            },
            "source_occurrence_counts": {"native_import": 1, "migration_capture": 0, "other": 0},
        },
    )


@pytest.mark.parametrize("rules_status", ["missing", "invalid", "opaque"])
def test_repository_configuration_diagnosis_does_not_suggest_init(tmp_path, rules_status):
    facts = _facts(tmp_path, rules_status)
    result = build_status_result(facts, diagnose_status(facts))
    assert result.payload["health"] == {
        "status": "critical",
        "reasons": [f"{rules_status}_rules_head"],
    }
    assert result.payload["rules_file"]["path"] is None
    assert result.payload["rules_file"]["authority"] == "repository"
    assert "migration" not in result.payload["schema"]
    assert all(step["command"] != "finjuice init" for step in result.payload["next_steps"])


def test_repository_table_distinguishes_occurrence_and_sqlite_schema(tmp_path):
    facts = _facts(tmp_path)
    payload = build_status_result(facts, diagnose_status(facts)).payload
    stream = StringIO()
    Console(file=stream, width=180, color_system=None).print(_build_status_table(payload))
    text = stream.getvalue()
    assert "SQLite active v5" in text
    assert "Canonical rules" in text
    assert "occurrence_id: native-occurrence" in text
    assert "file_id:" not in text
    assert "finjuice init" not in text
    assert "Repository revision" in text


def test_repository_metadata_is_emitted(tmp_path, monkeypatch):
    facts = _facts(tmp_path)
    captured = {}
    monkeypatch.setattr(rendering, "emit", lambda payload, **kwargs: captured.update(kwargs))
    rendering.emit_status_result(
        build_status_result(facts, diagnose_status(facts)), json_output=True
    )
    assert captured["meta_extras"]["dataset_revision"] == 7
    assert captured["meta_extras"]["authority"] == "repository"


def test_invalid_goals_warn_only_for_detailed_status(tmp_path):
    facts = _facts(tmp_path)
    facts.repository["goals_head"]["parsed_status"] = "invalid"
    assert diagnose_status(facts).health["status"] == "ok"
    detailed = diagnose_status(replace(facts, detailed_requested=True))
    assert detailed.health == {"status": "warning", "reasons": ["invalid_goals_head"]}


def test_repository_warning_without_detailed_stats_is_visible(tmp_path, monkeypatch):
    facts = replace(
        _facts(tmp_path),
        detailed_requested=True,
        detailed_stats_warning="Canonical detailed insight unavailable.",
    )
    result = build_status_result(facts, diagnose_status(facts))
    stream = StringIO()
    monkeypatch.setattr(rendering, "console", Console(file=stream, width=180, color_system=None))
    rendering.render_status(result)
    assert result.payload["detailed_stats_warning"] == facts.detailed_stats_warning
    assert facts.detailed_stats_warning in stream.getvalue()
