# row_hash Lookup Benchmark

Date: 2026-05-12
Issue: #597
Script: `scripts/benchmark_row_hash_lookup.py`
Raw result: `docs/benchmarks/row-hash-lookup-results.json`

## Decision

Do not add a production `metadata/partition_manifest` or persisted row_hash lookup map now.

The measured one-off lookup/edit path is still below a user-visible threshold for
representative solo personal-finance datasets. The worst measured scenario was
120 monthly partitions and 120,000 synthetic rows. In that case:

- `find_transaction_by_hash()` missing/last-partition scan p95: about 0.36s
- manual edit storage round trip p95: about 0.41s
- ephemeral row_hash map build p95: about 0.08s
- prebuilt dict probe mean: about 0.054 microseconds per lookup

A persisted manifest would make random hash lookup effectively constant-time, but
it would add a new SSOT-adjacent artifact that must stay in sync with ingest,
manual edits, migrations, and partition rewrites. The current workload is
single-row inspection/edit, so the complexity is not justified by the current
measurements.

## Revisit Threshold

Revisit a persisted partition manifest or row_hash lookup map when either condition
is true:

1. The maintained synthetic benchmark reports p95 >= 1.0s for either
   `find_transaction_by_hash()` `last_partition`/`missing_hash` or
   `manual_edit_round_trip` on a representative local dataset.
2. A real CLI workflow needs 10 or more independent row_hash lookups in one command
   invocation. On the 120k-row measurement, repeated full scans would spend roughly
   3.6s across 10 lookups, while a projected ephemeral map build is about 0.08s.

If this threshold is crossed, prefer a small design first: define the manifest
schema, invalidation rules, duplicate-hash behavior, migration story, and whether
the source of truth remains the CSV partitions.

## Methodology

The benchmark uses generated synthetic data only. It creates temporary
`transactions/YYYY/MM/transactions.csv` partitions with the live
`CSV_COLUMNS` schema and does not read user transaction data.

Measured operations:

- `find_transaction_by_hash`: current production helper, which scans every sorted
  partition and loads full partition DataFrames. It does not short-circuit on the
  first hit because it also detects duplicate row_hash matches across partitions.
- `manual_edit_round_trip`: `find_transaction_by_hash()` plus a single matching
  monthly partition rewrite via `write_month()`, approximating the storage cost of
  `finjuice tag --edit`.
- `ephemeral_row_hash_map`: comparison-only row_hash to `YYYY-MM` dict built from
  projected `row_hash` scans. This is not a production artifact.

Command:

```bash
uv run python scripts/benchmark_row_hash_lookup.py \
  --iterations 3 \
  --output docs/benchmarks/row-hash-lookup-results.json
```

Environment:

- Python: 3.13.11
- Polars: 1.35.2
- Platform: macOS-15.6.1-arm64-arm-64bit-Mach-O

## Results

Warm p95 timings, seconds:

| Scenario | Partitions | Rows | First lookup | Middle lookup | Last lookup | Missing lookup | Edit round trip | Map build |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| personal_6k | 24 | 6,000 | 0.0358 | 0.0349 | 0.0376 | 0.0385 | 0.0452 | 0.0098 |
| power_60k | 60 | 60,000 | 0.1889 | 0.1821 | 0.2914 | 0.2021 | 0.2216 | 0.0464 |
| stress_120k | 120 | 120,000 | 0.3883 | 0.3931 | 0.3645 | 0.3627 | 0.4134 | 0.0759 |

The first/middle/last lookup timings are intentionally similar at larger sizes
because the current helper scans all partitions to preserve duplicate detection.
That behavior keeps correctness simple, and the measured cost is still acceptable
for one-off manual edit workflows.
