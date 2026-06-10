# Rules Format

Use this guide when editing `rules.yaml` directly.

## File Location And Discovery

- The rules file is resolved from the active data directory as `<data-dir>/rules.yaml`.
- Data directory resolution order is: CLI `--data-dir`, `FINJUICE_DATA_DIR`, saved config, then the OS default.
- Confirm the actual path with `finjuice status --json` and read `rules_file.path`.

## Rule Structure

Each rule is a YAML object with these common fields:

```yaml
- name: cafe_starbucks
  match: "스타벅스|STARBUCKS"
  fields: [merchant_raw]
  tags: ["카페", "커피"]
  category: "카페"
  priority: 80
```

- `name`: unique identifier used for validation and debugging.
- `match`: Python-style regex pattern.
- `fields`: transaction fields to search, usually `merchant_raw`, `memo_raw`, `major_raw`, or `minor_raw`.
- `tags`: attribute tags to merge into `tags_final`.
- `category`: optional single aggregation category written to `category_rule`.
- `priority`: integer sort key for evaluation order.

## Match Pattern Syntax

- Use regex alternation with `|` for spelling variants: `"투썸플레이스|투썸|TWOSOME"`.
- Escape regex metacharacters when matching literal punctuation: `"\\(주\\)카카오"`.
- Prefer targeted patterns over broad `.*...*` catch-alls to reduce false positives.
- Match can be applied to multiple fields when one source column is not enough.

## Priority Semantics

- Rules are evaluated in descending `priority` order.
- Higher numbers run first.
- First match wins for category assignment.
- Use wider priority gaps when a specific rule must beat a broad fallback.
- Typical pattern: memo-based intent at the top, specific merchants next, general category fallbacks below.

## Category vs Tags

- `category_rule` is a single value from the rule and feeds report aggregation.
- `category_final` is calculated as `category_rule -> minor_raw -> major_raw -> "미분류"`.
- `tags_rule` stores rule tags, and `tags_final` stores the merged tag list.
- `tags_final` is for filtering and analysis, not aggregation.
- If a rule adds only `tags` and no `category`, reports still aggregate on `category_final`.

## Example Rules

Specific merchant rule:

```yaml
- name: cafe_twosome
  match: "투썸플레이스|투썸|TWOSOME"
  fields: [merchant_raw]
  tags: ["카페", "커피"]
  category: "카페"
  priority: 80
```

Memo-based high-priority rule:

```yaml
- name: subscription_memo
  match: "구독|멤버십|정기결제"
  fields: [memo_raw]
  tags: ["구독", "정기지출"]
  category: "구독"
  priority: 95
```

Broad fallback rule:

```yaml
- name: service_kakao
  match: "카카오|KAKAO"
  fields: [merchant_raw]
  tags: ["디지털서비스", "카카오"]
  category: "디지털서비스"
  priority: 70
```

## Validation Workflow

- Run `finjuice rules validate --json` after every edit.
- Run `finjuice rules suggest --json` to find high-impact missing merchants before adding rules by hand.
- Run `finjuice rules gaps --json` when tags and Banksalad categories disagree.
- Re-run `finjuice tag --json` after changing rules to refresh coverage stats.
