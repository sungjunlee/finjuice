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


def test_rules_yaml_io_keeps_public_yaml_api() -> None:
    """Public YAML IO names stay on rules_yaml_io after the filter-helper split."""
    yaml_io = importlib.import_module("finjuice.pipeline.tagging.rules_yaml_io")
    filters = importlib.import_module("finjuice.pipeline.tagging.rules_yaml_filters")

    for name in (
        "load_rules",
        "load_rules_collecting",
        "load_report_filters",
        "save_rules",
        "append_rule",
        "summarize_rule_notes",
        "save_rule_dicts_roundtrip",
        "add_rule_roundtrip",
        "update_rule_roundtrip",
        "remove_rule_roundtrip",
    ):
        assert callable(getattr(yaml_io, name))

    assert yaml_io._parse_report_filters is filters._parse_report_filters


def test_csv_partition_polars_shim_exports_only_schema_contract() -> None:
    """The old storage umbrella path should only keep the tiny schema contract."""
    storage = importlib.import_module("finjuice.pipeline.storage.csv_partition_polars")

    assert storage.__all__ == [
        "CSV_COLUMNS",
        "POLARS_SCHEMA",
    ]


def test_goals_validate_reexports_budget_helpers() -> None:
    """Monthly-budget section validators stay on validate after the helper split."""
    validate = importlib.import_module("finjuice.pipeline.goals_validators.validate")
    budget = importlib.import_module("finjuice.pipeline.goals_validators.budget")

    assert validate._validate_monthly_budget is budget._validate_monthly_budget
    assert validate._validate_monthly_budget_mapping is budget._validate_monthly_budget_mapping
    assert validate._validate_budget_total is budget._validate_budget_total
    assert validate._validate_budget_categories is budget._validate_budget_categories
    assert validate._validate_budget_category_values is budget._validate_budget_category_values
    assert validate._validate_budget_updated is budget._validate_budget_updated
    assert validate._validate_budget_notes is budget._validate_budget_notes
    assert callable(validate.validate_goals_payload)
    assert callable(validate.validate_month_literal)


def test_csv_transactions_reexports_public_crud_api() -> None:
    """Transaction CRUD stays on csv_transactions after the helper split."""
    transactions = importlib.import_module("finjuice.pipeline.storage.csv_transactions")
    helpers = importlib.import_module("finjuice.pipeline.storage.csv_transactions_helpers")

    assert transactions.__all__ == [
        "append_transactions",
        "find_transaction_by_hash",
        "get_all_transactions",
        "read_month",
        "read_range",
        "upsert_transaction",
        "write_month",
    ]
    assert transactions._add_read_defaults is helpers._add_read_defaults
    assert transactions._ensure_schema_columns is helpers._ensure_schema_columns
    assert transactions._get_transaction_read_columns is helpers._get_transaction_read_columns


def test_schema_registry_reexports_load_cache_helpers() -> None:
    """Load/cache helpers stay importable from schema_registry after the split."""
    registry = importlib.import_module("finjuice.pipeline.storage.schema_registry")
    helpers = importlib.import_module("finjuice.pipeline.storage.schema_registry_helpers")

    assert registry.__all__ == [
        "PartitionSchemaSummary",
        "SchemaCompatibilityState",
        "SchemaDetection",
        "clear_cache",
        "detect_schema_version",
        "get_column_definition",
        "get_compatible_read_versions",
        "get_current_schema",
        "get_schema_migration_guidance",
        "get_schema_version",
        "list_migrations",
        "load_schema_registry",
        "summarize_partition_schema_versions",
        "validate_column_names",
    ]
    assert registry.clear_cache is helpers.clear_cache
    assert registry.load_schema_registry is helpers.load_schema_registry
    assert registry._get_default_metadata_dir is helpers._get_default_metadata_dir
    assert registry._load_registry_for_detection is helpers._load_registry_for_detection


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


def test_reports_polars_reexports_csv_io_helpers() -> None:
    """CSV load/write helpers stay importable from reports_polars after the split."""
    reports_polars = importlib.import_module("finjuice.pipeline.export.reports_polars")
    helpers = importlib.import_module("finjuice.pipeline.export.reports_polars_helpers")

    assert reports_polars.UTF8_BOM is helpers.UTF8_BOM
    assert reports_polars._write_csv_with_bom is helpers._write_csv_with_bom
    assert reports_polars._load_report_source_df is helpers._load_report_source_df
    assert callable(reports_polars.export_monthly_spend_polars)
    assert callable(reports_polars.export_by_tag_polars)
    assert callable(reports_polars.export_by_category_polars)
    assert callable(reports_polars.export_by_account_polars)
    assert callable(reports_polars.export_transfers_polars)
