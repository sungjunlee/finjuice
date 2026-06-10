# Rule Decision Protocol

Use this shared protocol in rule-writing skills such as `finjuice-curate` and
`finjuice-rule-cleanup`.

## Default Posture

- Inspect first with `rules suggest`, `rules gaps`, `rules validate`, `rules test`, `show`, or `explain`.
- Preview rule writes with `--dry-run` before changing `rules.yaml`.
- Ask for user confirmation before applying any rule, removing any rule, or re-tagging after a rule change.
- Apply without another prompt only when the user explicitly says to automate the remaining decisions.
- Never edit transaction or asset CSV partitions directly from a rule workflow.

## Decision Loop

1. Present one merchant, rule, or rule cluster.
2. Show the evidence: counts, amount impact, current match path, and dry-run result.
3. Offer a default recommendation plus skip and investigate options.
4. Stop and wait for the user's decision.
5. Apply the confirmed change.
6. Re-run the smallest useful verification command.

## External Merchant Lookup Privacy

Use local evidence first. Before any web search or external merchant lookup, perform
local transaction pattern analysis with finjuice commands such as `finjuice query --json`,
`finjuice explain`, `finjuice rules suggest`, or `finjuice show`.

External lookup is allowed only when local evidence cannot identify the merchant and one
of these conditions is true:
- The user explicitly confirms the external lookup after seeing what will be searched.
- The search query is redacted/generalized so it does not reveal personal spending
  context.

Do not send private financial context to external search. This includes raw merchant strings
when they reveal personal context, transaction amounts, dates, account names, memo text, raw
transaction rows, local file paths, or unique combinations of financial details. Prefer
generalized searches such as a brand or service category instead of a full statement descriptor.
Never send raw transaction rows externally.

## Verification

- After rule additions or updates: run `finjuice tag --json`, then `finjuice status --json`.
- After rule removal or priority changes: run `finjuice rules validate --json`.
- For risky patterns: run `finjuice rules test <rule_name> --json`.
- If verification worsens coverage or validation, show the regression and ask before continuing.
