# CLI as Structured Data API for AI Agents

**Status**: accepted
**Date**: 2026-04-05
**Reviewed**: Eng review (CLEAR) + Codex outside voice (3 tension points resolved)

## Context and Problem Statement

finjuice started as a human-first CLI that later added `--json` flags for AI agent consumption. The result is a split identity: 28 commands, 36 report types, and analysis features that duplicate what AI agents already do better. Meanwhile, the primitives AI agents actually need (selective rule management, rich transaction context, clean data access) are missing or incomplete.

The question: should finjuice be a CLI tool that does analysis, or a structured data API that lets AI agents do the analysis?

## Decision Drivers

* AI agents (Claude Code, Codex, etc.) are the primary consumers via the published skill
* AI agents are better at analysis, pattern recognition, and natural language — finjuice shouldn't compete
* The SSOT (CSV partitions + rules.yaml) is well-designed and should be the foundation
* Solo dev: surface area must be minimal to maintain
* Other users will interact through AI agents, not the CLI directly

## Considered Options

* **Option A**: Keep current structure, fix bugs incrementally
* **Option B**: CLI as Data API — provide data primitives, let AI agents do analysis
* **Option C**: Full MCP server — replace CLI with tool-use protocol

## Decision Outcome

Chosen option: **Option B — CLI as Data API**, because it preserves the working pipeline infrastructure while removing the analysis layer that AI agents do better. Option C is premature (MCP protocol still evolving) but Option B naturally leads there.

### CLI Surface Redesign

**Keep (data primitives)**:

| Command | Role | Notes |
|---------|------|-------|
| `import` | XLSX → pipeline | Entry point, unchanged |
| `refresh` | Full re-process | Ingest → tag → transfer → export |
| `status --json` | Data health snapshot | Counts, coverage, date range |
| `status --json --detailed` | Curated spending view | Monthly breakdown, top tags/merchants |
| `query --json` | Free SQL against SSOT | Escape hatch for ad-hoc analysis |
| `tag --json` | Apply rules | Bulk re-tag |
| `tag --edit` | Single transaction edit | Manual tag/category override |
| `transfer --json` | Detect transfer pairs | Keep as pipeline step |
| `export` | Generate deliverables | XLSX/HTML/MD output |
| `explain --json` | Rule matching trace | Domain logic: traces why a transaction got its tags |
| `rules validate` | Rule health check | Syntax, overlap, priority |
| `rules suggest --json` | Context provider (Phase 2) | Rich context, not tag answers |
| `rules add` | **New**: programmatic rule CRUD | `--name X --match Y --tags Z --category C` |
| `rules add --dry-run` | **New**: impact preview | Absorbs `simulate` functionality |
| `rules remove` | **New**: programmatic rule removal | `--name X` |
| `template run --json` | Curated SQL views | Kept as stable, named query endpoints |
| `doctor --json` | Environment health | Keep |
| `history --json` | Import audit trail | Keep |

**Remove (hard delete)**:

| Command | Why | Lines |
|---------|-----|-------|
| `ask` | AI calling AI — the outer agent does this already | 934 |
| `insights` | Agent can detect patterns from `query` results | 805 |
| `stats` | Redundant with `status --detailed` + `query` | 531 |
| `review` | Agent can use `query --json WHERE needs_review=1` | 252 |
| `context` | Agent builds its own context from `status --json` | 246 |
| `inspect` | Agent can use `query` for preset deep-dives | 206 |
| `simulate` | Absorbed into `rules add --dry-run` | 244 |

**Kept after Codex challenge**: `explain` (encodes non-trivial domain logic for rule tracing that would be worse as prompt text). `template run` (curated views reduce schema-knowledge burden on agents).

### `rules add` — Programmatic Rule CRUD (PR1)

```bash
# Add a rule (AI agent's primary action)
finjuice rules add \
  --name dining_dokkaebi \
  --match "도깨비냉장고" \
  --tags "식비,식당" \
  --category "식비" \
  --priority 75 \
  --json

# Preview impact before adding (absorbs simulate)
finjuice rules add --dry-run \
  --name dining_dokkaebi \
  --match "도깨비냉장고" \
  --tags "식비,식당" \
  --json

# Remove a rule
finjuice rules remove --name dining_dokkaebi --json
```

Output:
```json
{
  "_meta": {"command": "rules add", ...},
  "rule_name": "dining_dokkaebi",
  "action": "added",
  "impact": {"matched_transactions": 15, "total_amount": -64300},
  "rules_count": 34,
  "coverage_after": 63.5
}
```

