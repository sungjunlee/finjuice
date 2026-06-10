# Mutation Testing Decision

Issue #632 keeps mutation testing out of the normal CI path for now.

The current cost/benefit does not justify adding tools such as `mutmut`,
`cosmic-ray`, or a randomized property-test dependency. finjuice already runs
coverage, ruff, mypy, and a complexity ratchet, and most critical behavior
depends on filesystem-backed CSV partitions and CLI flows. A full mutation run
would add another slow dependency and make the solo-dev feedback loop heavier.

Instead, critical finance data invariants should be hardened with deterministic
table-driven/property-style tests:

- Pagination must cover each row exactly once across pages.
- Review queues must use stable tie-breakers for equal sort keys.
- Partition append/read behavior must stay idempotent across month boundaries.

Revisit mutation testing only if it can run outside the normal fast path, such
as a manual or scheduled job with a narrow target module list and an explicit
time budget.
