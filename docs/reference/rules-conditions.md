# Conditional Rule Engine Reference

> **Status**: Canonical reference (v0.6.0+)
> **Introduced**: v0.6.0 (Issue #400)
> **Last updated**: 2026-04-12 (#408)

This page is the canonical reference for the v0.6.0+ conditions engine.

## Overview

The conditions engine matches a transaction against one or more structured predicates.
Each condition specifies `field`, `op`, and `value`. Multiple conditions combine via
`logic: all` (AND) or `logic: any` (OR).

Unlike legacy `match`/`fields`, conditions make the target field explicit per predicate.
This is the preferred syntax when you need exact equality, numeric ranges, or mixed
field-specific logic inside one rule.

```yaml
rules:
  - name: premium_dining
    conditions:
      - {field: major_raw, op: is, value: "식비"}
      - {field: amount, op: between, value: [-200000, -50000]}
    logic: all
    tags: ["외식", "프리미엄"]
    priority: 70
```

> **Implementation evidence**
> The operator semantics on this page come from
> `src/finjuice/pipeline/tagging/rules.py`, especially `_check_condition`,
> `_check_numeric_condition`, `_check_regex`, `_check_conditions`, and
> `_get_rule_match`.

## Report Filters

`report_filters` is a read-time exclusion block inside `rules.yaml`. It does not
change transaction CSV partitions on disk; it only removes matched rows from analysis
surfaces.

Commands that honor `report_filters`:
- `finjuice status`
- `finjuice template run`
- `finjuice show`
- `finjuice export`
- `finjuice query`

`_meta.filters_applied` is the number of configured filter rules that matched at least
one source row for that command invocation. It is a rule count, not a row count. This
semantic was established in FLT-01 and is preserved across all JSON surfaces.

`finjuice --no-filter ...` disables `report_filters` for a single invocation. When that
flag is present, the commands above skip read-time filtering and emit
`_meta.filters_applied = 0`.

`finjuice query` uses the default-on strategy: the CLI prepends a CTE that rebinds the
conventional `transactions` view to filtered rows, then executes the user's SQL as a
subquery. The CLI does not parse or rewrite the user's SQL clauses. Queries that
deliberately bypass the `transactions` view, such as direct reads from
`transactions_source`, also bypass this filter layer by design.

`finjuice export` keeps `master_YYYYMMDD.xlsx` unfiltered so there is always a full
audit artifact. The report-style outputs (`exports/reports/*.csv`, HTML, Markdown)
honor `report_filters` unless `--no-filter` is set.

## Operators

### Operators table

| Operator | Applies to | Semantics | Example |
|---|---|---|---|
| `contains` | text | case-insensitive substring | `{field: merchant_raw, op: contains, value: "스타벅스"}` |
| `not_contains` | text | negation of contains | `{field: merchant_raw, op: not_contains, value: "배달"}` |
| `is` | text | exact equality, case-insensitive | `{field: major_raw, op: is, value: "식비"}` |
| `is_not` | text | exact inequality, case-insensitive | `{field: type_norm, op: is_not, value: "transfer"}` |
| `starts_with` | text | case-insensitive prefix | `{field: merchant_raw, op: starts_with, value: "(주)"}` |
| `regex` | text | Python regex, always `re.IGNORECASE` | `{field: merchant_raw, op: regex, value: "OPENAI&#124;CLAUDE"}` (see subsection for unescaped form) |
| `less_than` | numeric | `<` float comparison | `{field: amount, op: less_than, value: -10000}` |
| `greater_than` | numeric | `>` float comparison | `{field: amount, op: greater_than, value: 1000}` |
| `between` | numeric | inclusive range | `{field: amount, op: between, value: [-50000, -10000]}` |

### `contains`

Case-insensitive substring match. The engine lowercases both the field value and the
condition value before checking membership.

- Accepted `value`: string
- Typical use: merchant keyword, memo keyword, broad text classification

```yaml
rules:
  - name: coffee_starbucks
    conditions:
      - field: merchant_raw
        op: contains
        value: "스타벅스"
    tags: ["카페", "커피"]
    priority: 80
```

Gotchas:
- `contains` is not exact match. `"식"` also matches `"식비"`.
- On `type_norm`, `contains` works, but `is` is usually clearer.

### `not_contains`

Negation of `contains`. It matches when the lowercase substring is absent from the
target field.

- Accepted `value`: string
- Typical use: exclude one text pattern while keeping broader conditions

```yaml
rules:
  - name: dining_except_delivery
    conditions:
      - field: major_raw
        op: is
        value: "식비"
      - field: merchant_raw
        op: not_contains
        value: "배달"
    logic: all
    tags: ["외식"]
    priority: 72
```

Gotchas:
- `not_contains` is still substring logic. It does not mean "different full string."
- If you need exact inequality, use `is_not`.

### `is`

Case-insensitive whole-field equality. The entire normalized field value must equal the
entire normalized condition value.

- Accepted `value`: string
- Typical use: enum-like fields such as `type_norm`, or exact category names

```yaml
rules:
  - name: all_food_rows
    conditions:
      - field: major_raw
        op: is
        value: "식비"
    tags: ["식비"]
    priority: 60
```

```yaml
rules:
  - name: transfer_rows
    conditions:
      - field: type_norm
        op: is
        value: "transfer"
    tags: ["내부이체"]
    priority: 95
```

Gotchas:
- Users often expect `is` to behave like "contains." It does not.
- `value: "식"` does not match `major_raw: "식비"`. Use `contains` for substring intent.

### `is_not`

Case-insensitive whole-field inequality. It matches when the normalized field value is
not exactly equal to the normalized condition value.

- Accepted `value`: string
- Typical use: exclude one exact enum or category value

```yaml
rules:
  - name: non_transfer_income
    conditions:
      - field: type_norm
        op: is_not
        value: "transfer"
      - field: amount
        op: greater_than
        value: 0
    logic: all
    tags: ["수입"]
    priority: 75
```

Gotchas:
- Users often confuse `is_not` with `not_contains`.
- `is_not: "transfer"` still matches `expense`, `income`, and `other`, because this is
  exact inequality, not substring negation.

### `starts_with`

Case-insensitive prefix match. The normalized field value must start with the normalized
condition value.

- Accepted `value`: string
- Typical use: legal prefixes, issuer prefixes, memo conventions

```yaml
rules:
  - name: corp_merchants
    conditions:
      - field: merchant_raw
        op: starts_with
        value: "(주)"
    tags: ["법인"]
    priority: 68
```

Gotchas:
- `starts_with` only checks the beginning of the field.
- It is usually less expressive than `regex`, but clearer when a simple prefix is enough.

### `regex`

Python regular expression match using `re.search`. Matching is always case-insensitive.

- Accepted `value`: string containing a Python regex pattern
- Typical use: multiple spelling variants, anchored prefixes, structured text patterns

```yaml
rules:
  - name: ai_services
    conditions:
      - field: merchant_raw
        op: regex
        value: 'OPENAI|CLAUDE'
    tags: ["AI", "디지털구독"]
    priority: 88
```

```yaml
rules:
  - name: card_fee_prefix
    conditions:
      - field: memo_raw
        op: regex
        value: '^CARD FEE'
    tags: ["수수료"]
    priority: 65
```

Gotchas:
- `regex` always uses `re.IGNORECASE`. There is no per-rule `case_sensitive` switch
  today.
- A future `case_sensitive` option is on the roadmap, but it does not exist in v0.6.0.
- Invalid regex patterns do not crash tagging. The engine logs a warning and evaluates
  the condition as `False`.

### `less_than`

Strict numeric `<` comparison after converting the field value and condition value to
`float`.

- Accepted `value`: number or numeric string
- Typical use: negative-spend thresholds, low-value filtering

```yaml
rules:
  - name: large_expense
    conditions:
      - field: amount
        op: less_than
        value: -100000
    tags: ["고액지출"]
    priority: 85
```

Gotchas:
- `less_than` is strict. `-100000` does not match `value: -100000`.
- Numeric operators on non-numeric fields evaluate to `False`. They do not raise an
  error at match time.

### `greater_than`

Strict numeric `>` comparison after converting the field value and condition value to
`float`.

- Accepted `value`: number or numeric string
- Typical use: income thresholds, positive-value filtering

```yaml
rules:
  - name: meaningful_income
    conditions:
      - field: amount
        op: greater_than
        value: 1000
    tags: ["수입", "입금"]
    priority: 70
```

Gotchas:
- `greater_than` is strict. `1000` does not match `value: 1000`.
- Numeric operators on non-numeric fields evaluate to `False`. They do not raise an
  error at match time.

### `between`

Inclusive numeric range comparison. The engine parses the condition into `min,max` and
matches when `min <= field_value <= max`.

- Accepted `value`: two-item YAML list or `"min,max"` string
- Typical use: spend bands, income bands, amount bucketing

```yaml
rules:
  - name: medium_expense
    conditions:
      - field: amount
        op: between
        value: [-50000, -10000]
    tags: ["중간지출"]
    priority: 85
```

```yaml
rules:
  - name: medium_income
    conditions:
      - field: amount
        op: between
        value: "100000,500000"
    tags: ["중간수입"]
    priority: 72
```

Gotchas:
- `between` is inclusive on both ends.
- Numeric operators on non-numeric fields evaluate to `False`. They do not raise an
  error at match time.
- Detailed accepted formats are documented in [`between` - value formats](#between--value-formats).

## Fields

Use the following fields for conditions.

| Field | Type | Notes |
|---|---|---|
| `merchant_raw` | text | 가맹점명 원본 |
| `memo_raw` | text | 사용자 메모 |
| `major_raw` | text | 뱅크샐러드 대분류 |
| `minor_raw` | text | 뱅크샐러드 소분류 |
| `type_norm` | text | `expense` / `income` / `transfer` / `other` |
| `amount` | numeric | 음수=지출, 양수=수입 |
| `account` | text | 계좌/카드명 |

## Field x Operator Matrix (recommended usage)

This table shows the **recommended** operator for each field, not a hard support
matrix. Internally the engine stringifies every non-numeric field value before
applying text operators, so `starts_with`/`regex` on `type_norm` technically run
— they're just rarely the clearest expression.

| Field \\ Op | contains | is | starts_with | regex | less_than/greater_than/between |
|---|---|---|---|---|---|
| `merchant_raw`, `memo_raw`, `major_raw`, `minor_raw`, `account` | ✓ | ✓ | ✓ | ✓ | — |
| `type_norm` | ✓ | ✓ **(recommended)** | △ works, rarely needed | △ works, rarely needed | — |
| `amount` | △ | △ | △ | △ | ✓ |

Legend: ✓ idiomatic, △ functional but unusual, — not supported.

Notes:
- `not_contains` mirrors `contains` compatibility; `is_not` mirrors `is`.
- `type_norm` enum-like values (`expense`/`income`/`transfer`/`other`) read clearest
  with `is` / `is_not`.
- **Text operators on `amount` run against the stringified decimal representation**
  (`_check_condition` calls `str(field_value)` before text matching). For example,
  `{field: amount, op: contains, value: "150"}` matches `-150000` and `1500` alike.
  This is rarely what you want — prefer `less_than`/`greater_than`/`between` on
  `amount`. Reference: `_check_condition` in `src/finjuice/pipeline/tagging/rules.py`.
- **Numeric ops (`less_than`/`greater_than`/`between`) on non-numeric fields silently
  return false** (the engine catches the float cast error). No warning. Reference:
  `_check_numeric_condition` in the same file.

## `logic: all` vs `logic: any`

`logic: all` means every condition must match. `logic: any` means at least one condition
must match. If `logic` is omitted, the default is `all`.

### `logic: all` example

```yaml
rules:
  - name: dining_large_ticket
    conditions:
      - field: major_raw
        op: is
        value: "식비"
      - field: amount
        op: less_than
        value: -30000
    logic: all
    tags: ["외식", "고액지출"]
    priority: 82
```

### `logic: any` example

```yaml
rules:
  - name: ai_or_cloud
    conditions:
      - field: merchant_raw
        op: contains
        value: "OPENAI"
      - field: merchant_raw
        op: contains
        value: "AWS"
    logic: any
    tags: ["개발도구"]
    priority: 78
```

## Conditions vs legacy `match`/`fields` precedence

> ⚠️ When a rule defines both `conditions` AND `match`/`fields`, **conditions win**.
> The legacy `match`/`fields` fields are **ignored** entirely for that rule.
> If you want to mix matching strategies within a rule, use multiple conditions with
> `logic: any`. Reference: `_get_rule_match` in `src/finjuice/pipeline/tagging/rules.py`.

## `between` — value formats

The numeric range operator `between` accepts **two equivalent value formats**:

### Recommended: YAML list

```yaml
conditions:
  - {field: amount, op: between, value: [-50000, -10000]}
```

### Compact: CSV string

```yaml
conditions:
  - {field: amount, op: between, value: "-50000,-10000"}
```

Both forms are normalized to the same internal representation and produce identical
matching. Use whichever reads better in context.

### Constraints

- Exactly **2 numeric elements**. `[1, 2, 3]` or `"1"` fails validation with a clear
  error message.
- `min <= max`. Reversed ranges fail with `min must be <= max`.
- Values may be integers or floats; YAML autocoerces `-50000` and `-50000.0`
  identically.
- Bounds are **inclusive** on both ends.

### Typical use cases

| Scope | Example |
|---|---|
| 중간 지출 구간 | `value: [-50000, -10000]` |
| 대형 지출 | `value: "-500000,-100000"` |
| 소액 수입 | `value: [1000, 50000]` |

### Error message (reference)

Invalid inputs produce:

```
Rule '<name>': condition at index N has invalid 'value' for between: <got>.
Use [min, max] list or 'min,max' string (e.g., [-50000, -10000] or '-50000,-10000').
```

## See also

- [`docs/architecture/specs/v0_initial.md`](../architecture/specs/v0_initial.md) - Original rules.yaml spec
- [`docs/reference/schema.md`](schema.md) - Transaction schema and field meanings
- [`docs/workflows/rule-editing-with-claude.md`](../workflows/rule-editing-with-claude.md) - End-to-end editing workflow
- [`templates/rules.yaml.example`](../../templates/rules.yaml.example) - Copy-paste starter examples
- `src/finjuice/pipeline/tagging/rules.py` - Implementation
