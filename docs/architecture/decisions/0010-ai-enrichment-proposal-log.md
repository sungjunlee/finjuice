# 10. AI Enrichment Proposal Log

Date: 2026-05-12

## Status

Accepted

## Context

finjuice already reserves `tags_ai` in the transaction schema, but runtime AI
enrichment is not implemented. The unsafe path would be to let an LLM or an
agent silently rewrite transaction CSV partitions and populate `tags_ai` as part
of proposal generation. That would make financial data hard to audit and would
blur the boundary between AI suggestions and user-approved data changes.

Issue #602 defines the safety contract before any implementation that writes
`tags_ai`: AI enrichment must be proposal-first, local-first, append-only, and
explicitly approved before it can affect transaction partitions.

## Decision

Use an append-only proposal log under the user data directory:

```text
metadata/enrichments/YYYY/MM/proposals.jsonl
```

Each line is a JSONL event. Proposal generation appends `proposal.created`
events only. Review and apply steps append later state events for the same
`proposal_id`; they do not edit earlier records. A future reader derives the
current state by replaying events for a proposal.

Proposal generation never mutates transaction CSV partitions and never silently
populates `tags_ai`. Applying a proposal is a separate explicit user-approved
action. A future apply implementation may update `tags_ai` only after the latest
proposal state is approved. It may append an approval event before the write,
but it must append `proposal.applied` only after the transaction partition
rewrite succeeds. The apply step must not call an LLM.

Safety contract:

- Proposal generation never mutates transaction CSV partitions.
- Proposal generation never silently populates `tags_ai`.
- Applying a proposal is an explicit user-approved action.
- The design forbids direct LLM writes to `tags_ai`.

The proposal record shape is stable enough for future implementation, but this
ADR does not add runtime enrichment commands.

Minimum `proposal.created` fields are `row_hash`, `proposed_category`,
`proposed_tags`, `rationale`, `confidence`, `model`, `provider`,
`prompt_version`, `prompt_input_digest`, `approval_state`, `applied_state`, and
`created_at`. Implementations may add provenance fields when they are safe, but
they must not remove these fields from newly written proposal records.

```json
{
  "event": "proposal.created",
  "proposal_id": "sha256:...",
  "row_hash": "ac875c7391d4e2f8",
  "proposed_category": "food",
  "proposed_tags": ["cafe"],
  "rationale": "Short sanitized reason based on safe local summaries.",
  "confidence": 0.82,
  "model": "gpt-example",
  "provider": "openai",
  "prompt_version": "ai-enrichment-v1",
  "prompt_input_digest": "sha256:...",
  "safe_summary": {
    "month": "2026-05",
    "direction": "expense",
    "amount_bucket": "10000-49999",
    "existing_category": "uncategorized"
  },
  "approval_state": "pending",
  "applied_state": "not_applied",
  "created_at": "2026-05-12T00:00:00Z"
}
```

State events use the same `proposal_id` and `row_hash` and append a new state:

```json
{
  "event": "proposal.approved",
  "proposal_id": "sha256:...",
  "row_hash": "ac875c7391d4e2f8",
  "approval_state": "approved",
  "approved_at": "2026-05-12T00:05:00Z",
  "approved_by": "local-user"
}
```

```json
{
  "event": "proposal.applied",
  "proposal_id": "sha256:...",
  "row_hash": "ac875c7391d4e2f8",
  "applied_state": "applied",
  "applied_at": "2026-05-12T00:06:00Z",
  "applied_fields": ["tags_ai"]
}
```

Rejected, skipped, stale, or superseded proposals use the same append-only event
pattern. A proposal is stale if `row_hash` no longer resolves to exactly one
current transaction. Stale proposals must not be applied silently.

## Privacy Contract

Proposal logs are local-first artifacts. They stay under the user's data
directory and must not be uploaded or synchronized by finjuice.

Proposal logs must contain no raw transaction rows, no account numbers, no
sensitive free text, no raw memo values, and no unnecessary merchant,
counterparty, file path, or import-source details. Future implementations should
use `row_hash`, prompt digests, coarse safe summaries, and model provenance
instead of copying private transaction fields into the log.

The shorthand privacy rule is: no raw transaction rows, no account numbers, and
no sensitive free text.

Rationale text must be short and sanitized. If a future reviewer needs full
transaction detail, it should resolve `row_hash` against the local CSV
partitions at review time instead of storing the details in the proposal log.

## Apply Flow

1. Generate proposals from safe local summaries and append `proposal.created`
   records to `metadata/enrichments/`.
2. Review proposals against live local data by resolving `row_hash`. The review
   step may append approved, rejected, or skipped state events.
3. Apply only approved proposals through an explicit user-approved action. The
   apply step performs the smallest needed transaction partition rewrite first,
   then appends `proposal.applied` only after that rewrite succeeds.
4. Verify by replaying the proposal log and checking the current CSV row for the
   same `row_hash`.

If the partition rewrite fails, the implementation must not append
`proposal.applied`; replaying the append-only log must continue to show the
proposal as approved but not applied. A future implementation may append a
sanitized `proposal.apply_failed` event for auditability, but failure metadata
must not contain raw transaction details and must not be treated as an applied
state.

This flow rules out direct LLM writes to `tags_ai`. AI systems may propose;
local deterministic code may apply after approval.

## Non-goals

This ADR does not implement schema v4, MCP/server, dashboard, materialized
cache, LLM calls inside finjuice CLI, direct LLM writes to `tags_ai`, or a public
Python API facade.

Out of scope: schema v4, MCP/server, dashboard, materialized cache, LLM calls
inside finjuice CLI, public Python API facade.

This ADR also does not define a production command name. Any future command must
preserve the proposal-first contract and add focused tests before it can write
`tags_ai`.

## Consequences

- AI suggestions become auditable without turning transaction partitions into
  an implicit LLM output surface.
- The append-only log gives future tooling a durable approval trail and avoids
  hidden state rewrites.
- Future apply code must handle stale proposals and partition rewrites
  carefully, but that complexity is isolated from proposal generation.
- `proposed_category` is recorded for review context, but writing category
  output to transaction partitions requires a separate schema decision if the
  current schema cannot represent it safely.

## Confirmation

`tests/test_doc_consistency.py` contains a focused consistency check that keeps
this ADR linked from the architecture decision index and locks the core
proposal-first safety contract.
