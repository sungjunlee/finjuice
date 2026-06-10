---
name: finjuice-curate
description: |
  Interactive rule curation for finjuice. Fetches untagged merchant suggestions,
  previews clear ones before applying, asks the user about ambiguous ones one at a time,
  and tracks coverage improvement throughout.
  Trigger when user says 태그 정리, 커버리지 올려줘, 규칙 추가해줘, rule curation,
  태깅 개선, or 미분류 정리.
argument-hint: "[target coverage % or merchant name]"
compatibility: "Requires finjuice CLI runtime; resolve and run the shared runtime ensure helper before running `finjuice`."
---

# Finjuice Curate

## Side Effects

- Modes: `read-only`, `mutating-with-confirmation`, `runtime-install/update`
- Reads status, rules, coverage, suggestions, explain traces, and untagged transactions.
- Rule additions/removals and follow-up `tag --json` runs mutate `rules.yaml` and tagged transaction state only after dry-run preview and explicit user confirmation.
- Runtime ensure may install a missing runtime or update runtime state only under the shared runtime policy.

## Runtime Requirements

- Minimum finjuice: `0.6.2`
- Capabilities: `index`, `checkup`, `rules suggest`, `rules add`, `status`, `tag`, `query`, `explain`, `export`
- Extras: `analytics` (`duckdb`)
- Unsupported fallback: Unsupported CLI path: `<cli path>`. Confidence lost for this workflow because the local finjuice runtime lacks required capability `<capability>`. Do not recommend or run the failed command after preflight failure.

Interactive rule curation workflow. Prepare clear proposals in a batch, ask the user about
ambiguous ones one at a time. Questions ONE AT A TIME — never batch ambiguous decisions.

## Runtime Preflight

Before running any `finjuice ...` command, load the shared procedure in
`skills/finjuice/references/runtime-preflight.md` to resolve `FINJUICE_ENSURE`, then
run this skill-local gate:

```bash
"$FINJUICE_ENSURE" --json \
  --require-version 0.6.2 \
  --require-command "index" \
  --require-command "checkup" \
  --require-command "rules suggest" \
  --require-command "rules add" \
  --require-command "status" \
  --require-command "tag" \
  --require-command "query" \
  --require-command "explain" \
  --require-command "export" \
  --require-extra analytics
```

If the JSON response has `status: "blocked"`, stop and report its `message`; do not
install `uv` automatically or continue to finjuice commands.

Rule writes are preview-first. Follow the shared decision protocol in
[../finjuice/references/rule-decision-protocol.md](../finjuice/references/rule-decision-protocol.md):
classify candidates, preview the rule impact, ask for confirmation, then apply.

## Final Response Contract

Follow [../finjuice/references/final-response-contract.md](../finjuice/references/final-response-contract.md)
and finish Korean-first. Include these fields in the final answer:

- `evidence_commands`: list `rules suggest`, `rules add --dry-run`, `rules add`,
  `tag`, `status`, `query`, `explain`, or `export` commands used.
- `mutations_applied`: applied rules, final `tag --json`, transfer/category decisions, or
  `없음`; separate automatic and user-decided changes when possible.
- `files_written`: `없음` unless the user explicitly requested export/report artifacts.
- `skipped_steps`: skipped merchants, skipped ambiguous questions, skipped final retag,
  or skipped export/report work with the reason.
- `residual_risk`: remaining untagged count, unresolved ambiguous merchants, low coverage,
  or rules that still need validation.
- `next_suggested_action`: one concrete next action such as rerun with a larger `--top`,
  run `rules gaps`, start review, or generate a report.

## Phase 1 — ASSESS

Load [../finjuice/references/discovery-guide.md](../finjuice/references/discovery-guide.md).
Run `finjuice index --json --privacy compact` first to confirm transactions and rules
collections exist, then `finjuice checkup --json --privacy compact` for current health.
After discovery, run `finjuice rules suggest --json --top 30` and `finjuice status --json`.
- Parse `coverage_before_pct`, `untagged_count`, `total_count`.
- Parse each suggestion's `merchant`, `pattern`, `transaction_count`, `total_amount`, `banksalad_category`, `similar_merchants`, `is_recurring`, `time_patterns`, `merchant_kind`, `ambiguous_reason`, `default_action`, `auto_apply_eligible`, and `suggested_rule`.
- If the user asked for "새로 들어온 건", "이번 import", or named an import ID, prefer `finjuice rules suggest --json --top 30 --file-id FILE_ID`.
- Maintain a session-local `skipped_merchants` set of `{merchant, reason}`. Do not ask about a merchant again in the same run after the user says skip, next, no rule, 규칙 만들지 않음, or similar.

