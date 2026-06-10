# Use MADR for Architecture Decisions

**Status**: accepted
**Date**: 2025-11-16
**Issue**: #110

## Context and Problem Statement

As the finjuice project evolves, we need a systematic way to document significant architectural decisions. Key challenges:

* Solo developer needs lightweight process without overhead
* Decisions need to be discoverable by future contributors and AI assistants
* Rationale for choices must be preserved (not just "what" but "why")
* Integration with existing documentation structure required

How should we document and manage architecture decisions in a way that serves both human developers and AI assistants?

## Decision Drivers

* **Simplicity**: Minimal overhead for solo developer workflow
* **Discoverability**: Easy for AI assistants (Claude Code) to find and understand decisions
* **Community standard**: Use widely adopted format for consistency
* **Markdown-first**: Plain text, version-controlled, git-friendly
* **Traceability**: Link decisions to GitHub issues and implementation PRs

## Considered Options

1. **MADR (Markdown Any Decision Records)** - Modern evolution of Nygard's ADR
2. **Original Nygard ADR template** - Classic format from 2011
3. **Y-Statements** - Alternative format focusing on context/facing/we decided
4. **Custom template** - Roll our own format
5. **No formal ADRs** - Just use GitHub issues and comments

## Decision Outcome

Chosen option: "MADR (Markdown Any Decision Records)", because:

* It's the modern standard (evolved from Nygard, maintained by adr.github.io)
* Balances comprehensiveness with simplicity
* Well-documented template with clear sections
* Tooling support (Log4brains, adr-tools)
* Commonly used in 2025 open-source projects

### Consequences

**Positive**:
* ✅ Standardized format makes decisions easily discoverable
* ✅ "Considered Options" section forces evaluation of alternatives
* ✅ Consequences section makes trade-offs explicit
* ✅ Markdown format integrates seamlessly with existing docs/
* ✅ AI assistants can parse and understand MADR structure
* ✅ Immutability principle prevents loss of historical context

**Negative**:
* ⚠️ Overhead of creating new ADR for each significant decision
* ⚠️ Template has more sections than minimal Nygard format

**Mitigations**:
* Use template.md as starting point to reduce friction
* Not every decision needs an ADR - only "significant" architectural choices
* Keep ADRs concise (2-3 paragraphs per section max)
* Link to issues/PRs for detailed implementation discussion

### Confirmation

Success will be measured by:
* New architectural decisions are documented as ADRs
* ADRs are referenced in code reviews and discussions
* AI assistants successfully use ADRs for context

## Pros and Cons of the Options

### MADR (Markdown Any Decision Records)

**Description**: Modern ADR template with structured sections for context, options, and consequences.

* ✅ Good, because it's the current community standard (2025)
* ✅ Good, because "Considered Options" forces documenting alternatives
* ✅ Good, because it has clear template with examples
* ✅ Good, because tooling support exists (Log4brains, adr-tools)
* 🔵 Neutral, because it's slightly more verbose than Nygard original
* ❌ Bad, because template has many optional sections (can feel heavyweight)

### Original Nygard ADR Template

**Description**: Classic ADR format from Michael Nygard's 2011 blog post.

* ✅ Good, because it's the original, well-known format
* ✅ Good, because it's very simple (just Title, Status, Context, Decision, Consequences)
* ❌ Bad, because it doesn't force documenting "Considered Options"
* ❌ Bad, because modern projects have moved to MADR

### Y-Statements

**Description**: Alternative format: "In the context of X, facing Y, we decided Z to achieve W, accepting downside Q."

* ✅ Good, because very concise one-liner format
* ❌ Bad, because too terse for complex decisions
* ❌ Bad, because not widely adopted (niche format)

### Custom Template

**Description**: Create our own ADR format tailored to this project.

* ✅ Good, because perfect fit for project needs
* ❌ Bad, because reinvents the wheel
* ❌ Bad, because unfamiliar to new contributors
* ❌ Bad, because no tooling support

### No Formal ADRs

**Description**: Rely on GitHub issues, PR comments, and CLAUDE.md for decision documentation.

* ✅ Good, because zero overhead
* ❌ Bad, because decisions scattered across issues/PRs
* ❌ Bad, because rationale gets lost over time
* ❌ Bad, because hard for AI assistants to find context

## More Information

* MADR homepage: https://adr.github.io/madr/
* Original Nygard post: https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions
* Template adapted from MADR 3.0.0

**Related ADRs**:
* This is the first ADR, establishing the meta-decision process
* See [README.md](README.md) for index of all decisions

**Implementation**:
* Template created at `docs/architecture/decisions/template.md`
* ADRs numbered sequentially (0001-9999)
* ADR index maintained at `docs/architecture/decisions/README.md`
