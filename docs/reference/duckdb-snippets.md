# DuckDB SQL Snippets

> **Status**: Canonical reference for ad-hoc DuckDB queries on finjuice CSV partitions
> **Use with**: `finjuice query "SQL"` or `DuckDBAnalytics.conn.execute(...)`
> **Schema**: v3 `transactions` view over CSV partitions
> **Last updated**: 2026-04-15 (#425)

This page consolidates the DuckDB query patterns that repeatedly came up during the
2026-04-14 finance review. All snippets assume the `transactions` view already exists,
which is true for `finjuice query` and for `DuckDBAnalytics` after initialization.

If you are working in plain DuckDB without that view, register the CSV files first using the
`read_csv(...)` pattern in the [DuckDB setup guide](../guides/setup/duckdb-setup.md).

## Quick Rules

- Use `FROM transactions` for ad-hoc analysis in finjuice.
- Treat `amount < 0` as expense and `amount > 0` as income.
- Use `category_final` for category totals. It is the single-value v3 aggregation field.
- Use `tags_final` only when you need tag-level filtering or exploding.
- Exclude internal transfers from spend queries with
  `(is_transfer = 0 OR is_transfer IS NULL)`.

## Pitfalls

### Date formatting trap

Wrong: SQLite-style string slicing treats `date` like text.

```sql
SELECT substr(date, 1, 7) AS month
FROM transactions;
```

Right: `date` is a DuckDB `DATE`, so use `strftime`.

```sql
SELECT strftime(date, '%Y-%m') AS month
FROM transactions;
```

### JSON array trap

Wrong: `json_each(tags_final)` is a SQLite pattern and is not the safe default here.

```sql
SELECT *
FROM transactions, json_each(tags_final);
```

Right: parse the JSON string into a DuckDB list, then `UNNEST` it.

```sql
SELECT tag
FROM transactions
CROSS JOIN UNNEST(from_json(tags_final, '["VARCHAR"]')) AS tag_list(tag);
```

### Transfer filter trap

Wrong: expense-only filters still count internal transfers.

```sql
SELECT ROUND(SUM(-amount), 0) AS spend_krw
FROM transactions
WHERE amount < 0;
```

Right: keep the transfer exclusion pattern in every spend query.

```sql
SELECT ROUND(SUM(-amount), 0) AS spend_krw
FROM transactions
WHERE amount < 0
  AND (is_transfer = 0 OR is_transfer IS NULL);
```

## Snippets

### 1. Monthly spend aggregation

Use when: You want a clean month-by-month spend trend without income or internal transfers.

```sql
SELECT
    strftime(date, '%Y-%m') AS month,
    COUNT(*) AS expense_count,
    ROUND(SUM(-amount), 0) AS spend_krw
FROM transactions
WHERE amount < 0
  AND (is_transfer = 0 OR is_transfer IS NULL)
GROUP BY 1
ORDER BY 1 DESC;
```

Pitfalls:
- Use `strftime(date, '%Y-%m')`, not `substr(date, ...)`.
- Keep the transfer filter or card-payment/account-transfer rows will overstate spending.

### 2. Category totals with `category_final`

Use when: You need report-safe category totals under the v3 single-category aggregation model.

```sql
SELECT
    category_final,
    COUNT(*) AS txn_count,
    ROUND(SUM(-amount), 0) AS spend_krw
FROM transactions
WHERE amount < 0
  AND (is_transfer = 0 OR is_transfer IS NULL)
GROUP BY 1
ORDER BY spend_krw DESC, category_final;
```

Pitfalls:
- Use `category_final`, not `tags_final`, for category rollups.
- `category_final` already resolves the v3 priority chain, so you do not need to coalesce
  `category_rule`, `minor_raw`, and `major_raw` again.

### 3. Tag totals with DuckDB JSON unnest

Use when: You want a tag-level breakdown and need DuckDB-safe exploding of `tags_final`.
The CLI `pivot` wrapper reuses this exact unnest-before-aggregate pattern: `finjuice template run pivot --param row=month --param col=tags_final`.

```sql
WITH expense_rows AS (
    SELECT
        date,
        amount,
        tags_final
    FROM transactions
    WHERE amount < 0
      AND (is_transfer = 0 OR is_transfer IS NULL)
)
SELECT
    tag,
    COUNT(*) AS txn_count,
    ROUND(SUM(-amount), 0) AS spend_krw
FROM expense_rows
CROSS JOIN UNNEST(from_json(tags_final, '["VARCHAR"]')) AS tag_list(tag)
GROUP BY 1
ORDER BY spend_krw DESC, tag;
```

Pitfalls:
- Do not use SQLite's `json_each(tags_final)` pattern here.
- `tags_final` is a JSON array serialized as text in CSV, so parse first and unnest second.

### 4. Transfer inflation audit

Use when: You want to see how much gross outflow is being inflated by internal transfers.

```sql
SELECT
    ROUND(SUM(CASE WHEN amount < 0 THEN -amount ELSE 0 END), 0)
        AS outflow_including_transfers_krw,
    ROUND(
        SUM(
            CASE
                WHEN amount < 0 AND (is_transfer = 0 OR is_transfer IS NULL) THEN -amount
                ELSE 0
            END
        ),
        0
    ) AS spend_excluding_transfers_krw,
    ROUND(
        SUM(CASE WHEN amount < 0 THEN -amount ELSE 0 END)
        - SUM(
            CASE
                WHEN amount < 0 AND (is_transfer = 0 OR is_transfer IS NULL) THEN -amount
                ELSE 0
            END
        ),
        0
    ) AS transfer_only_delta_krw
FROM transactions;
```

Pitfalls:
- `amount < 0` alone means "cash went out," not "real spend."
- This check is a fast sanity pass before you trust any monthly or merchant totals.

### 5. Income vs expense split by amount sign

Use when: You want a simple cashflow split using the canonical sign convention from the schema.

```sql
SELECT
    CASE
        WHEN amount < 0 THEN 'expense'
        WHEN amount > 0 THEN 'income'
        ELSE 'zero'
    END AS flow_type,
    COUNT(*) AS txn_count,
    ROUND(SUM(ABS(amount)), 0) AS gross_krw,
    ROUND(SUM(amount), 0) AS net_krw
FROM transactions
WHERE (is_transfer = 0 OR is_transfer IS NULL)
GROUP BY 1
ORDER BY flow_type;
```

Pitfalls:
- Keep transfers out or transfers will appear as both incoming and outgoing cashflow.
- `type_norm` is useful for filtering, but amount sign is the canonical convention for totals.

### 6. Latest month vs previous month

Use when: You want an immediate before/after comparison without hard-coding month literals.

```sql
WITH monthly AS (
    SELECT
        strftime(date, '%Y-%m') AS month,
        ROUND(SUM(-amount), 0) AS spend_krw
    FROM transactions
    WHERE amount < 0
      AND (is_transfer = 0 OR is_transfer IS NULL)
    GROUP BY 1
),
ranked AS (
    SELECT
        month,
        spend_krw,
        ROW_NUMBER() OVER (ORDER BY month DESC) AS month_rank
    FROM monthly
)
SELECT
    curr.month AS current_month,
    curr.spend_krw AS current_spend_krw,
    prev.month AS previous_month,
    prev.spend_krw AS previous_spend_krw,
    curr.spend_krw - prev.spend_krw AS delta_krw,
    ROUND(
        100.0 * (curr.spend_krw - prev.spend_krw) / NULLIF(prev.spend_krw, 0),
        1
    ) AS delta_pct
FROM ranked AS curr
JOIN ranked AS prev
  ON prev.month_rank = curr.month_rank + 1
WHERE curr.month_rank = 1;
```

Pitfalls:
- This compares the latest month present in the data, not necessarily a fully closed month.
- The month format stays `YYYY-MM` so lexical ordering still matches chronological ordering.

### 7. Template shortcut: baseline vs current compare

Use when: You want the reusable CLI wrapper for month-window comparison by category,
major group, or merchant without rewriting the FULL OUTER JOIN each time.

```bash
finjuice template run compare \
  --param baseline_months=2024-01:2024-03 \
  --param current_months=2024-04:2024-06 \
  --param group_by=category_final \
  --output json
```

This emits `group_key`, `baseline_monthly_avg`, `current_monthly_avg`, `diff`, and
`pct_change`. See the [CLI reference](cli.md) for the full `template` command surface.

### 8. Top merchants by spend

Use when: You want to find the biggest spend sinks by raw merchant text before cleaning rules.

```sql
SELECT
    merchant_raw,
    COUNT(*) AS txn_count,
    ROUND(SUM(-amount), 0) AS spend_krw
FROM transactions
WHERE amount < 0
  AND (is_transfer = 0 OR is_transfer IS NULL)
  AND merchant_raw IS NOT NULL
  AND merchant_raw <> ''
GROUP BY 1
ORDER BY spend_krw DESC, txn_count DESC, merchant_raw
LIMIT 20;
```

Pitfalls:
- `merchant_raw` is source text, so issuer-specific spelling differences may split the same merchant.
- Keep transfer rows out or account-to-account moves can surface as fake top merchants.

### 8. Account-level cashflow summary

Use when: You need to see which cards/accounts drive expense, income, and net movement.

```sql
SELECT
    account,
    COUNT(*) AS txn_count,
    ROUND(SUM(CASE WHEN amount < 0 THEN -amount ELSE 0 END), 0) AS expense_krw,
    ROUND(SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END), 0) AS income_krw,
    ROUND(SUM(amount), 0) AS net_krw
FROM transactions
WHERE (is_transfer = 0 OR is_transfer IS NULL)
GROUP BY 1
ORDER BY expense_krw DESC, account;
```

Pitfalls:
- Net totals are only comparable after removing transfers.
- This is account-centric; use `counterparty` or `transfer_group_id` when you actually want
  transfer-pair analysis.

### 9. Running cumulative spend

Use when: You want a year-to-date or all-time burn curve on monthly spend totals.

```sql
WITH monthly AS (
    SELECT
        strftime(date, '%Y-%m') AS month,
        ROUND(SUM(-amount), 0) AS spend_krw
    FROM transactions
    WHERE amount < 0
      AND (is_transfer = 0 OR is_transfer IS NULL)
    GROUP BY 1
)
SELECT
    month,
    spend_krw,
    SUM(spend_krw) OVER (ORDER BY month) AS cumulative_spend_krw
FROM monthly
ORDER BY month;
```

Pitfalls:
- The running total is only stable if `month` stays in `YYYY-MM` format.
- This is a spend curve, so it intentionally excludes income and transfers.

## See Also

- [DuckDB setup guide](../guides/setup/duckdb-setup.md)
- [Schema reference](schema.md)
- [Schema registry](../../templates/schema.yaml)