Set a target: if the user specified a target coverage, use that. Otherwise default to 80%.

Show the starting point:
```
📊 현재 커버리지: XX.X% (미분류 XX건/XX건)
🎯 목표: XX%
📋 분석할 가맹점: XX곳
```

## Phase 2 — CLASSIFY

For each suggestion, classify it into one of two buckets:

### Clear (preview as a batch)

A suggestion is clear when ALL of these hold:
- The Banksalad category (`banksalad_category.major` / `.minor`) makes semantic sense for the merchant name.
- The merchant name itself is unambiguous (e.g., "파리바게뜨" is clearly a bakery/cafe).
- There is no mismatch between what the merchant sells and the Banksalad category (e.g., "UMS수수료" categorized as "식비" is a mismatch).
- The `suggested_rule` category and tags are reasonable as-is or need only minor refinement (e.g., "생활" → "편의점" for GS25).

When auto-applying, you MAY override the `suggested_rule` values:
- Override `category` when you can be more specific (e.g., GS25: "생활" → "편의점", 리디: "온라인쇼핑" → "구독").
- Override `tags` to add useful attributes (e.g., add "정기지출" for recurring merchants).
- Merge similar merchants into one rule with `|` pattern (e.g., "투썸플레이스 판교봇들마을점|투썸플레이스판교테크노밸리점" → single rule).

### Ambiguous (ask user)

A suggestion is ambiguous when ANY of these hold:
- The Banksalad category is clearly wrong (e.g., "정보보호서비스" → "카페/간식").
- The merchant name is a PG company or intermediary (e.g., "엔에이치엔케이씨피", "NHNKCP") where the actual purchase is unknown.
- The suggestion has `merchant_kind: "payment_gateway"`, `ambiguous_reason: "payment_gateway"`, `default_action: "skip_rule"`, or `auto_apply_eligible: false`.
- The merchant could be personal or business (e.g., "LG CNSPay" could be employee benefit or personal purchase).
- The transaction could be an internal transfer (e.g., "송금 내역", "가족계").
- Multiple valid categories exist (e.g., "부모님용돈" could be "가족", "경조/선물", or even internal transfer).

## Phase 3 — PREVIEW CLEAR RULES

Build clear-rule proposals, but do not write them yet. Preview each proposal with:
```bash
finjuice rules add --dry-run --name NAME --match PATTERN --category CAT --tags TAG1,TAG2 --json
```

If using the CLI-generated `suggested_rule` values as-is for the whole batch, you may use:
```bash
finjuice rules suggest --apply --dry-run --json --top N
```
Do not include suggestions whose `default_action` is `skip_rule` or whose `auto_apply_eligible`
is false in the clear-rule batch. Treat them as "visible but no broad rule by default".

Present a summary to the user before any write:
```
📝 자동 적용 후보 미리보기 (XX건)

• GS25 판교 → 편의점 [편의점] (24건, dry-run 영향 확인)
• 투썸플레이스 → 카페/간식 [카페] (7건, dry-run 영향 확인)
• 파리바게뜨 → 카페/간식 [카페, 베이커리] (11건, dry-run 영향 확인)
• ...

이 clear 후보들을 적용할까요? (전체/선택/건너뛰기)
```

Stop and wait for the user's confirmation. Only after confirmation, apply selected rules:
```bash
finjuice rules add --name NAME --match PATTERN --category CAT --tags TAG1,TAG2 --json
```

After confirmed writes, run `finjuice tag --json` once, then `finjuice status --json`.

Present a summary to the user:
```
✅ 자동 적용 완료 (XX건)

• GS25 판교 → 편의점 [편의점] (24건)
• 투썸플레이스 → 카페/간식 [카페] (7건)
• 파리바게뜨 → 카페/간식 [카페, 베이커리] (11건)
• ...

커버리지: XX.X% → XX.X% (+X.X%)
```

## Phase 4 — ASK ABOUT AMBIGUOUS RULES

For each ambiguous suggestion, ask the user ONE AT A TIME. Group similar merchants together when appropriate (e.g., multiple AI SaaS subscriptions as one question with a shared default).

### Presenting a question

```
❓ [N/total] 가맹점: [merchant_raw]
   거래: XX건, 총 ₩XXX,XXX (월평균 ₩XX,XXX)
   뱅크샐러드 분류: [major] > [minor]
   패턴: [recurring/one-time], [weekday/weekend]

   선택지:
   1. [suggested category] + [suggested tags] (뱅크샐러드 분류 기반)
   2. [alternative category] + [alternative tags] (내 판단)
   3. 내부이체로 처리 (is_transfer=1)
   4. 규칙 만들지 않음 / 건너뛰기 (이번 세션에서 다시 묻지 않음)
   5. 직접 입력 (카테고리: __, 태그: __)
   6. 좀 더 알아봐 (거래 내역 상세 조회)
```

