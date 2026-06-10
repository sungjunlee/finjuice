#!/usr/bin/env python3
"""Standalone trust-boundary check for GitHub Actions workflows.

Runs with only stdlib + PyYAML so it can execute in the minimal docs-check
environment, independent of pytest, conftest, or project runtime dependencies.

Equivalent to the assertions in tests/test_workflow_trust_boundaries.py, but
suitable for direct invocation: ``python scripts/check_workflow_permissions.py``.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

WORKFLOW_DIR = Path(".github/workflows")
DEVELOPMENT_DOCS_DIR = Path("docs/development")

ALLOWED_JOB_WRITES: dict[tuple[str, str], set[str]] = {
    ("audit.yml", "audit"): {"issues"},
    ("claude-code-review.yml", "claude-review"): {"id-token"},
    ("claude.yml", "claude"): {"id-token"},
    ("codeql.yml", "analyze"): {"security-events"},
    ("release.yml", "release"): {"attestations", "contents", "id-token"},
    ("scorecard.yml", "analysis"): {"security-events"},
}

REQUIRED_CHECKS = (
    "CI Lint",
    "CI Test 3.13",
    "Documentation Quality Checks",
    "Package Artifacts",
    "Security Baselines",
    "Public PR Gate",
    "CodeRabbit",
    "claude-review",
)

REQUIRED_BRANCH_PHRASES = (
    "1 approving review",
    "force-push",
    "branch deletion",
    "GitHub plan/API",
    "Settings UI",
    "release.md",
)

REQUIRED_WORKFLOW_DOC_REFS = (
    "audit.yml",
    "ci.yml",
    "ci-full.yml",
    "codeql.yml",
    "docs-check.yml",
    "claude-code-review.yml",
    "claude.yml",
    "public-pr-ci.yml",
    "release.yml",
    "scorecard.yml",
)

PUBLIC_COMMENT_EVENTS = {
    "issue_comment",
    "pull_request_review_comment",
    "pull_request_review",
    "issues",
}
TRUSTED_ASSOCIATION_MARKER = '["OWNER","MEMBER","COLLABORATOR"]'
TRUSTED_ACTOR_ALLOWLIST_MARKER = '["sungjunlee"]'
PINNED_ACTION_REF_PATTERN = re.compile(r"@[0-9a-f]{40}$")


def _load(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise SystemExit(f"{path}: top-level YAML must be a mapping")
    return data


def _workflow_events(workflow: dict[str, object]) -> set[str]:
    """Return trigger names, accounting for PyYAML's YAML 1.1 ``on`` boolean."""
    trigger = workflow.get("on", workflow.get(True))
    if isinstance(trigger, str):
        return {trigger}
    if isinstance(trigger, list):
        return {str(item) for item in trigger}
    if isinstance(trigger, dict):
        return {str(item) for item in trigger}
    return set()


def _runs_on_self_hosted(job: dict[str, object]) -> bool:
    runs_on = job.get("runs-on")
    if isinstance(runs_on, str):
        return runs_on == "self-hosted"
    if isinstance(runs_on, list):
        return "self-hosted" in runs_on
    return False


def _job_if(job: dict[str, object]) -> str:
    return str(job.get("if", ""))


def _job_text(job: dict[str, object]) -> str:
    return yaml.safe_dump(job, sort_keys=True)


def _has_trusted_author_gate(expression: str) -> bool:
    return (
        "author_association" in expression
        and TRUSTED_ASSOCIATION_MARKER in expression
        and TRUSTED_ACTOR_ALLOWLIST_MARKER in expression
    )


def _has_trusted_pr_guard(expression: str) -> bool:
    return (
        _has_trusted_author_gate(expression)
        and "github.event.pull_request.head.repo.full_name == github.repository" in expression
    )


def _uses_secret_backed_claude(job: dict[str, object]) -> bool:
    text = _job_text(job)
    return (
        "anthropics/claude-code-action" in text
        or "CLAUDE_CODE_OAUTH_TOKEN" in text
        or "ANTHROPIC_API_KEY" in text
    )


def _check_top_level_permissions(errors: list[str]) -> None:
    workflows = sorted(WORKFLOW_DIR.glob("*.yml"))
    if not workflows:
        errors.append("no workflows found under .github/workflows/*.yml")
        return
    for path in workflows:
        wf = _load(path)
        perms = wf.get("permissions")
        if not isinstance(perms, dict):
            errors.append(f"{path}: missing top-level permissions mapping")
            continue
        if perms.get("contents") != "read":
            errors.append(f"{path}: top-level permissions.contents must be 'read'")
        if "write" in set(perms.values()):
            errors.append(f"{path}: top-level permissions must not grant any write scope")


def _check_job_writes(errors: list[str]) -> None:
    for path in sorted(WORKFLOW_DIR.glob("*.yml")):
        wf = _load(path)
        jobs = wf.get("jobs")
        if not isinstance(jobs, dict):
            errors.append(f"{path}: jobs must be a mapping")
            continue
        for job_name, job in jobs.items():
            if not isinstance(job, dict):
                continue
            perms = job.get("permissions", {})
            if not isinstance(perms, dict):
                errors.append(f"{path}:{job_name}: job permissions must be a mapping")
                continue
            write_scopes = {scope for scope, access in perms.items() if access == "write"}
            expected = ALLOWED_JOB_WRITES.get((path.name, str(job_name)), set())
            if write_scopes != expected:
                errors.append(
                    f"{path}:{job_name}: unexpected write scopes {sorted(write_scopes)} "
                    f"(expected {sorted(expected)})"
                )


