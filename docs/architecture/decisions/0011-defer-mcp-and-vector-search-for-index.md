# Defer MCP and Vector Search for Index

**Status**: accepted
**Date**: 2026-05-24
**Issue**: #774
**Supersedes**: N/A

## Context and Problem Statement

`finjuice index --json` gives agents a catalog of workspace collections, privacy levels,
freshness, counts, and safe next commands. Prior art such as QMD makes local collection
indexing, hybrid search, and MCP surfaces tempting. Those tools solve a different first
problem: finding relevant passages across mostly unstructured document collections.

finjuice's first agent problem is narrower and higher risk. Agents need a safe map of a
private finance workspace before they decide whether to inspect transactions, rules,
assets, reports, goals, or scenarios. Merchant names, amounts, filenames, paths, and
asset details are sensitive. Adding retrieval infrastructure before the JSON contracts
stabilize would increase privacy and maintenance risk without first proving that agents
can use the boring catalog correctly.

The question: should finjuice move from `index --json` directly to MCP/vector search, or
should it stage discovery surfaces more conservatively?

## Decision Drivers

* Local-first privacy: private financial rows and paths must stay out of default agent
  context.
* Stable CLI JSON contracts: skills and downstream agents need predictable schemas before
  richer discovery layers.
* Solo-maintainer cost: MCP servers, embedding stores, migrations, and ranking evaluation
  add operational surface area.
* Agent ergonomics: agents first need to know what collections exist and which safe
  commands to run, not semantic retrieval over every row.
* Reversibility: a catalog-first interface can later feed retrieval or MCP without
  committing to a protocol too early.

## Considered Options

* Catalog first, retrieval later, MCP last.
* Add vector or hybrid search as the next index milestone.
* Add an MCP server as the primary agent discovery layer.

## Decision Outcome

Chosen option: "Catalog first, retrieval later, MCP last", because it keeps the current
agent discovery surface simple, privacy-aware, and testable while the CLI/index contracts
are still being hardened.

The staged approach is:

1. Stabilize `finjuice manifest --json`, `finjuice index --json`, schema refs, privacy
   profiles, and skill guidance.
2. Add targeted read primitives only when a concrete workflow cannot be served by
   `status`, `checkup`, `show`, `query`, `rules`, `template`, or `export`.
3. Reconsider retrieval after there are measured agent failures that require ranking,
   not just cataloging.
4. Reconsider MCP after the CLI JSON contracts and skill suite are stable enough to map
   into long-lived tool contracts.

### Consequences

**Positive**:
* The default index remains safe to expose to agents without row-level or path-level
  leakage.
* Tests can pin the catalog schema and privacy profiles before any search ranking exists.
* Skills can use the same CLI JSON surface in Claude Code, Codex, and shell contexts.
* Future MCP or retrieval work can reuse the catalog as a source map instead of replacing
  it.

**Negative**:
* Agents do not get semantic search over journals, rules, reports, or transactions yet.
* Some exploratory workflows still require explicit `query`, `show`, or template calls.
* Contributors may repeatedly propose MCP/vector work because it is an obvious adjacent
  agent feature.

**Mitigations**:
* Keep `index --json` explicitly documented as a catalog, not a search engine.
* Add workflow-specific read primitives only when their privacy contract can be described
  and tested.
* Use this ADR as the default answer for MCP/vector proposals until a trigger below is
  met.

### Confirmation

This decision is working while:

* Agents can choose the correct next command from `index --json` plus skill guidance.
* `index --json` and `manifest --json` schemas stay stable enough for generated docs and
  contract tests.
* No recurring workflow requires ranked retrieval to avoid unsafe or excessive raw data
  reads.

## Pros and Cons of the Options

### Catalog First, Retrieval Later, MCP Last

Keep `index --json` as a boring, collection-level catalog and defer search/protocol
infrastructure.

* Good, because it minimizes privacy leakage by default.
* Good, because it lets agents inspect structured collections intentionally.
* Good, because it preserves the CLI as the source of truth across agent hosts.
* Bad, because it does not solve open-ended semantic discovery yet.

### Add Vector or Hybrid Search Next

Create embeddings or a hybrid lexical/vector index for workspace artifacts and possibly
transaction context.

* Good, because it could help agents find relevant notes, reports, or rule rationale.
* Good, because QMD-like document workflows show the value of local collection search.
* Bad, because finjuice's most sensitive data is structured finance data, not a generic
  document corpus.
* Bad, because ranking quality, redaction, incremental indexing, and embedding storage
  would all need new tests and privacy review.

### Add MCP as the Primary Agent Discovery Layer

Expose finjuice collections and commands through a local MCP server before the CLI JSON
contracts settle.

* Good, because MCP could provide typed tools for agent hosts that support it.
* Good, because it may eventually reduce shell-command prompt burden.
* Bad, because it would create a second product/API surface before the CLI schemas,
  manifest, index, and skills have stabilized.
* Bad, because Codex/Claude Code portability currently depends on boring CLI JSON and
  local skill instructions.

## Reconsideration Triggers

Revisit vector or hybrid search when one of these is true:

* At least three real workflows cannot be handled safely with `index`, `checkup`,
  `status`, `show`, `query`, `template`, `rules`, or `export`.
* Agents repeatedly over-read raw transaction rows because no smaller ranked context
  primitive exists.
* Journals/reports/rule notes become large enough that exact file or command selection is
  the main workflow bottleneck.
* A privacy-preserving retrieval test harness exists for redaction, ranking quality, and
  stale-index behavior.

Revisit MCP when one of these is true:

* The CLI JSON schemas and manifest have stayed stable across at least one public-preview
  release.
* The skill suite has a validation script that can map workflows to command contracts.
* There is a concrete host integration that needs MCP and cannot use local CLI JSON.
* MCP tools can be generated from existing manifest/schema metadata without hand-maintaining
  a second command registry.

## More Information

Related decisions:

* [ADR-0007: CLI as Structured Data API for AI Agents](0007-cli-as-data-api-for-ai-agents.md)
* [ADR-0009: No CLI Command Spec Registry](0009-no-cli-command-spec-registry.md)

This ADR contrasts QMD-style document search with finjuice's structured finance workspace:
QMD primarily helps locate passages across local documents, while finjuice first needs to
tell an agent which private finance collection exists, what privacy level it has, and
which audited CLI JSON command can inspect it next.

---

**Template**: MADR 3.0.0 (Markdown Any Decision Records)
**Reference**: https://adr.github.io/madr/
