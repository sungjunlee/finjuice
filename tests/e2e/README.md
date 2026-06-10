# End-to-End Tests

This directory contains end-to-end (E2E) tests that validate the full pipeline with
synthetic fixtures and runtime-generated workbooks.

## Overview

E2E tests validate the complete pipeline workflow and release-gate stability, ensuring:
- Combined transaction + asset ingestion works in one pipeline run
- Core transaction outputs and reports are generated
- Asset snapshot daily dedup is preserved
- Idempotency is maintained across reruns

## Directory Structure

```
tests/e2e/
├── __init__.py                    # Package marker
├── README.md                      # This file
├── conftest.py                    # Shared E2E fixtures
├── test_cli_flow.py               # CLI end-to-end workflows
├── test_data_integrity.py         # Idempotency/data integrity E2E checks
├── test_error_handling.py         # End-to-end error scenarios
├── test_first_run.py              # First-run experience checks
├── test_real_data_pipeline.py     # Main E2E test suite (8 tests)
├── test_tx_asset_regression.py    # Minimal tx+asset regression gate (Issue #230)
├── metrics.py                     # Performance metrics collection
└── report_generator.py            # Markdown report generation
```

## Test Files

### [test_tx_asset_regression.py](test_tx_asset_regression.py)

Minimal transaction+asset regression gate for release reuse:

1. **test_tx_asset_minimal_e2e_flow**
   - Generates runtime XLSX with `가계부 내역` + `보유 종목`
   - Runs `finjuice refresh`
   - Verifies transaction partitions, asset snapshot partition, master export, and reports
   - Verifies asset daily dedup (`snapshot_date + account_id + instrument_id`)

2. **test_tx_asset_rerun_idempotent_for_tx_and_assets**
   - Runs `finjuice refresh` twice on the same runtime fixture
   - Verifies transaction `row_hash` set is unchanged
   - Verifies asset snapshot rows are unchanged

### [test_real_data_pipeline.py](test_real_data_pipeline.py)

Main E2E test suite with 8 comprehensive tests:

1. **test_clean_pipeline_with_real_data** - Complete pipeline validation
   - Runs ingest → tag → transfer → export
   - Validates all phases complete successfully
   - Checks performance (<10min), coverage (>60%), transfers detected
   - Generates performance report and metrics

2. **test_incremental_update** - Idempotency validation
   - Runs pipeline twice with same data
   - Verifies no duplicates created
   - Checks tags and transfer pairs remain consistent

3. **test_performance_benchmarks** - Performance validation
   - Measures execution time per phase
   - Calculates throughput (transactions/sec)
   - Validates CSV storage size is reasonable

4. **test_rule_effectiveness** - Tag coverage analysis
   - Validates >60% tag coverage target
   - Identifies top untagged merchants
   - Reports rule effectiveness

5. **test_transfer_detection_accuracy** - Transfer pairing validation
   - Validates transfer pairs have exactly 2 transactions
   - Checks is_transfer flag correctness
   - Verifies transfer_group_id assignment

6. **test_report_generation_and_validation** - Report output validation
   - Checks all 5 CSV reports generated
   - Validates master XLSX structure
   - Verifies transfer exclusion from expense reports

7. **test_csv_partition_consistency** - CSV partition integrity
   - No duplicate row_hash values
   - All required fields populated
   - JSON fields valid

8. **test_csv_partition_metrics** (planned) - Metrics calculation
   - Validates helper functions
   - Checks metric accuracy

### [metrics.py](metrics.py)

Performance metrics collection module providing:

**Classes:**
- `PhaseMetrics` - Metrics for individual pipeline phase
- `PipelineMetrics` - Comprehensive pipeline metrics (execution time, throughput, coverage)
- `MetricsCollector` - Collector for gathering and calculating metrics

**Key Features:**
- Phase timing (ingest, tag, transfer, export)
- Throughput calculation (transactions/sec, files/sec)
- Coverage metrics (tag coverage %, transfer detection rate)
- CSV storage metrics (partition size, transaction count)
- Rule effectiveness analysis
- JSON export for reporting

**Example Usage:**
```python
from tests.e2e.metrics import MetricsCollector

metrics = MetricsCollector(csv_base_dir)
metrics.start_phase("ingest")
# ... run ingestion ...
metrics.end_phase(success=True)

metrics.collect_storage_metrics()
pipeline_metrics = metrics.finalize()
metrics.print_summary()
metrics.save_report(output_path)
```

### [report_generator.py](report_generator.py)

Markdown report generation from pipeline metrics.

**Class:**
- `ReportGenerator` - Generates comprehensive markdown reports

**Report Sections:**
1. Executive Summary (status, key metrics vs targets)
2. Performance Metrics (phase timing, throughput)
3. Coverage Analysis (tag coverage breakdown)
4. Rule Effectiveness (untagged merchants, recommendations)
5. Transfer Detection (pairs found, detection rate)
6. CSV Storage Metrics (size, transactions)
7. Recommendations (actionable items)
8. Conclusion (ready for production? next steps)

**Example Usage:**
```python
from tests.e2e.report_generator import ReportGenerator

generator = ReportGenerator(pipeline_metrics)
report_md = generator.generate_report(output_path)
```

## Running Tests

### Run all E2E tests
```bash
uv run pytest tests/e2e/ -v
```

### Run minimal tx+asset regression gate
```bash
uv run pytest -q --no-cov \
  tests/e2e/test_tx_asset_regression.py \
  tests/test_asset_ingest_pipeline.py \
  tests/storage/test_asset_snapshot_storage.py \
  tests/cli/test_audit.py::TestAuditStatsCommand::test_audit_stats_template_metrics
```

