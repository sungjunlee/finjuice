# 8. Financial Metadata Notes Path

Date: 2026-05-05

## Status

Accepted

## Context

finjuice needs a place for stable user-confirmed financial context, such as
family constraints, housing, recurring savings, and large obligations. It also
needs notes that explain tagging decisions without creating transaction-level
metadata churn or making tag reruns unstable.

## Decision

Use `goals.yaml` for stable financial context:

- `financial_context` stores high-level income, family/dependent, and housing
  context.
- `known_obligations` stores confirmed large obligations and loans.
- Optional `notes`, `source`, `date`, and `as_of` fields are allowed inside those
  user-confirmed metadata blocks.

For tagging rationale, use the existing rule-level `rules.yaml` `notes` field as
the first metadata notes path. `finjuice context --json`, `finjuice checkup
--json`, and `finjuice review --json` may surface concise rule-note summaries,
but transaction CSV partitions do not gain a transaction-level notes field for
this purpose.

## Consequences

- Tag reruns stay idempotent because rule notes do not alter transaction schema
  or write per-row hidden metadata.
- Context surfaces can explain rule intent and stable financial constraints
  without exposing raw memos, account numbers, or private transaction rows.
- If finer-grained notes are needed later, they should be introduced through an
  explicit design that separates user-authored private notes from pipeline
  classification output.
