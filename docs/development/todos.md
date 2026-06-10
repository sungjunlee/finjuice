# TODOS

Cross-cutting work surfaced during reviews but deferred from active sprints.

---

## 2026-05-20

### Batch 3 destination of `show_command` (Sprint 2026-05-maintainability-refactors)

**What**: When splitting `cli/commands/init.py` (#700/#701), `show_command` needs
a new home. It's currently bundled with `init`/`migrate`/`history` despite being a
different concern.

**Options**:
- A. New `cli/commands/show_cmd.py` (parallel sibling).
- B. Fold into existing `cli/commands/query.py` family (read-only data inspection).
- C. Promote to top-level `commands/show/` package with its own use case layer.

**Decision dependency**: blocks Batch 3 of `2026-05-maintainability-refactors`
sprint; Batches 1 (tagging model) and 2 (storage split) can proceed without
this decision.

**Surfaced from**: code-explorer architecture map on 2026-05-20.