### Run specific E2E test
```bash
uv run pytest tests/e2e/test_real_data_pipeline.py::test_clean_pipeline_with_real_data -v
```

### Run with fixture defaults
Synthetic E2E fixtures are bundled under:
```
tests/fixtures/e2e/synthetic_banksalad_e2e.xlsx
```
No external real-data file is required for the #230 minimal regression gate.

### View generated reports
After running tests, check the temporary directory for:
- `e2e_test_report.md` - Comprehensive markdown report
- `e2e_metrics.json` - Raw metrics in JSON format

### Run with coverage
```bash
uv run pytest tests/e2e/ --cov=src/finjuice --cov-report=term-missing
```

### Skip E2E tests (fast feedback)
```bash
uv run pytest -m "not e2e"
```

## Test Data Requirements

### Required Files

1. **Sample rules**
   - Path: `tests/fixtures/sample_rules.yaml`
   - Used by E2E pipeline tagging steps

2. **Synthetic fixture workbook**
   - Path: `tests/fixtures/e2e/synthetic_banksalad_e2e.xlsx`
   - Deterministic synthetic transactions for reproducible E2E runs

3. **Runtime-generated tx+asset workbook (Issue #230)**
   - Created at test runtime in temporary directories
   - Includes `가계부 내역` and `보유 종목` in one file
   - Includes an asset duplicate row to verify daily dedup behavior

### Data Anonymization

E2E fixtures in this repository are synthetic and deterministic.

**Do NOT commit actual personal financial data.**

## Success Criteria

E2E tests must meet these criteria to pass:

### Performance
- [ ] Total execution time < 10 minutes
- [ ] Throughput > 100 transactions/second
- [ ] Memory usage < 500 MB
- [ ] CSV storage size reasonable for dataset

### Accuracy
- [ ] Tag coverage > 60%
- [ ] Transfer detection accuracy > 80%
- [ ] No duplicate transactions
- [ ] All JSON fields valid

### Outputs
- [ ] Master XLSX created with all transactions
- [ ] All 5 CSV reports generated:
  - monthly_spend.csv
  - by_category.csv
  - by_tag.csv
  - by_account.csv
  - transfers.csv
- [ ] Reports have correct structure
- [ ] Transfers excluded from expense reports

### Reliability
- [ ] Idempotency verified (2 runs = identical output)
- [ ] All phases complete successfully
- [ ] No uncaught exceptions
- [ ] Error messages are helpful

## Troubleshooting

### Tests skip with "Synthetic data not found"

**Cause**: Missing `tests/fixtures/e2e/synthetic_banksalad_e2e.xlsx`

**Solution**:
- Regenerate fixture: `uv run python scripts/generate_e2e_fixtures.py`
- Re-run the E2E command

### Performance tests fail (>10 min)

**Cause**: Large dataset or slow system

**Solution**:
- Check fixture size and custom test inputs
- Profile slow phases using metrics report
- Consider optimizing CSV partition reads or using chunking

### Tag coverage below 60%

**Cause**: Rules don't match synthetic merchant patterns (or custom runtime fixture inputs)

**Solution**:
- Review `e2e_test_report.md` for top untagged merchants
- Update `tests/fixtures/sample_rules.yaml` to add missing patterns

### Transfer detection fails

**Cause**: No valid transfer pairs in dataset

**Solution**:
- Verify dataset has transfer transactions (type_raw='이체')
- Check amounts are opposite and within 5-minute window
- Review transfer detection parameters (time_window, amount_tolerance)

### Report generation errors

**Cause**: Missing export directories or storage read/write issues

**Solution**:
- Check exports/ and exports/reports/ directories exist
- Verify CSV partitions can be read and written
- Review log output for specific errors

## CI/CD Integration

E2E tests run separately from unit/integration tests for efficiency:

```yaml
# Fast feedback (unit + integration, skip E2E)
- run: pytest -m "not e2e" --cov

# Full validation (all tests including E2E)
- run: pytest --cov --cov-report=xml
```

**Recommended**: Run E2E tests on:
- Pull request creation
- Before merge to main
- Nightly builds
- Release candidates

## Contributing

When adding new E2E tests:

1. **Follow AAA pattern**: Arrange → Act → Assert
2. **Use descriptive names**: `test_<feature>_<scenario>_real_data`
3. **Add docstrings**: Explain what scenario is being validated
4. **Use fixtures**: Leverage `real_data_dir` fixture for test isolation
5. **Document expectations**: Add success criteria to test docstring
6. **Update this README**: Document new test scenarios

## Performance Benchmarks

Typical results with ~2,000 transaction dataset:

```
Execution Time: 5.2s
├─ ingest:   2.1s
├─ tag:      1.4s
├─ transfer: 0.8s
└─ export:   0.9s

Throughput:  385 transactions/sec

Coverage:
├─ Tag coverage: 68.4%
├─ Transfers:    42 pairs (84 transactions)
└─ Detection:    87.5%

CSV Storage: 1.8 MB
```

## Related Documentation

- [../integration/README.md](../integration/README.md) - Integration tests with synthetic data
- [../../CLAUDE.md](../../CLAUDE.md) - Project overview and architecture
- [../../docs/specs/v0_initial.md](../../docs/specs/v0_initial.md) - Complete design specification
- [../../docs/tasks/mvp_implementation.md](../../docs/tasks/mvp_implementation.md) - MVP roadmap

## Next Steps

After E2E tests pass:

1. Review generated report (`e2e_test_report.md`)
2. Address any recommendations
3. Document performance benchmarks
4. Proceed with production deployment
5. Monitor metrics in production
