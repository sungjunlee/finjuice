# Test Suite Documentation

This directory contains comprehensive tests for finjuice, ensuring data integrity, idempotency, and correctness across all modules.

## Test Organization

### Test Files

```
tests/
├── conftest.py                   # Shared fixtures for all tests
├── fixtures/                     # Test data files
│   └── sample_rules.yaml        # Sample tagging rules
├── test_cli.py                  # CLI command tests
├── test_config.py               # Configuration management tests
├── test_db_schema.py            # Database schema tests
├── test_export_edge_cases.py    # Export error handling
├── test_idempotency.py          # End-to-end idempotency tests
├── test_ingest_deduplication.py # Row hash and deduplication tests
├── test_ingest_pipeline.py      # XLSX ingestion tests
├── test_ingest_schemas.py       # Column mapping tests
├── test_master_export.py        # Master XLSX export tests
├── test_reports.py              # CSV report generation tests
├── test_tagging_pipeline.py     # Tagging pipeline tests
├── test_tagging_rules.py        # Rule matching tests
└── test_transfer_detection.py   # Transfer pairing tests
```

### Coverage Statistics

Coverage and test counts change frequently. Use the current pytest configuration
as the source of truth:

```bash
uv run pytest --cov-report=term-missing
```

## Running Tests

### All Tests

```bash
# Run all tests with coverage report
uv run pytest

# Run with detailed output
uv run pytest -v

# Run without coverage
uv run pytest --no-cov
```

### Specific Test Files

```bash
# Run single test file
uv run pytest tests/test_cli.py

# Run specific test function
uv run pytest tests/test_cli.py::test_cli_init_success

# Run specific test class
uv run pytest tests/test_export_edge_cases.py::TestConvertJsonToCsv
```

### By Marker

```bash
# Run only unit tests (fast)
uv run pytest -m unit

# Run integration tests
uv run pytest -m integration

# Run idempotency tests
uv run pytest -m idempotent

# Skip slow tests
uv run pytest -m "not slow"
```

### Coverage Reports

```bash
# Terminal report with missing lines
uv run pytest --cov-report=term-missing

# HTML report (opens in browser)
uv run pytest --cov-report=html
open htmlcov/index.html

# XML report (for CI/CD)
uv run pytest --cov-report=xml
```

### Debugging Failed Tests

```bash
# Stop at first failure
uv run pytest -x

# Show local variables on failure
uv run pytest -l

# Detailed traceback
uv run pytest --tb=long

# Drop into debugger on failure
uv run pytest --pdb
```

## Test Categories

### Unit Tests

Fast, isolated tests for individual functions and classes.

**Examples:**
- `test_calculate_row_hash_success()`
- `test_normalize_amount()`
- `test_convert_json_to_csv()`

**Marker:** `@pytest.mark.integration`

### Idempotency Tests

End-to-end tests verifying that re-running operations produces identical results.

**Key Tests:**
- Full pipeline idempotency (ingest → tag → detect → export)
- Incremental import (no duplicates)
- Tagging consistency (same rules → same tags)
- Transfer detection stability

**Marker:** `@pytest.mark.idempotent`

## Shared Fixtures

Located in `conftest.py`, these fixtures are available to all tests:

### Directory Fixtures

```python
temp_csv_base_dir  # Temporary CSV partition directory
temp_import_dir    # Temporary import directory
```

```python
temp_import_dir  # Temporary import directory
temp_export_dir  # Temporary export directory
temp_finance_dir # Temporary finance root directory
temp_data_dir    # Complete data directory structure (dict)
```

### File Fixtures

```python
sample_xlsx_file   # Sample XLSX with 3 transactions
sample_rules_file  # Path to sample rules.yaml
```

### Data Fixtures

```python
sample_transaction      # Single transaction dict
sample_transactions     # List of 4 transactions (with transfer pair)
sample_transfer_pair    # Tuple of (outgoing, incoming) transfers
test_config            # Test configuration dict
```

## Writing New Tests

### Test Structure (AAA Pattern)

```python
def test_feature_name():
    """Brief description of what this test verifies."""
    # Arrange: Set up test data and preconditions
    input_data = create_test_data()

    # Act: Execute the code under test
    result = function_to_test(input_data)

    # Assert: Verify the results
    assert result == expected_value
```

### Using Fixtures

```python
def test_with_csv_partition(temp_csv_base_dir, sample_transactions):
    """Test that uses shared fixtures."""
    # temp_csv_base_dir and sample_transactions are automatically provided
    write_sample_partition(temp_csv_base_dir, sample_transactions)

    result = read_partition_summary(temp_csv_base_dir)
    assert result == expected
```

