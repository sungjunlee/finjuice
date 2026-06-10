"""Regression coverage for post-release re-export shim cleanup."""

from __future__ import annotations

import importlib


def test_tagging_rules_shim_exports_only_documented_public_api() -> None:
    """The rules shim should not advertise split-module implementation details."""
    rules = importlib.import_module("finjuice.pipeline.tagging.rules")

    assert rules.__all__ == [
        "TagRule",
        "ReportFilters",
        "FiltersValidationError",
        "apply_tagging_rules_v3",
        "load_rules",
        "load_report_filters",
        "summarize_rule_notes",
    ]


def test_csv_partition_polars_shim_exports_only_schema_contract() -> None:
    """The old storage umbrella path should only keep the tiny schema contract."""
    storage = importlib.import_module("finjuice.pipeline.storage.csv_partition_polars")

    assert storage.__all__ == [
        "CSV_COLUMNS",
        "POLARS_SCHEMA",
    ]


def test_init_command_shim_does_not_keep_migration_patch_dependencies() -> None:
    """Migration tests should patch migrate_cmd, not the init command shim."""
    init_shim = importlib.import_module("finjuice.pipeline.cli.commands.init")

    assert "shutil" not in vars(init_shim)
    assert "typer" not in vars(init_shim)


def test_checkup_entrypoint_does_not_export_private_rendering_helpers() -> None:
    """Private rendering helpers belong to the rendering module, not __all__."""
    checkup = importlib.import_module("finjuice.pipeline.cli.commands.checkup")

    assert "_compact_checkup" not in checkup.__all__
    assert "_serialize_checkup_payload" not in checkup.__all__
