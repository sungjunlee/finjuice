---
name: finjuice-rule-cleanup
description: |
  Tagging taxonomy maintenance session for finjuice. Audits rule validity,
  overlap, and stale merchant coverage, investigates candidates with `finjuice explain`,
  and guides the user through cleanup decisions one at a time without batch prompting.
  Trigger when user says 규칙 정비, 룰 정리, 중복 규칙 정리, rule cleanup,
  taxonomy cleanup, or tagging maintenance.
argument-hint: "[merchant, rule name, or cleanup focus]"
compatibility: "Requires finjuice CLI runtime; resolve and run the shared runtime ensure helper before running `finjuice`."
---

# Finjuice Rule Cleanup

## Side Effects

- Modes: `read-only`, `mutating-with-confirmation`, `journal-writing`, `runtime-install/update`
- Reads context, rules, validation output, gaps, suggestions, explain traces, and transaction examples.
- Rule additions/removals and re-tagging mutate `rules.yaml` and tagged transaction state only after preview and explicit user confirmation.
- Writes a retrospective journal only when the session produced durable cleanup decisions.
- Runtime ensure may install a missing runtime or update runtime state only under the shared runtime policy.

## Runtime Requirements

- Minimum finjuice: `0.6.2`
- Capabilities: `index`, `checkup`, `context`, `rules validate`, `rules gaps`, `rules suggest`, `rules test`, `rules add`, `rules remove`, `explain`, `show`, `journal`
- Unsupported fallback: Unsupported CLI path: `<cli path>`. Confidence lost for this workflow because the local finjuice runtime lacks required capability `<capability>`. Do not recommend or run the failed command after preflight failure.

Run a rule-maintenance session focused on taxonomy quality, not just coverage growth. Follow the `finjuice-curate` convention: one decision at a time, never batch multiple cleanup questions together.

## Runtime Preflight

Before running any `finjuice ...` command, load the shared procedure in
`skills/finjuice/references/runtime-preflight.md` to resolve `FINJUICE_ENSURE`, then
run this skill-local gate:

```bash
"$FINJUICE_ENSURE" --json \
  --require-version 0.6.2 \
  --require-command "index" \
  --require-command "checkup" \
  --require-command "context" \
  --require-command "rules validate" \
  --require-command "rules gaps" \
  --require-command "rules suggest" \
  --require-command "rules test" \
  --require-command "rules add" \
  --require-command "rules remove" \
  --require-command "explain" \
  --require-command "show" \
  --require-command "journal new"
```

If the JSON response has `status: "blocked"`, stop and report its `message`; do not
install `uv` automatically or continue to finjuice commands.

Side-effect mode: mutating-with-confirmation plus optional journal-writing. Follow
[../finjuice/references/rule-decision-protocol.md](../finjuice/references/rule-decision-protocol.md)
for preview, confirmation, and verification. Write a retrospective journal only when
the session produced durable taxonomy decisions.

## Final Response Contract

Follow [../finjuice/references/final-response-contract.md](../finjuice/references/final-response-contract.md)
and finish Korean-first. Include these fields in the final answer:

- `evidence_commands`: list `context`, `rules validate`, `rules gaps`, `rules suggest`,
  `rules test`, `rules add/remove`, `explain`, `show`, `tag`, and `status` commands used.
- `mutations_applied`: rule additions/removals, re-tagging, journal write, or `없음`;
  include only user-confirmed mutations.
- `files_written`: retrospective journal path, exported evidence if requested, or `없음`.
- `skipped_steps`: skipped cleanup candidates, skipped journal persistence, skipped
  validation/re-tagging, or skipped ambiguous decisions with the reason.
- `residual_risk`: remaining validator warnings, unresolved overlaps, stale merchant
  evidence, low coverage, or categories that need a future decision.
- `next_suggested_action`: one concrete next action such as rerun validation, run curation,
  review remaining gaps, or schedule the next taxonomy cleanup.

## Phase 0 — LOAD PRIORITY CONTEXT

Load [../finjuice/references/discovery-guide.md](../finjuice/references/discovery-guide.md).
Run `finjuice index --json --privacy compact`, then
`finjuice checkup --json --privacy compact` to confirm rule/transaction collections
and current health before taxonomy-specific reads.

Run `finjuice context --json`.
- Parse active goals, top patterns, and any recent journal themes that should affect cleanup priorities.
- Use this context only to prioritize. The core evidence still comes from the rules commands.

## Phase 1 — AUDIT THE RULE SET

Run these in parallel:
- `finjuice rules validate --json`
- `finjuice rules gaps --json`
- `finjuice rules suggest --top 30 --json`

Build a cleanup queue from:
- Validation failures or warnings.
- Large untagged merchants or mismatch clusters from `rules gaps`.
- Suggestion rows that imply stale, duplicate, or overly broad existing rules.

## Phase 2 — INVESTIGATE CANDIDATES

For each candidate merchant or rule cluster, investigate before proposing a cleanup action.

Use:
- `finjuice explain "<merchant>" --json`
- `finjuice show --json --merchant "<merchant>" --limit 20` when you need concrete row samples.
- `finjuice rules test <rule_name> --json` when a specific rule needs dry-run evidence.

Look for:
- Stale rules: old merchant patterns no longer matching the current merchant string variants.
- Duplicate rules: multiple rule names producing the same outcome for the same merchant family.
- Overly broad rules: one regex swallowing unrelated merchants or setting the wrong category.
- Priority problems: a broad rule firing before a more specific rule.

## Phase 3 — CLEAN UP ONE DECISION AT A TIME

Present one candidate at a time. Stop after each decision and wait for the user's answer.

Use this decision frame:

```text
🧹 [N/total] 규칙 후보: [rule or merchant]

증거:
- validate: [warning or pass]
- gaps/suggest: [impact]
- explain: [matched rule / wrong category / no match]

선택지:
1. 기존 규칙 수정 (`finjuice rules add --name ...`)
2. 규칙 분리 또는 우선순위 조정 (`finjuice rules add --name ... --priority ...`)
3. 중복 규칙 제거 (`finjuice rules remove --name ... --json`)
4. 이번에는 유지
5. 더 조사하기
```

Conversation rules:
1. Stay on the same candidate until the user explicitly decides.
2. If the user asks "왜?", "근거 보여줘", or "더 자세히", run another `finjuice explain "<merchant>" --json` or `finjuice show --json --merchant "<merchant>" --limit 20` and re-present the options.
3. Never ask about multiple merchants or multiple rules in a single prompt.

## Phase 4 — VERIFY NO REGRESSIONS

After each applied change, or at minimum after the final change set:
- Run `finjuice rules validate --json` again.
- If a changed rule needs spot-checking, run `finjuice rules test <rule_name> --json`.
- Summarize whether warnings improved, stayed the same, or got worse.

Do not end the session with a broken validation state.

## Phase 5 — OPTIONAL RETROSPECTIVE

If the session produced meaningful taxonomy decisions:
- Run `finjuice journal new --topic rule-cleanup --template retrospective`.
- Run `finjuice journal resume rule-cleanup` to resolve the created file path.
- Capture:
  - `# 규칙 정비 회고`
  - `## 변경한 규칙`
  - `## 제거한 규칙`
  - `## 남은 리스크`

If the session was only exploratory, skip journal creation and say so explicitly.
