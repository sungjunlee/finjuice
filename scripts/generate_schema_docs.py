#!/usr/bin/env python3
"""Generate schema documentation from schema.yaml

This script reads templates/schema.yaml and generates a comprehensive
Markdown reference document at docs/reference/schema.md.

Usage:
    python scripts/generate_schema_docs.py
    just docs-schema  # Recommended
"""

from pathlib import Path

import yaml


def _format_breaking_changes(compatibility: dict) -> str:
    """Render breaking-change sections for one compatibility entry."""
    md = ""
    for key in compatibility:
        if not key.startswith("breaking_changes_from_"):
            continue
        from_version = key.removeprefix("breaking_changes_from_")
        md += f"\n**Breaking Changes from {from_version}**:\n\n"
        for change in compatibility[key]:
            md += f"- {change}\n"
    return md


def _format_compatibility_entry(version_key: str, compatibility: dict) -> str:
    """Render one schema compatibility entry as Markdown."""
    md = f"### {version_key}\n\n"
    if "compatibility_status" in compatibility:
        md += f"- **Compatibility Status**: `{compatibility['compatibility_status']}`\n"
    if "migration_status" in compatibility:
        md += f"- **Migration Status**: {compatibility['migration_status']}\n"
    for key, label in (("can_read", "Can Read"), ("can_write", "Can Write")):
        if key in compatibility:
            versions = ", ".join(f"v{version}" for version in compatibility[key])
            md += f"- **{label}**: {versions}\n"
    if "migration_required" in compatibility:
        required = "Yes" if compatibility["migration_required"] else "No"
        md += f"- **Migration Required**: {required}\n"
    for key, label in (
        ("runtime_migration", "Runtime Migration"),
        ("manual_migration", "Manual Migration"),
        ("note", "Note"),
    ):
        if key in compatibility:
            md += f"- **{label}**: {compatibility[key]}\n"
    md += _format_breaking_changes(compatibility)
    return md + "\n"


