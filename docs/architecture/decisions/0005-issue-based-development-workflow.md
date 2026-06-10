# Issue-Based Development Workflow

**Status**: accepted
**Date**: 2025-10-28
**Issue**: #47

## Context and Problem Statement

As a solo-developer project with heavy AI assistance (Claude Code), we need a structured workflow that:

* Provides consistent quality gates (testing, linting, type checking)
* Links code changes to GitHub issues for traceability
* Minimizes manual steps that are error-prone
* Works well with AI pair programming
* Doesn't feel heavyweight (not Jira/enterprise process)

How can we structure development workflow to ensure quality without bureaucratic overhead?

## Decision Drivers

* **Consistency**: Same quality checks on every PR (pytest, ruff, mypy)
* **Traceability**: Code changes linked to issues/requirements
* **Automation**: Reduce manual git/test/review steps
* **AI-friendly**: Commands AI assistants can easily invoke
* **Solo dev mindset**: Lightweight, not enterprise-heavy

## Considered Options

1. **Slash command workflow** (`/issue:*` hierarchical commands)
2. **GitHub Actions only** (automate via CI/CD)
3. **Makefile targets** (`make test`, `make pr`, etc.)
4. **Git hooks** (pre-commit, pre-push)
5. **Manual workflow** (developer remembers all steps)

## Decision Outcome

Chosen option: "Slash command workflow", because:

* Hierarchical commands (`/issue:start`, `/issue:review`, `/issue:pr`) guide the workflow
* AI assistants (Claude Code) can easily invoke commands
* Automated checks (pytest, ruff, mypy) run consistently
* Git history automatically linked to issues
* Repeatable `/issue:review` vs one-shot `/issue:pr`

### Consequences

**Positive**:
* ✅ **Consistent quality gates**: Every PR runs pytest, ruff, mypy
* ✅ **Reduced manual steps**: Automation for branch creation, test running, PR creation
* ✅ **Git history linked**: Commits reference issues (e.g., `feat(#47): ...`)
* ✅ **AI-friendly**: Clear commands Claude Code can invoke
* ✅ **Repeatable reviews**: `/issue:review` can run multiple times

**Negative**:
* ⚠️ **Initial learning curve**: New contributors need to learn slash commands
* ⚠️ **Command maintenance**: Slash commands need updating as workflow evolves

**Mitigations**:
* `/issue:status` provides guidance on current state and next steps
* Documentation in CLAUDE.md explains full workflow
* Commands have clear error messages when misused

### Confirmation

Success measured by:
* All PRs pass automated checks (pytest, ruff, mypy)
* Git history shows issue linkage (commit messages reference issues)
* AI assistants successfully use slash commands without confusion

## Workflow Steps

### 1. Start Issue: `/issue:start N`
* Fetches issue from GitHub API
* Creates feature branch (`feature/issue-N-title`)
* Generates initial plan

### 2. TDD Cycle: `/issue:tdd N --feature "description"` (optional)
* **🔴 RED**: Write failing tests → Commit: `test(issue-N): add tests`
* **🟢 GREEN**: Minimal implementation → Commit: `feat(issue-N): implement`
* **🔵 REFACTOR**: Improve quality → Commit: `refactor(issue-N): improve`

### 3. Local QA: `/issue:review` (repeatable)
* Run pytest with coverage checks
* Run ruff for linting
* Run mypy for type checking
* Can be run multiple times before PR

### 4. Create PR: `/issue:pr` (once only)
* Commits all changes
* Pushes to remote
* Creates GitHub PR
* Invokes code-reviewer agent

### 5. Address Feedback: `/issue:fix` (optional)
* After PR review, make fixes
* Re-run `/issue:review`
* Push updates

### 6. Merge & Complete: `/issue:done`
* Merge PR to master
* Close issue on GitHub
* Delete feature branch
* Clean up

## Pros and Cons of the Options

### Slash Command Workflow (Chosen)

**Approach**: Hierarchical commands implemented as Claude Code slash commands.

* ✅ Good, because AI-friendly (clear invocation pattern)
* ✅ Good, because hierarchical (`/issue:*` namespace)
* ✅ Good, because automated (pytest, ruff, mypy run automatically)
* ✅ Good, because repeatable (`/issue:review` can run multiple times)
* ✅ Good, because guides workflow (status command provides help)
* 🔵 Neutral, because requires Claude Code CLI
* ❌ Bad, because initial learning curve

### GitHub Actions Only

**Approach**: All checks run in CI/CD, no local commands.

* ✅ Good, because automated (no manual steps)
* ✅ Good, because no local tool dependencies
* ❌ Bad, because slow feedback loop (wait for CI)
* ❌ Bad, because hard to test changes locally
* ❌ Bad, because doesn't guide developer workflow

### Makefile Targets

**Approach**: `make test`, `make lint`, `make pr` commands.

* ✅ Good, because familiar Unix tool
* ✅ Good, because simple implementation
* ❌ Bad, because not hierarchical (flat namespace)
* ❌ Bad, because less AI-friendly (generic `make` vs specific `/issue:*`)
* ❌ Bad, because doesn't integrate with GitHub issues

### Git Hooks

**Approach**: pre-commit, pre-push hooks enforce checks.

* ✅ Good, because automatic enforcement
* ✅ Good, because runs before bad commits pushed
* ❌ Bad, because can be bypassed (`--no-verify`)
* ❌ Bad, because doesn't guide full workflow (just gates)
* ❌ Bad, because harder to debug when hooks fail

### Manual Workflow (Status Quo)

**Approach**: Developer remembers all steps (branch, test, lint, PR).

* ✅ Good, because no tooling needed
* ❌ Bad, because error-prone (forgetting steps)
* ❌ Bad, because inconsistent (different developers skip different checks)
* ❌ Bad, because no AI guidance

## Implementation

**Slash Commands** (`.claude/commands/issue_*.md`):
* `/issue:start N` - Start working on issue
* `/issue:tdd N --feature "desc"` - TDD cycle
* `/issue:review` - Local QA (repeatable)
* `/issue:pr` - Create PR (once only)
* `/issue:fix` - Address feedback
* `/issue:done` - Merge & complete
* `/issue:status` - Show current state
* `/issue:auto [N]` - Semi-automated full cycle

**Subagents**:
* `issue-coordinator`: GitHub issue workflow orchestration
* `test-architect`: Test generation (AAA pattern)
* `security-auditor`: Auto security scan after code changes

**Hooks**:
* Post-Edit: Auto-format Python with ruff
* Pre-Commit: Ruff, mypy, secret detection

## More Information

**Documentation**:
* Workflow guide: CLAUDE.md (§Development Workflow)
* Slash commands: `.claude/commands/issue_*.md`

**Related ADRs**:
* [ADR-0001: Use MADR](0001-use-madr-for-architecture-decisions.md) - ADR process integrated with issue workflow

**References**:
* Issue #47: Issue-based workflow implementation
* Claude Code docs: https://docs.claude.com/en/docs/claude-code
