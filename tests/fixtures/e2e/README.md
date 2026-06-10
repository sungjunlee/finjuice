# E2E Test Fixtures

Synthetic test data for end-to-end pipeline testing.

## Files

- `synthetic_banksalad_e2e.xlsx` - Synthetic Banksalad export: 93 rows spanning
  3 months, of which 87 ingest as valid transactions (3 duplicate rows are
  deduplicated and 3 malformed rows are skipped on ingest).

## Regeneration

If you need to regenerate the test data:

```bash
uv run python scripts/generate_e2e_fixtures.py
```

## Data Characteristics

| Category | Count | Description |
|----------|-------|-------------|
| Expenses | 60 | Rule-matching + untagged merchants |
| Incomes | 8 | Salary + misc income |
| Transfers | 19 | 8 pairs + 3 unpaired |
| Duplicates | 3 | Verbatim copies of expense rows — deduplicated by `row_hash` on ingest |
| Malformed | 3 | Missing date, non-numeric amount, missing account — skipped row-by-row on ingest |

The duplicate and malformed rows keep the E2E suite exercising the
deduplication and row-level validation paths on every run. They are appended
after the random rows, so the reproducible seed-42 output is unaffected.
`tests/e2e/test_real_data_pipeline.py::test_synthetic_fixture_edge_cases`
asserts all four edge-case classes are present.

### Rule-Matching Merchants

The synthetic data includes merchants that match `tests/fixtures/sample_rules.yaml`:

- Cafes: 스타벅스, 이디야
- Convenience: GS25, CU, 세븐일레븐
- Medical: 병원, 약국
- Transport: 카카오택시, 지하철
- Subscriptions: 넷플릭스, 스포티파이
- Utilities: 관리비, 전기, 가스
- Insurance: 메트라이프, 삼성화재

### Untagged Merchants

20 transactions with merchants that don't match any rules:
- 다이소, 올리브영, 쿠팡, 배달의민족, CGV, etc.

### Transfer Pairs

8 transfer pairs with varying characteristics:
- Time differences: 1-5 minutes
- Amount range: 10,000 ~ 10,000,000 KRW
- Edge cases: 5-minute boundary, large/small amounts

### Duplicate & Malformed Rows

- **Duplicates**: the first 3 expense rows are appended verbatim. Identical
  `row_hash` values mean ingest drops them — `skipped_dedup == 3`.
- **Malformed**: 3 rows that each trip one validation failure (missing date,
  non-numeric amount, missing account). Ingest skips them row-by-row and
  continues — `len(skipped_rows) == 3`.

### Date Range

2025-08-01 ~ 2025-10-31 (3 months for partition testing)

## Reproducibility

- Fixed random seed: 42
- Deterministic output on each run