def _check_trigger_boundaries(errors: list[str]) -> None:
    for path in sorted(WORKFLOW_DIR.glob("*.yml")):
        workflow = _load(path)
        events = _workflow_events(workflow)
        if "pull_request_target" in events:
            errors.append(f"{path}: pull_request_target is not allowed without a security review")
        jobs = workflow.get("jobs")
        if not isinstance(jobs, dict):
            continue
        for job_name, job in jobs.items():
            if not isinstance(job, dict) or not _runs_on_self_hosted(job):
                continue
            expression = _job_if(job)
            if "pull_request" in events and not _has_trusted_pr_guard(expression):
                errors.append(
                    f"{path}:{job_name}: self-hosted pull_request job must require same-repo "
                    "PR plus trusted author_association/allowlist"
                )
            if events & PUBLIC_COMMENT_EVENTS and not _has_trusted_author_gate(expression):
                errors.append(
                    f"{path}:{job_name}: self-hosted public comment job must require trusted "
                    "author_association/allowlist"
                )


def _check_no_self_hosted_runners(errors: list[str]) -> None:
    for path in sorted(WORKFLOW_DIR.glob("*.yml")):
        workflow = _load(path)
        jobs = workflow.get("jobs")
        if not isinstance(jobs, dict):
            continue
        for job_name, job in jobs.items():
            if isinstance(job, dict) and _runs_on_self_hosted(job):
                errors.append(f"{path}:{job_name}: public workflows must use GitHub-hosted runners")


def _check_claude_boundaries(errors: list[str]) -> None:
    for workflow_name in ("claude.yml", "claude-code-review.yml"):
        path = WORKFLOW_DIR / workflow_name
        workflow = _load(path)
        events = _workflow_events(workflow)
        jobs = workflow.get("jobs")
        if not isinstance(jobs, dict):
            errors.append(f"{path}: jobs must be a mapping")
            continue
        for job_name, job in jobs.items():
            if not isinstance(job, dict) or not _uses_secret_backed_claude(job):
                continue
            expression = _job_if(job)
            if not _has_trusted_author_gate(expression):
                errors.append(
                    f"{path}:{job_name}: secret-backed Claude job must require trusted "
                    "author_association/allowlist"
                )
            if "pull_request" in events and not _has_trusted_pr_guard(expression):
                errors.append(
                    f"{path}:{job_name}: pull_request Claude job must also require a same-repo PR"
                )


def _check_claude_public_feedback(errors: list[str]) -> None:
    path = WORKFLOW_DIR / "claude-code-review.yml"
    workflow = _load(path)
    jobs = workflow.get("jobs")
    if not isinstance(jobs, dict):
        errors.append(f"{path}: jobs must be a mapping")
        return
    public_feedback = jobs.get("public-feedback")
    if not isinstance(public_feedback, dict):
        errors.append(f"{path}: missing secret-free public-feedback job")
        return
    if public_feedback.get("runs-on") != "ubuntu-latest":
        errors.append(f"{path}:public-feedback: must run on GitHub-hosted ubuntu-latest")
    expression = _job_if(public_feedback)
    if "github.event.pull_request" not in expression:
        errors.append(f"{path}:public-feedback: must be scoped to pull_request context")
    text = _job_text(public_feedback)
    for forbidden in ("self-hosted", "secrets.", "anthropics/claude-code-action"):
        if forbidden in text:
            errors.append(f"{path}:public-feedback: must not contain {forbidden!r}")
    perms = public_feedback.get("permissions", {})
    if not isinstance(perms, dict):
        errors.append(f"{path}:public-feedback: permissions must be a mapping")
        return
    write_scopes = {scope for scope, access in perms.items() if access == "write"}
    if write_scopes:
        errors.append(f"{path}:public-feedback: must not grant write scopes {sorted(write_scopes)}")


def _check_action_refs_pinned(errors: list[str]) -> None:
    for path in sorted(WORKFLOW_DIR.glob("*.yml")):
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            match = re.search(r"uses:\s*([^\s#]+)", line)
            if match and PINNED_ACTION_REF_PATTERN.search(match.group(1)) is None:
                errors.append(
                    f"{path}:{line_number}: action ref {match.group(1)!r} must be pinned "
                    "to a full 40-character commit SHA"
                )


def _check_required_strings(doc: Path, required: tuple[str, ...], label: str) -> list[str]:
    if not doc.exists():
        return [f"missing {doc}"]
    text = doc.read_text(encoding="utf-8")
    return [f"{doc}: missing {label} '{item}'" for item in required if item not in text]


def _check_docs(errors: list[str]) -> None:
    branch_doc = DEVELOPMENT_DOCS_DIR / "branch-protection.md"
    permission_doc = DEVELOPMENT_DOCS_DIR / "workflow-permissions.md"
    errors.extend(_check_required_strings(branch_doc, REQUIRED_CHECKS, "required check reference"))
    errors.extend(_check_required_strings(branch_doc, REQUIRED_BRANCH_PHRASES, "required phrase"))
    errors.extend(
        _check_required_strings(permission_doc, REQUIRED_WORKFLOW_DOC_REFS, "reference to")
    )


def main() -> int:
    errors: list[str] = []
    _check_top_level_permissions(errors)
    _check_job_writes(errors)
    _check_no_self_hosted_runners(errors)
    _check_trigger_boundaries(errors)
    _check_claude_boundaries(errors)
    _check_claude_public_feedback(errors)
    _check_action_refs_pinned(errors)
    _check_docs(errors)
    if errors:
        print("workflow trust-boundary check failed:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    print("workflow trust-boundary check: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