Implementation requirements (from Codex review):
* ruamel.yaml for YAML round-trip (preserves comments)
* Duplicate name detection on write
* Validation-on-write (regex syntax, priority range, field names)
* Idempotent add semantics (re-add same name = update)
* DuckDB ILIKE for `--dry-run` impact calc (reuse simulate.py pattern)

### `rules suggest` Redesign: Context Provider (PR2)

Current (answers for the agent):
```json
{"merchant": "도깨비냉장고", "suggested_tags": ["미분류"], "confidence": 0.74}
```

Redesigned (context for the agent to decide):
```json
{
  "merchant": "도깨비냉장고",
  "transaction_count": 15,
  "total_amount": -64300,
  "avg_amount": -4287,
  "amount_stddev": 1850,
  "active_months": 8,
  "is_recurring": false,
  "time_pattern": {"weekday_pct": 0.87, "lunch_pct": 0.60},
  "banksalad_category": {"major": "식비", "minor": null},
  "payment_method": "카카오뱅크",
  "similar_merchants": [
    {"name": "예술작품을빚다비즐", "tags": ["식비", "식당"], "similarity": "same_price_range"}
  ]
}
```

Implementation: DuckDB SQL rewrite, replacing 400+ lines of Python row loops.

### Agent Loop (observe → decide → act → verify)

```
1. observe:  finjuice status --json
             → coverage 62.7%, 803 untagged

2. discover: finjuice rules suggest --json --top 5
             → rich context for top 5 untagged merchants

3. decide:   AI analyzes context, determines tags/category
             (this is the AI's job, not the CLI's)

4. preview:  finjuice rules add --dry-run --name X --match Y --tags Z --json
             → "would match 15 transactions, ₩64,300"

5. act:      finjuice rules add --name X --match Y --tags Z --category C --json
             → rule added to rules.yaml

6. apply:    finjuice tag --json
             → coverage now 63.5%

7. verify:   finjuice status --json
             → confirm improvement, loop back to 2 if needed
```

### Execution Plan (3 PRs, additive then destructive)

**PR1** (unblocks agent loop): `rules add/remove` + `rules add --dry-run` + E2E test
**PR2** (enrichment): `rules suggest` DuckDB context rewrite
**PR3** (cleanup): Hard delete 7 deprecated commands + skill update

### Consequences

**Positive**:
* CLI surface shrinks from ~28 commands to ~17
* AI agents get clean observe/decide/act/verify loop
* `rules suggest` becomes genuinely useful (context, not bad answers)
* Maintenance burden drops (3200+ lines of code + 3200+ lines of tests removed)
* Other users' AI agents can autonomously manage their data

**Negative**:
* Breaking change for anyone using `ask`, `stats`, `insights` directly
* Template SQL queries are the only remaining curated views
* `finjuice ask` was a good demo/onboarding feature

**Mitigations**:
* Additive-first PR sequencing (replacement before removal)
* Skill update ships simultaneously with hard delete
* `explain` kept for domain-specific rule debugging

### Confirmation

* E2E test: AI agent autonomously onboards new user data (import → suggest → add rules → tag → verify coverage >50%)
* Skill test: published skill can handle "이번달 카페 지출?" using `query --json`
* Performance: full observe→add→tag→verify cycle under 10s for 3000 rows

## Eng Review Decisions (2026-04-05)

| # | Decision | Choice | Rationale |
|---|----------|--------|-----------|
| 1 | Query design | Views + raw query | Curated views reduce schema burden |
| 2 | Suggest engine | Rewrite on DuckDB (PR2) | Delete O(N*M) Python row loops |
| 3 | Deprecation | Hard remove, 3-PR sequence | Additive first, destructive later (Codex) |
| 4 | YAML write | ruamel.yaml | Preserves user comments |
| 5 | E2E test | Full agent loop integration test | ADR confirmation criterion |
| 6 | Impact calc | DuckDB ILIKE | Reuse simulate.py pattern |
| 7 | Domain APIs | Keep explain, fold simulate | Codex: domain logic > prompt text |
| 8 | Suggest scope | rules add first (PR1), suggest later (PR2) | Narrowest unblocking path |

## More Information

* Related: ADR-0006 (Polars vs DuckDB roles) — query command uses DuckDB, tag command uses Polars
* Related: Issue #252 (AI-first CLI transition epic)
* Supersedes the implicit "CLI does analysis" design from v0 spec

---

**Template**: MADR 3.0.0 (Markdown Any Decision Records)
**Reference**: https://adr.github.io/madr/