### Parametrized Tests

```python
@pytest.mark.parametrize("input_value,expected", [
    (-5000, "지출"),
    (3000000, "수입"),
    (0, "other"),
])
def test_classify_transaction(input_value, expected):
    """Test transaction classification with multiple inputs."""
    result = classify_transaction(input_value)
    assert result == expected
```

### Testing Exceptions

```python
def test_handles_invalid_input():
    """Test that invalid input raises appropriate exception."""
    with pytest.raises(ValueError, match="Invalid date format"):
        parse_date("not-a-date")
```

## Test Standards

### Naming Conventions

- Test files: `test_<module>.py`
- Test functions: `test_<feature>_<condition>_<expected_outcome>()`
- Test classes: `Test<Feature>`

### Determinism Rules (Schema Registry)

For `schema_registry`-related tests, enforce deterministic path resolution:

- Never depend on OS default paths such as `~/Library/...` or user home state.
- Use `tmp_path` + `monkeypatch.setenv("FINJUICE_DATA_DIR", ...)` for default-path tests.
- Clear schema cache (`clear_cache()`) at test setup/teardown to prevent cross-test leakage.
- If testing fallback without env var, remove env (`monkeypatch.delenv`) and monkeypatch
  `get_default_data_dir()` to a temporary path.
- Keep v2 compatibility tests explicit by passing `metadata_dir` directly, rather than relying
  on whichever schema is active in the default registry.

### Docstrings

Every test must have a docstring explaining what it verifies:

```python
def test_ingest_deduplicates_by_row_hash():
    """Test that ingesting same file twice doesn't create duplicates.

    Verifies idempotency by checking that row_hash prevents duplicate
    entries even when the same XLSX file is imported multiple times.
    """
```

### Assertions

- Use descriptive assertion messages when helpful
- Prefer specific assertions over generic ones
- Test both happy path and error cases

```python
# Good: Specific assertion
assert len(transactions) == 4, "Should import all 4 transactions"

# Better: Multiple specific assertions
assert summary["inserted"] == 4
assert summary["updated"] == 0
assert summary["failed"] == 0
```

## Coverage Gate

### Enforced Minimum: 85%

- **Current enforced gate**: `--cov-fail-under=85`
- **Core modules** (db, ingest, tagging, transfer): keep coverage high with behavior tests
- **Critical paths**: prioritize meaningful checks for deduplication, row hashing, transfer pairing,
  storage idempotency, command contracts, rules, and export outputs

### Coverage Gaps (Acceptable)

Some lines are intentionally not covered:

- **CLI main entry point** (`if __name__ == "__main__"`): Tested via command invocation
- **Error logging branches**: Some rare error conditions are difficult to reproduce
- **Defensive code**: Exception handlers for "should never happen" cases

## Continuous Integration

### Pre-commit Checks

Before committing:

```bash
# Run all tests
uv run pytest

# Check formatting
uv run ruff check .

# Type check
uv run mypy src/
```

### CI/CD Pipeline

GitHub Actions runs on every push:

1. Run full test suite
2. Generate coverage report
3. Fail if coverage drops below 85%
4. Upload coverage to Codecov (if configured)

## Troubleshooting

### Tests Fail Locally

1. Ensure dependencies are up to date: `uv sync`
2. Clear pytest cache: `rm -rf .pytest_cache`
3. Ensure temporary files are not left under the project root

### Coverage Not Updating

1. Delete `.coverage` file: `rm .coverage`
2. Clear htmlcov: `rm -rf htmlcov/`
3. Run with `--cov-report=html` explicitly

### Slow Tests

1. Run unit tests only: `pytest -m unit`
2. Skip integration tests: `pytest -m "not integration"`
3. Prefer narrow test selection while iterating

## Contributing Tests

When adding new features:

1. Write tests **before** implementation (TDD)
2. Ensure new tests use shared fixtures from `conftest.py`
3. Add appropriate markers (`@pytest.mark.unit` or `@pytest.mark.integration`)
4. Update this README if adding new test categories
5. Verify coverage stays above the enforced 85% gate

## Related Documentation

- [CLAUDE.md](../CLAUDE.md) - Project guidelines for Claude Code
- [docs/architecture/specs/v0_initial.md](../docs/architecture/specs/v0_initial.md) - Full design specification
- [docs/architecture/README.md](../docs/architecture/README.md) - Architecture overview

---

**Last Updated:** 2026-05-11
