# Intake proposal revision and withdrawal

`finjuice ssot intake list --json` exposes the stored proposal digest, extraction,
uncertainties, confirmations, applications, parent lineage and successor IDs from
one repository snapshot. These are evidence for a decision, not automatic approval.

`ssot intake revise PROPOSAL_ID REQUEST.json` requires the current dataset generation,
revision and a new idempotency key through the existing mutation options. The request
contains `parent_payload_digest`, `proposal`, nonempty `evidence`, timezone-qualified
`revised_at`, explicit `uncertainties`, and `resolutions` mapping each removed uncertainty
to its explanation. Optional `extraction` records an explicit operator correction;
omitting it retains the original extraction. Original bytes are verified in the source
object store, so the original external file is not required.

Revision creates an immutable occurrence, extraction and proposal, and retires an
undecided parent in the same commit. The parent source, extraction, payload and any
application remain unchanged. Only one successor is allowed; revise that successor for
further changes. Retry with the original complete request returns the original receipt,
even after later revisions. Reusing its key with changed content fails.

An applied parent remains applied. Revisions retain their domain operation and target.
Binding, ownership and asset-meaning corrections must explicitly identify the current
typed head descended from the applied fact. Transaction overrides retain the actual
transaction identity; rule corrections retain the rule name. Applied observation amounts
cannot be rewritten through revision: use an explicit asset-meaning proposal for meaning
corrections; replacement numeric-source semantics remain unsupported.

`ssot intake withdraw PROPOSAL_ID REQUEST.json` takes `payload_digest`, nonempty
`evidence`, and timezone-qualified `rejected_at`, plus current mutation identity options.
It records a rejected confirmation for an undecided proposal. It cannot undo an applied
domain change. Both commands support human and JSON output. No schema version or separate
ledger is introduced; validated parent evidence and original source objects travel with
ordinary capture and restore.
