# Schema Reference

> **Auto-generated from** [`templates/schema.yaml`](../../templates/schema.yaml)
> **Do not edit manually** - Run `just docs-schema` to regenerate

---

## Current Schema: v4

Row-level manual notes plus category system for accurate report aggregation

**Issue**: #14
**Introduced**: 2026-06-09

### Performance Metrics

- **Total Columns**: 28
- **New Columns**: `notes_manual`
- **Category Priority**: `manual category override > category_rule > minor_raw > major_raw > '미분류'`
- **Aggregation Accuracy**: 100% (no duplicate counting)
- **Note**: Separates category (single, for aggregation), tags (multiple, for filtering), and transfer candidate vs confirmed state


### Partition Configuration

- **Location Pattern**: `data/transactions/YYYY/MM/transactions.csv`
- **Format**: CSV
- **Encoding**: utf-8
- **Sort By**: `datetime`

---

## Column Definitions (28 columns)

| Column | Type | Nullable | Description | Example |
|--------|------|----------|-------------|---------|
| `row_hash` | string | ✗ | SHA256[:16] transaction hash for deduplication | `ac875c7391d4e2f8` |
| `date` | date | ✗ | Transaction date | `2025-07-23` |
| `time` | time | ✗ | Transaction time (24-hour format) | `08:33` |
| `type_raw` | string | ✓ | Raw transaction type from Banksalad export | `지출` |
| `type_norm` | string | ✗ | Normalized transaction type for analytics | `-` |
| `major_raw` | string | ✓ | Major category from Banksalad (대분류) | `식비` |
| `minor_raw` | string | ✓ | Minor category from Banksalad (소분류) | `카페` |
| `merchant_raw` | string | ✓ | Merchant name from Banksalad export | `(주)카카오` |
| `memo_raw` | string | ✓ | User memo field from Banksalad export | `-` |
| `notes_manual` | string | ✓ | Manual row-level explanatory note controlled by finjuice users or agents | `3개월 할부` |
| `amount` | float | ✗ | Transaction amount (negative for expenses, positive for income) | `152129.0` |
| `account` | string | ✗ | Account or card name | `삼성카드법인` |
| `currency` | string | ✗ | Currency code (ISO 4217) | `KRW` |
| `counterparty` | string | ✓ | Counterparty account for transfer transactions | `우리은행` |
| `datetime` | datetime | ✗ | Combined datetime for sorting and time-based matching | `2025-07-23T08:33:00` |
| `category_rule` | string | ✓ | Category assigned by rules.yaml (single value for aggregation) | `온라인쇼핑` |
| `category_final` | string | ✗ | Final category for report aggregation (no duplicates) | `온라인쇼핑` |
| `tags_rule` | json_array | ✗ | Attribute tags applied by all matching enabled rules | `["정기지출", "해외결제"]` |
| `tags_ai` | json_array | ✗ | AI-generated tags (optional, Phase 2+) | `["업무식대"]` |
| `tags_manual` | json_array | ✗ | User-added tags via review queue | `["의료"]` |
| `tags_final` | json_array | ✗ | Final merged attribute tag list (rule + AI + manual) | `["정기지출", "해외결제", "의료"]` |
| `confidence` | float | ✓ | Binary tagging coverage confidence, not model confidence | `1.0` |
| `needs_review` | integer | ✓ | Flag derived from coverage confidence (1 when confidence < 0.7) | `-` |
| `is_transfer_candidate` | integer | ✓ | Transfer-like candidate flag from raw transaction type (1=candidate, not necessarily excluded) | `-` |
| `is_transfer` | integer | ✓ | Confirmed internal transfer flag (1=confirmed paired transfer, excluded from expense reports) | `-` |
| `transfer_group_id` | string | ✓ | Groups paired transfers (debit/credit) | `transfer_20250723_152129` |
| `file_id` | string | ✗ | Compact source file identifier (YYMMDD_N or 8-char hash fallback) | `241027_1` |
| `source_row` | integer | ✗ | Row number in source XLSX file (1-indexed) | `597` |


