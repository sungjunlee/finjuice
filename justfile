# justfile for finjuice
# Documentation and development automation
# Usage: just <recipe>

# Show available recipes
default:
    @just --list

# Documentation targets

# Generate schema reference from templates/schema.yaml
docs-schema:
    @echo "📄 Generating schema documentation from templates/schema.yaml..."
    @uv run python scripts/generate_schema_docs.py

# Generate CLI reference from finjuice --help
docs-cli:
    @echo "📄 Generating CLI documentation from finjuice --help..."
    @uv run python scripts/generate_cli_docs.py

# Generate machine-readable CLI tool schema
docs-tools:
    @echo "📄 Generating CLI tool schema from Typer app..."
    @uv run python scripts/generate_tool_schema.py

# Generate machine-readable command output JSON Schemas
docs-output-schemas:
    @echo "📄 Generating command output JSON Schemas and markdown reference..."
    @python -m tools.generate_schemas
    @python -m tools.render_schema_md > docs/reference/json-schemas.md

# Generate all documentation
docs: docs-schema docs-cli docs-tools docs-output-schemas
    @echo "✅ All documentation generated successfully"

# Development targets

# Run tests with pytest
test:
    @echo "🧪 Running tests..."
    @uv run pytest

# Run ruff linting
lint:
    @echo "🔍 Running ruff linting..."
    @uv run ruff check .
    @just complexity

# Run Ruff-backed complexity ratchet
complexity:
    @echo "🧮 Running complexity ratchet..."
    @if [ -x .venv/bin/python ] && [ -x .venv/bin/ruff ]; then \
        .venv/bin/python scripts/check_complexity_ratchet.py --ruff .venv/bin/ruff; \
    else \
        uv run python scripts/check_complexity_ratchet.py; \
    fi

# Re-point complexity + Bandit baseline paths after a refactor moved code
rebase-baselines:
    #!/usr/bin/env bash
    set -uo pipefail
    echo "🔁 Rebasing baseline paths after a refactor..."
    status=0
    uv run python scripts/check_complexity_ratchet.py --rebase-paths || status=1
    uv run python scripts/check_security_baselines.py --rebase-paths || status=1
    exit $status

# Run mypy type checking
typecheck:
    @echo "🔎 Running mypy type checking..."
    @uv run mypy src/

# Check logger calls for financial PII
pii-log-check:
    @echo "🔐 Checking logger calls for financial PII..."
    @uv run python scripts/check_pii_logging.py

# Build package artifacts and verify bundled resources
package-check:
    @echo "📦 Checking package contents..."
    @python3 scripts/check_package_contents.py

# Run all quality checks (test + lint + typecheck + PII logging)
qa: test lint typecheck pii-log-check
    @echo "✅ All quality checks passed"

# Release targets

# Bump version across all source locations (dry-run first with just bump-version-check)
bump-version VERSION:
    @echo "🔢 Bumping version to {{VERSION}}..."
    @uv run python scripts/bump_version.py {{VERSION}}

# Preview version bump without modifying any files
bump-version-check VERSION:
    @echo "🔍 Previewing version bump to {{VERSION}}..."
    @uv run python scripts/bump_version.py --dry-run {{VERSION}}
