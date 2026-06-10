# Integration Tests

This directory contains end-to-end integration tests for finjuice using real anonymized sample data.

## Overview

Integration tests validate the entire pipeline flow from XLSX ingestion through tagging, transfer detection, and export generation. Unlike unit tests which test individual functions in isolation, these tests verify that all components work together correctly.

## Test Structure

### Test Files

- **[test_full_pipeline.py](test_full_pipeline.py)** - Main integration test suite with 8 test scenarios
- **[helpers.py](helpers.py)** - Utility functions for test validation and data comparison
- **[generate_fixtures.py](generate_fixtures.py)** - Script to create anonymized test fixtures from real data

### Test Fixtures

Located in `../fixtures/`:

- **sample_banksalad.xlsx** - Anonymized sample with ~27 transactions (standard Korean schema)
- **sample_banksalad_alt_schema.xlsx** - Same data with English column names (tests schema evolution)
- **sample_rules.yaml** - Tagging rules that match the anonymized test data
- **expected_reports/** - Golden files for output validation (generated during tests)

## Test Scenarios

### 1. `test_full_pipeline_with_sample_data`
**Full end-to-end pipeline execution**

- Runs complete pipeline: ingest → tag → detect transfers → export
- Validates transaction counts at each stage
- Checks tag coverage meets >60% threshold
- Verifies transfer pair detection
- Confirms master XLSX and all 5 CSV reports are generated

### 2. `test_schema_evolution`
**Schema variant handling**

- Ingests standard Korean schema
- Ingests alternative English schema
- Verifies both map to standardized fields correctly
- Checks deduplication prevents duplicates

### 3. `test_transfer_detection_accuracy`
**Transfer pairing validation**

- Validates specific transfer pairs are matched
- Checks `is_transfer` flag is set correctly
- Verifies `transfer_group_id` assignment
- Tests unpaired transfers remain unpaired

### 4. `test_rule_hit_rate`
**Tagging coverage and accuracy**

- Validates rule matching achieves >60% coverage
- Checks specific merchants match expected tags
- Verifies `tags_final` JSON structure
- Tests confidence scores are valid (0-1 range)

### 5. `test_report_accuracy`
**Report generation and data integrity**

- Validates report structure (columns, data types)
- Checks transfer exclusion (transfers not in expense reports)
- Verifies tag aggregations match raw data
- Tests monthly summaries are correct

### 6. `test_incremental_pipeline_idempotency`
**Reproducibility and idempotency**

- Runs pipeline twice with same data
- Compares CSV partition state after each run
- Validates row hashes prevent duplicates
- Checks tags and transfer_group_ids are consistent

### 7. `test_master_xlsx_structure`
**Master XLSX output validation**

- Checks all required columns are present
- Validates data types
- Tests file structure and formatting

### 8. `test_csv_partition_metrics`
**Metrics calculation**

- Tests helper functions for metric extraction
- Validates tag coverage percentage
- Checks transfer pair counts
- Verifies type distribution

## Running Tests

### Run all integration tests
```bash
uv run pytest tests/integration/ -v
```

### Run specific test
```bash
uv run pytest tests/integration/test_full_pipeline.py::test_full_pipeline_with_sample_data -v
```

### Run with coverage
```bash
uv run pytest tests/integration/ --cov=src/finjuice --cov-report=term-missing
```

### Run in parallel (faster)
```bash
uv run pytest tests/integration/ -n auto
```

### Skip integration tests (run only unit tests)
```bash
uv run pytest -m "not integration"
```

## Test Data Creation

### Anonymization Process

Test fixtures are created from real Banksalad export data using [generate_fixtures.py](generate_fixtures.py):

1. **Selection**: Representative sample of 27 transactions including:
   - Regular expenses (various categories)
   - Income transactions
   - Transfer pairs (at least 2-3 pairs)
   - Edge cases (missing memo, large/small amounts)

2. **Anonymization**:
   - Merchant names → `TEST_*` patterns (e.g., `TEST_CAFE_A`, `TEST_CONVENIENCE_X`)
   - Account names → `TEST_BANK_*`, `TEST_CARD_*`
   - Memos → Cleared (set to None)
   - Dates → Preserved (no PII in dates)
   - Amounts → Preserved (realistic financial patterns)

3. **Schema variants**:
   - Standard: Korean column names (날짜, 시간, 타입, etc.)
   - Alternative: English lowercase names (date, time, type, etc.)

### Regenerating Fixtures

To regenerate test fixtures from a private source export:

```bash
uv run python tests/integration/generate_fixtures.py /path/to/private-banksalad-export.xlsx
```

## Test Utilities ([helpers.py](helpers.py))

### Core Functions

- **`compare_dataframes(df1, df2)`** - Compare DataFrames with numeric tolerance
- **`validate_xlsx_structure(file_path, required_columns)`** - Check XLSX file structure
- **`calculate_report_metrics(csv_base_dir)`** - Extract summary metrics from CSV partitions
- **`validate_transfer_pairing(csv_base_dir, expected_pairs)`** - Verify specific transfer pairs
- **`validate_rule_matching(csv_base_dir, expected_matches)`** - Check rule application
- **`validate_idempotency(csv_base_dir1, csv_base_dir2)`** - Compare two pipeline runs
- **`get_report_summary(csv_path)`** - Get summary stats from CSV report

## Expected Behavior

### Transaction Counts

With the sample data (~27 transactions):
- **Expenses**: ~17 transactions
- **Transfers**: ~9 transactions (4-5 pairs + unpaired)
- **Income**: ~1 transaction

### Tag Coverage

- **Target**: >60% of transactions tagged
- **Actual**: ~65-75% (depends on rules file)
- **Untagged**: Typically unusual merchants or one-time transactions

### Transfer Detection

- **Pairs detected**: 1-3 pairs (realistic for sample size)
- **Algorithm**: Greedy matching within 5-minute window
- **Unpaired**: Transfers without matching counterpart remain unpaired

### Report Generation

All 5 reports should be generated:
1. **monthly_spend.csv** - Monthly expense totals (transfers excluded)
2. **by_category.csv** - Spending aggregated by final category
3. **by_tag.csv** - Spending aggregated by tag
4. **by_account.csv** - Net spending by account/card
5. **transfers.csv** - Transfer audit log (paired transfers only)

## Troubleshooting

### Tests fail with "File not found" error

**Cause**: Test fixtures not generated
**Solution**:
```bash
uv run python tests/integration/generate_fixtures.py
```

### Tests fail with schema mapping errors

**Cause**: Column names don't match expected schema variants
**Solution**: Check [src/finjuice/pipeline/ingest/schemas.py](../../src/finjuice/pipeline/ingest/schemas.py) for supported column names

### Tag coverage too low (<60%)

**Cause**: Rules file doesn't match anonymized merchant names
**Solution**: Update [tests/fixtures/sample_rules.yaml](../fixtures/sample_rules.yaml) to include `TEST_*` patterns

### Transfer detection fails to find pairs

**Cause**: Sample data may not have valid transfer pairs (same amount, ±5min, opposite sign)
**Solution**: Check generate_fixtures.py selection logic or adjust test expectations

### Idempotency test fails

**Cause**: Non-deterministic elements (timestamps, random IDs)
**Solution**: Verify all IDs and timestamps use deterministic generation

## CI/CD Integration

Integration tests run in CI but are separated from fast unit tests for efficiency:

```yaml
# Fast feedback (unit tests only)
- run: pytest -m "not integration" --cov

# Full validation (all tests)
- run: pytest --cov --cov-report=xml
```

## Contributing

When adding new integration tests:

1. **Follow AAA pattern**: Arrange → Act → Assert
2. **Use descriptive names**: `test_<feature>_<scenario>`
3. **Add docstrings**: Explain what is being validated
4. **Keep tests independent**: Use fixtures for isolation
5. **Update this README**: Document new test scenarios

## Performance

Integration tests are slower than unit tests due to:
- CSV partition I/O
- XLSX file reading/writing
- Full pipeline execution

**Typical runtime**: 0.5-1 second per test (~8 seconds total)

For faster development iteration, run unit tests first:
```bash
uv run pytest tests/ -m "not integration" --maxfail=1
```

## Related Documentation

- [../fixtures/sample_rules.yaml](../fixtures/sample_rules.yaml) - Tagging rules for test data
- [../../src/finjuice/pipeline/](../../src/finjuice/pipeline/) - Pipeline implementation
- [../../CLAUDE.md](../../CLAUDE.md) - Project overview and architecture
- [../../docs/specs/v0_initial.md](../../docs/specs/v0_initial.md) - Complete design specification
