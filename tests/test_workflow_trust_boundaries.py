"""Pytest wrapper that delegates the trust-boundary check to the standalone script.

The actual invariants live in ``scripts/check_workflow_permissions.py`` so the
docs-check workflow can verify them in a minimal environment (no pytest, no
project conftest, no project runtime dependencies). This test ensures the same
gate also runs as part of the regular pytest suite.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_workflow_permissions.py"
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"

TRUSTED_ASSOCIATION_MARKER = '["OWNER","MEMBER","COLLABORATOR"]'
TRUSTED_ACTOR_ALLOWLIST_MARKER = '["sungjunlee"]'
PUBLIC_COMMENT_EVENTS = {
    "issue_comment",
    "pull_request_review_comment",
    "pull_request_review",
    "issues",
}


def _load_workflow(name: str) -> dict[str, object]:
    with (WORKFLOW_DIR / name).open(encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)
    assert isinstance(loaded, dict)
    return loaded


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


def _workflow_jobs(workflow: dict[str, object]) -> dict[str, object]:
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict)
    return jobs


def _runs_on_self_hosted(job: object) -> bool:
    assert isinstance(job, dict)
    runs_on = job.get("runs-on")
    if isinstance(runs_on, str):
        return runs_on == "self-hosted"
    if isinstance(runs_on, list):
        return "self-hosted" in runs_on
    return False


def _if_expression(job: object) -> str:
    assert isinstance(job, dict)
    return str(job.get("if", ""))


def _job_text(job: object) -> str:
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


def test_workflow_trust_boundary_script_passes() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"scripts/check_workflow_permissions.py failed:\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )


def test_dependency_audit_workflow_counts_vulnerabilities_not_dependencies() -> None:
    """The dependency audit issue gate should count advisory rows, not package rows."""
    workflow = (REPO_ROOT / ".github" / "workflows" / "audit.yml").read_text(encoding="utf-8")

    assert 'len(r.get("dependencies", []))' not in workflow
    assert "len(r.get('dependencies', []))" not in workflow
    assert 'sum(len(dep.get("vulns", [])) for dep in r.get("dependencies", []))' in workflow


def test_codeql_workflow_is_private_repo_tolerant() -> None:
    """Private repos without GHAS should not make the CodeQL workflow fail."""
    workflow = _load_workflow("codeql.yml")
    jobs = _workflow_jobs(workflow)

    analyze = jobs.get("analyze")
    private_summary = jobs.get("private-repo-summary")

    assert "github.event.repository.private == false" in _if_expression(analyze)
    assert isinstance(private_summary, dict)
    assert "github.event.repository.private == true" in _if_expression(private_summary)


def test_scorecard_workflow_is_private_repo_tolerant() -> None:
    """Private repos should not fail Scorecard when GitHub API/SARIF upload is unavailable."""
    workflow = _load_workflow("scorecard.yml")
    jobs = _workflow_jobs(workflow)

    analysis = jobs.get("analysis")
    private_summary = jobs.get("private-repo-summary")

    assert "github.event.repository.private == false" in _if_expression(analysis)
    assert isinstance(private_summary, dict)
    assert "github.event.repository.private == true" in _if_expression(private_summary)


def test_workflows_do_not_use_self_hosted_runners() -> None:
    offenders: list[str] = []
    for path in sorted(WORKFLOW_DIR.glob("*.yml")):
        workflow = _load_workflow(path.name)
        for job_name, job in _workflow_jobs(workflow).items():
            if _runs_on_self_hosted(job):
                offenders.append(f"{path.name}:{job_name}")

    assert offenders == []


def test_public_comment_jobs_do_not_run_on_self_hosted_runners() -> None:
    offenders: list[str] = []
    for path in sorted(WORKFLOW_DIR.glob("*.yml")):
        workflow = _load_workflow(path.name)
        if not (_workflow_events(workflow) & PUBLIC_COMMENT_EVENTS):
            continue
        for job_name, job in _workflow_jobs(workflow).items():
            if _runs_on_self_hosted(job):
                offenders.append(f"{path.name}:{job_name}")

    assert offenders == []


def test_secret_backed_claude_jobs_require_trusted_author_gate() -> None:
    offenders: list[str] = []
    for workflow_name in ("claude.yml", "claude-code-review.yml"):
        workflow = _load_workflow(workflow_name)
        for job_name, job in _workflow_jobs(workflow).items():
            text = _job_text(job)
            uses_claude_secret = (
                "anthropics/claude-code-action" in text
                or "CLAUDE_CODE_OAUTH_TOKEN" in text
                or "ANTHROPIC_API_KEY" in text
            )
            if uses_claude_secret and not _has_trusted_author_gate(_if_expression(job)):
                offenders.append(f"{workflow_name}:{job_name}")

    assert offenders == []


def test_claude_review_public_feedback_job_is_secret_free() -> None:
    workflow = _load_workflow("claude-code-review.yml")
    public_feedback = _workflow_jobs(workflow).get("public-feedback")

    assert isinstance(public_feedback, dict)
    assert public_feedback["runs-on"] == "ubuntu-latest"
    assert "pull_request" in _workflow_events(workflow)
    assert "github.event.pull_request" in _if_expression(public_feedback)
    assert "self-hosted" not in _job_text(public_feedback)
    assert "secrets." not in _job_text(public_feedback)
    assert "anthropics/claude-code-action" not in _job_text(public_feedback)