def generate_schema_docs():
    """Generate schema reference documentation from schema.yaml"""

    # Paths
    schema_path = Path("templates/schema.yaml")
    output_path = Path("docs/reference/schema.md")

    if not schema_path.exists():
        print(f"❌ Error: {schema_path} not found")
        return

    # Read schema
    with open(schema_path, encoding="utf-8") as f:
        schema = yaml.safe_load(f)

    # Extract current version info
    current_ver = f"v{schema['current_version']}"
    current_schema = schema["schemas"][current_ver]

    # Build Markdown content
    md = f"""# Schema Reference

> **Auto-generated from** [`templates/schema.yaml`](../../templates/schema.yaml)
> **Do not edit manually** - Run `just docs-schema` to regenerate

---

## Current Schema: {current_ver}

{current_schema["description"]}

**Issue**: {current_schema.get("issue", "N/A")}
**Introduced**: {current_schema.get("introduced", "N/A")}

### Performance Metrics

- **Total Columns**: {current_schema["metrics"]["csv_columns"]}
"""

    # Dynamically add metrics based on schema version
    metrics = current_schema["metrics"]
    if "token_efficiency" in metrics:
        md += f"- **Token Efficiency**: {metrics['token_efficiency']}\n"
    if "char_savings_per_row" in metrics:
        md += f"- **Savings per Row**: {metrics['char_savings_per_row']} chars\n"
    if "token_savings_estimate" in metrics:
        md += f"- **Estimated Token Savings**: {metrics['token_savings_estimate']}\n"
    if "new_columns" in metrics:
        md += f"- **New Columns**: {', '.join(f'`{c}`' for c in metrics['new_columns'])}\n"
    if "category_priority_chain" in metrics:
        md += f"- **Category Priority**: `{metrics['category_priority_chain']}`\n"
    if "aggregation_accuracy" in metrics:
        md += f"- **Aggregation Accuracy**: {metrics['aggregation_accuracy']}\n"
    if "note" in metrics:
        md += f"- **Note**: {metrics['note']}\n"

    md += f"""

### Partition Configuration

- **Location Pattern**: `{current_schema["partition_schema"]["location_pattern"]}`
- **Format**: {current_schema["partition_schema"]["format"]}
- **Encoding**: {current_schema["partition_schema"]["encoding"]}
- **Sort By**: `{current_schema["partition_schema"]["sort_by"]}`

---

## Column Definitions ({current_schema["metrics"]["csv_columns"]} columns)

| Column | Type | Nullable | Description | Example |
|--------|------|----------|-------------|---------|
"""

    # Add column definitions
    for col in current_schema["partition_schema"]["columns"]:
        nullable = "✓" if col.get("nullable", False) else "✗"
        description = col.get("description", "").replace("\n", " ")
        example = col.get("example", "-")

        md += f"| `{col['name']}` | {col['type']} | {nullable} | {description} | `{example}` |\n"

    # Add column details sections
    md += "\n\n### Column Details\n\n"

    # Group columns by section (based on comments in schema.yaml)
    for col in current_schema["partition_schema"]["columns"]:
        # Column name
        md += f"#### `{col['name']}`\n\n"
        md += f"**Type**: `{col['type']}`"

        if "length" in col:
            md += f" (length: {col['length']})"
        if "enum" in col:
            md += f" (enum: {', '.join(str(v) for v in col['enum'])})"
        if "range" in col:
            md += f" (range: {col['range']})"

        md += f"\n**Nullable**: {'Yes' if col.get('nullable', False) else 'No'}\n\n"

        if "description" in col:
            md += f"{col['description']}\n\n"

        if "example" in col:
            md += f"**Example**: `{col['example']}`\n\n"

        if "pattern" in col:
            md += f"**Pattern**: `{col['pattern']}`\n\n"

        if "note" in col:
            md += f"**Note**: {col['note']}\n\n"

        if "convention" in col:
            md += f"**Convention**: {col['convention']}\n\n"

        md += "---\n\n"

    # Add migration history
    md += "## Migration History\n\n"

    for migration in schema.get("migrations", []):
        md += f"### {migration['title']} (v{migration['version']})\n\n"
        md += f"**Issue**: {migration.get('issue', 'N/A')}\n"
        md += f"**Date**: {migration.get('executed_at', 'N/A')}\n"
        md += f"**Author**: {migration.get('author', 'N/A')}\n\n"
        md += f"{migration['description']}\n\n"

        if "changes" in migration:
            md += "**Changes**:\n\n"
            for change in migration["changes"]:
                field = change.get("field", "N/A")
                change_type = change["type"].title()
                change_desc = change["change"]
                md += f"- **{change_type}** `{field}`: {change_desc}\n"
                if "impact" in change:
                    md += f"  - Impact: {change['impact']}\n"
            md += "\n"

        if "results" in migration:
            md += "**Results**:\n\n"
            for key, value in migration["results"].items():
                md += f"- **{key.replace('_', ' ').title()}**: {value}\n"
            md += "\n"

    # Add schema compatibility matrix
    if "compatibility" in schema:
        md += "## Schema Compatibility\n\n"

        for version_key, compatibility in schema["compatibility"].items():
            md += _format_compatibility_entry(version_key, compatibility)

    # Add validation rules
    md += "## Validation Rules\n\n"

    for rule in schema.get("validation_rules", []):
        severity_emoji = "🔴" if rule["severity"] == "error" else "⚠️"
        md += f"{severity_emoji} **{rule['rule']}**\n\n"

        if "field" in rule:
            md += f"- Field: `{rule['field']}`\n"
        elif "fields" in rule:
            md += f"- Fields: {', '.join(f'`{f}`' for f in rule['fields'])}\n"

        if "regex" in rule:
            md += f"- Pattern: `{rule['regex']}`\n"
        elif "enum" in rule:
            md += f"- Allowed values: {', '.join(f'`{v}`' for v in rule['enum'])}\n"
        elif "range" in rule:
            md += f"- Range: {rule['range']}\n"

        md += f"- Severity: `{rule['severity']}`\n"

        if "note" in rule:
            md += f"- Note: {rule['note']}\n"

        md += "\n"

    # Add footer
    md += """---

## See Also

- [templates/schema.yaml](../../templates/schema.yaml) - Source of truth
- [rules-conditions.md](rules-conditions.md) - Conditional rule engine reference
- [CLAUDE.md](../../CLAUDE.md) - Project guide
- [Data Repository Setup](../setup/data-repository.md) - User data configuration

**Note**: This file is auto-generated. Do not edit manually. Run `make docs-schema` to regenerate.
"""

    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Write output
    output_path.write_text(md, encoding="utf-8")

    print(f"✅ Generated {output_path}")
    print(f"📊 Schema version: {current_ver}")
    print(f"📋 Columns: {current_schema['metrics']['csv_columns']}")
    print(f"🗂️ Migrations: {len(schema.get('migrations', []))}")


if __name__ == "__main__":
    generate_schema_docs()
