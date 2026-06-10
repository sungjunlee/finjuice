# Tagging And Review Terminology

Canonical terms for status, review, and rules JSON contracts:

| Term | Definition |
|------|------------|
| `untagged` | `tags_final` is null or an empty tag array. This includes transfer rows. |
| `uncategorized` | `category_final` is the fallback category `미분류`. This is independent from tag coverage. |
| `rule_matched` | A rule contributed output: `tags_rule` is non-empty or `category_rule` is non-empty. All matching enabled rules may contribute tags. |
| `confidence` | Current persisted tagging coverage confidence, not model confidence: `1.0` when `tags_final` is non-empty, otherwise `0.0`. |
| `needs_review` | The explicit row flag `needs_review == 1`; it follows `confidence < 0.7` and does not mean every row returned by `review`. |
| `suggestable_untagged` | An `untagged` row eligible for `rules suggest` after excluding confirmed internal transfer pairs (`is_transfer == 1` with `transfer_group_id`). |

Rule application semantics:

- Enabled rules are evaluated in priority order, highest first.
- All matching rules contribute `tags_rule`; duplicate tags are removed while preserving first-seen order.
- `category_rule` is the category from the highest-priority matching rule that has a non-empty category.
- `category_final` prefers a persisted manual category override, then `category_rule`, then `minor_raw`, then `major_raw`, then `미분류`.
- `tags_final` merges rule tags, AI tags, and visible manual tags with stable deduplication.

Affected JSON fields:

| Field | Term |
|-------|------|
| `status.tagging.untagged_count` | `untagged` |
| `status.tagging.suggestable_untagged_count` | `suggestable_untagged` |
| `status.tagging.transfer_excluded_untagged_count` | `untagged` rows excluded from `suggestable_untagged` |
| `status.terminology.reference` | Link to this terminology contract |
| `automation run.tagging_pressure.untagged_transactions` | `untagged` |
| `automation run.tagging_pressure.suggestable_untagged_transactions` | `suggestable_untagged` |
| `automation run.tagging_pressure.threshold_basis` | The automation `untagged_count` threshold is evaluated against `suggestable_untagged_transactions` |
| `automation run.tagging_pressure.transfer_excluded_untagged_transactions` | `untagged` rows excluded from suggestions |
| `rules suggest.untagged_count` | `untagged` |
| `rules suggest.suggestable_untagged_count` | `suggestable_untagged` |
| `rules suggest.transfer_exclusions.excluded_untagged_count` | `untagged` rows excluded from suggestions |
| `review.transactions[].rule_matched` | `rule_matched` |
| `review.transactions[].needs_review` | `needs_review` |
| `review.transactions[].reasons` | Machine-readable labels explaining why the row is in the review queue |
| `review.transactions[].severity` | Highest severity derived from the row's review reasons |
| `review.signals.untagged_count` | `untagged` |
| `review.signals.unclassified_count` | `uncategorized` |
| `review.signals.uncategorized_count` | `uncategorized` |
| `review.signals.needs_review_count` | `needs_review` |
| `review.signals.needs_review_flag_count` | `needs_review` |
| `review.signals.rule_matched_count` | `rule_matched` |