`규칙 만들지 않음` is a valid and often preferred decision, not a failure. Use it when
the merchant is a PG/intermediary, the real vendor cannot be identified from row-level
evidence, the merchant is too broad, or the user wants to handle the row with
`tag --edit --set-note`, event tagging, or no rule. For PG/intermediary candidates,
present option 4 as the recommended default unless local row evidence identifies a
single actual vendor.

### Conversation loop (critical)

The user may NOT pick a number. They may ask a question, challenge a premise, or say something like "이게 뭐야?", "좀 이상한데?", "진짜 구독 맞아?", or "더 자세히 알려줘".

When this happens:
1. **Stay on this item.** Do NOT move to the next merchant.
2. **Investigate** using the tools available:
   - `finjuice query --json "SELECT date, amount, account, memo_raw FROM transactions WHERE merchant_raw LIKE '%...' ORDER BY date"` for payment patterns
   - `finjuice explain "merchant" --json` for rule trace
   - External lookup only after the privacy guardrail below is satisfied
3. **Share findings** concisely, then re-present options — revised if the investigation changed the picture.
4. **Repeat** until the user makes an explicit decision (picks a number, says "그걸로 해", or gives custom input).

Only advance to the next merchant after the user has explicitly decided or said "건너뛰기" / "다음".

### After each decision

- If 1-2: apply with `finjuice rules add --name NAME --match PATTERN --category CAT --tags TAGS --json`.
- If 3: apply a rule with `category: "이체"` and `tags: ["내부이체"]`.
- If 4: add `{merchant, reason}` to `skipped_merchants`, do not create a rule, and move to the next suggestion without asking this merchant again in the same run.
- If 5: use the user's custom input.

Show running progress:
```
[N/total] 완료 — 커버리지: XX.X%
```

## Phase 5 — FINALIZE

Run `finjuice tag --json` for a final re-tag, then `finjuice status --json`.

Present the final report:
```
🎯 규칙 큐레이션 완료

시작: XX.X% (미분류 XXX건)
완료: XX.X% (미분류 XX건)
적용된 규칙: XX건 (자동 XX건 + 수동 XX건)
건너뛴 가맹점: XX건

다음 단계:
• sibling skill `finjuice-review`로 주간 리뷰 실행(available); otherwise follow `../finjuice-review/SKILL.md` inline
• finjuice export --format html 로 리포트 생성
```

If coverage is still below target, note the remaining gap and suggest rerunning this
`finjuice-curate` workflow with a larger `--top 50` scope, or checking
`finjuice rules gaps --json` for structural issues.

## Operational Rules

- Questions ONE AT A TIME. Never batch multiple merchant questions — but DO group similar merchants into one question when they share a clear pattern (e.g., 4 AI SaaS tools → one question with shared default).
- Keep `skipped_merchants` in memory throughout the run. Before presenting any suggestion, check it against that set and silently advance if already skipped; include all skipped merchants and reasons in the final answer.
- Make "규칙 만들지 않음 / skip rule" visible whenever a candidate is ambiguous. For PG/intermediary candidates, make it the recommended default.
- STOP after each question. Wait for the user's response before proceeding.
- Preview clear-rule writes with `--dry-run` and ask before applying them.
- **Never rush a decision.** If the user asks a follow-up question instead of picking an option, investigate and continue the conversation on that item. Do not advance to the next item until the user explicitly decides.
- Show running coverage after each applied rule so the user sees progress.
- If the user says "나머지 다 자동으로" or "auto", apply remaining suggestions using their `suggested_rule` values without further questions after showing the current dry-run summary.
- If the user says "그만" or "stop", finalize immediately with current progress.
- Merge similar merchant variants into single rules when the pattern is obvious (e.g., different branch names of the same chain).
- When investigating a merchant, follow the External Merchant Lookup Privacy guardrail in
  [../finjuice/references/rule-decision-protocol.md](../finjuice/references/rule-decision-protocol.md).
  Prefer local transaction pattern analysis with `finjuice query` and `finjuice explain`
  before web search or external merchant lookup.
- External lookup is allowed only after user confirmation or with a redacted/generalized
  query. Do not send raw merchant strings when they reveal personal context, transaction
  amounts, dates, account names, memo text, raw transaction rows, local file paths, or
  unique combinations of financial details to external search. In short: transaction
  amounts and other row details stay local.
  Never send transaction amounts externally.