### Column Details

#### `row_hash`

**Type**: `string` (length: 16)
**Nullable**: No

SHA256[:16] transaction hash for deduplication

**Example**: `ac875c7391d4e2f8`

**Pattern**: `^[0-9a-f]{16}$`

**Note**: Increased from 10 to 16 chars (Issue #81) for negligible collision risk

---

#### `date`

**Type**: `date`
**Nullable**: No

Transaction date

**Example**: `2025-07-23`

---

#### `time`

**Type**: `time`
**Nullable**: No

Transaction time (24-hour format)

**Example**: `08:33`

---

#### `type_raw`

**Type**: `string`
**Nullable**: Yes

Raw transaction type from Banksalad export

**Example**: `지출`

---

#### `type_norm`

**Type**: `string` (enum: expense, income, transfer, other)
**Nullable**: No

Normalized transaction type for analytics

---

#### `major_raw`

**Type**: `string`
**Nullable**: Yes

Major category from Banksalad (대분류)

**Example**: `식비`

**Note**: Preserved as-is from Banksalad, used as category fallback

---

#### `minor_raw`

**Type**: `string`
**Nullable**: Yes

Minor category from Banksalad (소분류)

**Example**: `카페`

**Note**: Preserved as-is from Banksalad, used as category fallback (priority over major_raw)

---

#### `merchant_raw`

**Type**: `string`
**Nullable**: Yes

Merchant name from Banksalad export

**Example**: `(주)카카오`

**Note**: Used for rule matching and transfer detection

---

#### `memo_raw`

**Type**: `string`
**Nullable**: Yes

User memo field from Banksalad export

**Note**: Excluded from row_hash calculation

---

#### `notes_manual`

**Type**: `string`
**Nullable**: Yes

Manual row-level explanatory note controlled by finjuice users or agents

**Example**: `3개월 할부`

**Note**: Excluded from row_hash, tag aggregation, category aggregation, and audit content

---

#### `amount`

**Type**: `float`
**Nullable**: No

Transaction amount (negative for expenses, positive for income)

**Example**: `152129.0`

**Convention**: Expenses are negative, income is positive

---

#### `account`

**Type**: `string`
**Nullable**: No

Account or card name

**Example**: `삼성카드법인`

**Note**: Used for transfer pairing and account-level reports

---

#### `currency`

**Type**: `string`
**Nullable**: No

Currency code (ISO 4217)

**Example**: `KRW`

**Note**: Currently only KRW supported

---

#### `counterparty`

**Type**: `string`
**Nullable**: Yes

Counterparty account for transfer transactions

**Example**: `우리은행`

**Note**: Used for transfer detection

---

#### `datetime`

**Type**: `datetime`
**Nullable**: No

Combined datetime for sorting and time-based matching

**Example**: `2025-07-23T08:33:00`

**Note**: Generated from date + time fields

---

#### `category_rule`

**Type**: `string`
**Nullable**: Yes

Category assigned by rules.yaml (single value for aggregation)

**Example**: `온라인쇼핑`

**Note**: Set by the highest-priority matching enabled rule that has a non-empty category

---

#### `category_final`

**Type**: `string`
**Nullable**: No

Final category for report aggregation (no duplicates)

**Example**: `온라인쇼핑`

**Note**: Manual category override wins; otherwise a single category value is used for spending reports

---

#### `tags_rule`

**Type**: `json_array`
**Nullable**: No

Attribute tags applied by all matching enabled rules

**Example**: `["정기지출", "해외결제"]`

**Note**: Rules are evaluated by priority; matching rule tags are deduplicated while preserving first-seen order

---

#### `tags_ai`

**Type**: `json_array`
**Nullable**: No

AI-generated tags (optional, Phase 2+)

**Example**: `["업무식대"]`

**Note**: Not yet implemented

---

#### `tags_manual`

**Type**: `json_array`
**Nullable**: No

User-added tags via review queue

**Example**: `["의료"]`

**Note**: Visible manual tags merge into tags_final; an internal marker may persist a category_final override

---

#### `tags_final`

**Type**: `json_array`
**Nullable**: No

Final merged attribute tag list (rule + AI + manual)

**Example**: `["정기지출", "해외결제", "의료"]`

**Note**: Merges rule tags, AI tags, and visible manual tags with stable deduplication; not used for spending aggregation

---

#### `confidence`

**Type**: `float` (range: [0.0, 1.0])
**Nullable**: Yes

Binary tagging coverage confidence, not model confidence

**Example**: `1.0`

**Note**: Currently 1.0 when tags_final is non-empty, otherwise 0.0; below 0.7 triggers needs_review

---

#### `needs_review`

**Type**: `integer` (enum: 0, 1)
**Nullable**: Yes

Flag derived from coverage confidence (1 when confidence < 0.7)

---

#### `is_transfer_candidate`

**Type**: `integer` (enum: 0, 1)
**Nullable**: Yes

Transfer-like candidate flag from raw transaction type (1=candidate, not necessarily excluded)

**Note**: Candidates without a confirmed pair remain reportable spend

---

#### `is_transfer`

**Type**: `integer` (enum: 0, 1)
**Nullable**: Yes

Confirmed internal transfer flag (1=confirmed paired transfer, excluded from expense reports)

---

#### `transfer_group_id`

**Type**: `string`
**Nullable**: Yes

Groups paired transfers (debit/credit)

**Example**: `transfer_20250723_152129`

**Note**: Same ID for both sides of a confirmed transfer; null for unconfirmed candidates

---

#### `file_id`

**Type**: `string`
**Nullable**: No

Compact source file identifier (YYMMDD_N or 8-char hash fallback)

**Example**: `241027_1`

**Pattern**: `^(?:\d{6}_\d+|[0-9a-f]{8})$`

**Note**: Dated Banksalad filenames use YYMMDD_N; non-standard filenames use SHA256[:8]. Sequence suffixes may grow beyond one digit.

---

#### `source_row`

**Type**: `integer`
**Nullable**: No

Row number in source XLSX file (1-indexed)

**Example**: `597`

**Note**: Enables traceability back to original import file

---

## Migration History

### Category System for Accurate Aggregation (v3)

**Issue**: #166
**Date**: N/A
**Author**: Claude Code

Add category_rule and category_final fields to eliminate duplicate counting in reports

**Changes**:

- **Add** `category_rule`: New nullable string field for rule-based category
  - Impact: +15 chars per row (average)
- **Add** `category_final`: Calculated category for aggregation (COALESCE chain)
  - Impact: +15 chars per row (average)
- **Add** `is_transfer_candidate`: Added nullable integer flag for transfer-like raw rows before pair confirmation
  - Impact: +2 chars per row (average)
- **Modify** `is_transfer`: Clarified as confirmed paired-transfer flag; report filters also require transfer_group_id
  - Impact: Legacy unpaired rows with is_transfer=1 and blank transfer_group_id are no longer excluded
- **Modify** `tags_final`: Role changed from aggregation to filtering only
  - Impact: No structural change

### CSV Metadata Optimization (v2)

**Issue**: #59
**Date**: 2025-11-03T20:45:30Z
**Author**: Claude Code

Reduced token consumption by 89% through hash truncation and file_id system

**Changes**:

- **Optimize** `row_hash`: Truncated from 64 chars (full SHA256 hex) to 16 chars
  - Impact: -54 chars per row
- **Add** `file_id`: Added compact identifier (YYMMDD_N for dated filenames, SHA256[:8] fallback for non-standard filenames)
  - Impact: +8 chars per row in the common case; longer when YYMMDD_N sequence suffix exceeds one digit
- **Remove** `source_file_path`: Removed ~80 char absolute file path
  - Impact: -80 chars per row
- **Remove** `source_file_mtime`: Removed 26-char ISO timestamp
  - Impact: -26 chars per row
- **Add_Metadata** `N/A`: Centralized file_id → import history tracking

**Results**:

- **Partitions Migrated**: 13
- **Rows Migrated**: 2269
- **Status**: completed
- **Net Savings**: 152 chars per row = 89% metadata reduction
- **Token Efficiency**: 40-50% overall improvement
- **File Id Registry Rows**: 1

## Schema Compatibility

### v4

- **Compatibility Status**: `active`
- **Migration Status**: Active read/write schema; older readable partitions are upgraded on write.
- **Can Read**: v2, v3, v4
- **Can Write**: v4
- **Migration Required**: No
- **Runtime Migration**: Run finjuice refresh to process existing partitions; transaction writers backfill notes_manual, category_rule/category_final, and is_transfer_candidate even if rules.yaml is missing and tagging is skipped.
- **Manual Migration**: No eager migration required; write paths persist v4 columns after normal mutations. scripts/migrate_schema_v3.py remains optional only for eager v2→v3 category rewrites.
- **Note**: v4 is backward compatible: runtime readers tolerate compatible older partitions, append/tag/transfer/write_month writes persist v4 columns, and notes_manual remains outside row_hash and aggregation.

**Breaking Changes from v3**:

- notes_manual field added (nullable string)

**Breaking Changes from v2**:

- category_rule field added (nullable string)
- category_final field added (calculated, not null)
- is_transfer_candidate field added (nullable integer)
- tags_final role changed (filtering only, not aggregation)

### v2

- **Compatibility Status**: `compatible-legacy`
- **Migration Status**: Readable by v3 as an inactive legacy schema; run finjuice refresh to rewrite partitions to v3 when convenient.
- **Can Read**: v2
- **Can Write**: v2
- **Migration Required**: Yes

**Breaking Changes from v1**:

- row_hash field length changed (64 → 16 chars)
- source_file_path removed (replaced by file_id)
- source_file_mtime removed (moved to import_history.csv)
- file_id field added (requires lookup in import_history.csv)

## Validation Rules

🔴 **row_hash must be exactly 16 lowercase hex characters**

- Field: `row_hash`
- Pattern: `^[0-9a-f]{16}$`
- Severity: `error`

🔴 **file_id must follow YYMMDD_N or 8-char lowercase hex hash fallback pattern**

- Field: `file_id`
- Pattern: `^(?:\d{6}_\d+|[0-9a-f]{8})$`
- Severity: `error`

🔴 **date must be valid ISO date**

- Field: `date`
- Severity: `error`

🔴 **type_norm must be one of: expense, income, transfer, other**

- Field: `type_norm`
- Allowed values: `expense`, `income`, `transfer`, `other`
- Severity: `error`

🔴 **tags fields must be valid JSON arrays**

- Fields: `tags_rule`, `tags_ai`, `tags_manual`, `tags_final`
- Severity: `error`

🔴 **transfer/review flags must be 0 or 1 (or null)**

- Fields: `is_transfer_candidate`, `is_transfer`, `needs_review`
- Allowed values: `0`, `1`, `None`
- Severity: `error`

⚠️ **confidence must be between 0.0 and 1.0**

- Field: `confidence`
- Range: [0.0, 1.0]
- Severity: `warning`

⚠️ **amount cannot be zero**

- Field: `amount`
- Severity: `warning`
- Note: Zero-amount transactions are unusual

🔴 **category_final must not be empty**

- Field: `category_final`
- Severity: `error`
- Note: category_final is required for report aggregation

⚠️ **category_rule should be single value (no comma/array)**

- Field: `category_rule`
- Pattern: `^[^,\[\]]*$`
- Severity: `warning`
- Note: category is for single-value aggregation, not multi-value like tags

---

## See Also

- [templates/schema.yaml](../../templates/schema.yaml) - Source of truth
- [rules-conditions.md](rules-conditions.md) - Conditional rule engine reference
- [CLAUDE.md](../../CLAUDE.md) - Project guide
- [Data Repository Setup](../setup/data-repository.md) - User data configuration

**Note**: This file is auto-generated. Do not edit manually. Run `make docs-schema` to regenerate.
