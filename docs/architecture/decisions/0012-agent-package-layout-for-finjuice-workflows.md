# Agent Package Layout for Finjuice Workflows

**Status**: accepted
**Date**: 2026-05-24
**Issue**: #779
**Supersedes**: N/A

## Context and Problem Statement

finjuice currently ships agent workflows as sibling skills under `skills/finjuice*`.
The base `finjuice` skill routes to specialized skills such as `finjuice-onboard`,
`finjuice-review`, `finjuice-report`, and `finjuice-curate`. The CLI JSON surface
remains the structured tool/API layer.

Anthropic's financial-services reference package suggests a richer package shape with
named agents, vertical bundles, manifest validation, and cookbook-style workflow groups.
That pattern is attractive because finjuice already has distinct roles: analyst,
curator, reporter, onboarding guide, and diagnosis helper.

The question: should finjuice introduce named agent packages such as
`finjuice-analyst`, `finjuice-curator`, and `finjuice-reporter` now, keep the current
flat skill suite, or move toward plugin-style bundles?

## Decision Drivers

* Skill suite as product surface: users invoke finjuice through Codex/Claude Code skills,
  not a separate hosted UI.
* Local-first privacy: package boundaries must not encourage sharing real financial data,
  logs, paths, or exports.
* Provider portability: the same workflow instructions should work in Codex, Claude Code,
  and local shell contexts without depending on one host's agent abstraction.
* Low maintenance cost: each new package/agent name creates install, docs, validation, and
  support surface.
* Existing validation: the skill suite now has file-based validation for frontmatter,
  references, runtime helper paths, and sibling skill drift.
* Reversibility: aliases and bundle metadata can be added later without moving the
  canonical skill files.

## Considered Options

* Keep `skills/finjuice*` as the canonical package surface.
* Add named vertical packages now, such as `finjuice-analyst`, `finjuice-curator`, and
  `finjuice-reporter`.
* Create plugin-style bundles with generated package manifests and managed-agent
  cookbooks.

## Decision Outcome

Chosen option: **keep `skills/finjuice*` as the canonical package surface for the public
preview**, because it is already provider-neutral, validated, and close to how users
install and invoke finjuice today.

Do not introduce separate named packages such as `finjuice-analyst`,
`finjuice-curator`, or `finjuice-reporter` yet. The existing skill names remain the
stable workflow units:

* `finjuice` for routing and general analysis.
* `finjuice-onboard` for first-run import/setup.
* `finjuice-review` for conversational weekly/monthly reviews.
* `finjuice-report` for saved report artifacts.
* `finjuice-curate` and `finjuice-rule-cleanup` for rule work.
* `finjuice-diagnose` for explicit full-diagnosis workflows.

Named package concepts may appear only as documentation labels or future manifest
metadata until there is concrete evidence that users need installable bundles.

### Non-goals

* Do not introduce duplicate package directories for the same workflow.
* Do not add a second command registry or a second runtime manifest beyond the current
  CLI manifest and skill validator.
* Do not introduce provider-specific managed-agent definitions as the primary product
  surface.
* Do not split the skill suite into multiple release artifacts before public-preview
  usage shows that the split reduces real installation or routing friction.

### Migration Path

1. Continue publishing the current `skills/finjuice*` suite as one installable skill set.
2. Keep `scripts/validate_agent_package.py` as the gate for frontmatter, references,
   runtime helper paths, side-effect blocks, and sibling skill drift.
3. If named bundles become useful, first add a small metadata file that maps bundle labels
   to existing skill directories without moving files. Candidate labels:
   `finjuice-analyst`, `finjuice-curator`, and `finjuice-reporter`.
4. Add tests proving that bundle metadata is consistent with existing skill paths and
   runtime capability gates.
5. Only after at least one public-preview release and repeated user need, consider
   generated provider-specific packages or managed-agent cookbooks as derived artifacts.

### Tiny First Step

No implementation step is required in this issue. The first implementation step, if later
needed, should be a follow-up issue for metadata-only bundle labels that reference the
current skill directories.

## Consequences

**Positive**:

* The public preview has one clear install story: install the finjuice skill suite and let
  the base skill route to siblings.
* Existing validation remains effective because the package shape does not fork into
  multiple manifests.
* Provider-neutral routing stays intact for Codex, Claude Code, and shell workflows.
* Future package labels can be added without breaking existing skill paths.

**Negative**:

* Users cannot yet install only an "analyst" or "reporter" subset.
* The base skill still carries routing responsibility across many workflows.
* Contributors may continue to ask where agent/package boundaries should live.

**Mitigations**:

* Keep routing language explicit in `skills/finjuice/SKILL.md`.
* Use the agent package validator to catch stale sibling links and runtime contracts.
* Revisit named bundles only after real user installs or support requests show that the
  flat suite is causing friction.

### Confirmation

This decision is working while:

* `npx skills add sungjunlee/finjuice -g -a codex -a claude-code --skill '*'` remains the
  recommended install path.
* The base skill can route natural-language prompts to the correct sibling skill.
* `scripts/validate_agent_package.py` passes and catches stale package references.
* No support issue requires installing only a subset such as "reporter" or "curator".

## Pros and Cons of the Options

### Keep `skills/finjuice*` Canonical

* Good, because it matches the current product surface and public docs.
* Good, because it avoids provider-specific abstractions.
* Good, because validation can stay file-based and dependency-light.
* Bad, because package roles are implicit in skill names rather than a formal bundle
  manifest.

### Add Named Vertical Packages Now

* Good, because names such as `finjuice-analyst` and `finjuice-reporter` could be clearer
  for product positioning.
* Good, because users might eventually want smaller installs.
* Bad, because it duplicates existing skill routing before there is evidence of install
  friction.
* Bad, because every package name needs docs, validation, and migration support.

### Plugin-style Bundles and Managed-agent Cookbooks

* Good, because generated manifests and cookbooks could help richer agent ecosystems.
* Good, because Anthropic's financial-services reference shows how vertical packages can
  scale for larger organizations.
* Bad, because finjuice is still a solo-maintainer public preview with privacy-sensitive
  local data.
* Bad, because provider-specific agent files would become a second product surface before
  the CLI JSON and skill contracts finish stabilizing.

## Reconsideration Triggers

Revisit this decision when one of these is true:

* At least three public users ask for subset installs or named role packages.
* Support issues show repeated confusion between `finjuice-review`, `finjuice-report`, and
  `finjuice-curate`.
* A host ecosystem requires package manifests that cannot be generated from current skill
  files.
* The skill validator can check bundle metadata and provider-specific generated artifacts
  without adding manual release burden.

## More Information

Related decisions and artifacts:

* [ADR-0007: CLI as Structured Data API for AI Agents](0007-cli-as-data-api-for-ai-agents.md)
* [ADR-0011: Defer MCP and Vector Search for Index](0011-defer-mcp-and-vector-search-for-index.md)
* `scripts/validate_agent_package.py`
* `skills/finjuice/SKILL.md`

---

**Template**: MADR 3.0.0 (Markdown Any Decision Records)
**Reference**: https://adr.github.io/madr/
