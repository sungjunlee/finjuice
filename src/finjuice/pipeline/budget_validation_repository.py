"""Canonical goals validation for an activated repository."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from finjuice.pipeline.analysis_source import analysis_metadata, read_analysis_source
from finjuice.pipeline.budget_compute import _serialize_problem
from finjuice.pipeline.checkup.repository_inputs import checkup_goals
from finjuice.pipeline.goals import GoalsValidationProblem
from finjuice.pipeline.storage.authority import ActivationEvidenceProvider


def compute_repository_budget_validate(
    data_dir: Path, provider: ActivationEvidenceProvider | None = None
) -> dict[str, Any] | None:
    """Validate selected canonical bytes, distinguishing absence from nonselection."""
    snapshot = read_analysis_source(data_dir, provider)
    if snapshot is None:
        return None
    goals = checkup_goals(snapshot.goals)
    problems = goals.problems
    if not goals.exists:
        problems = [GoalsValidationProblem("goals", "Canonical goals are absent.")]
    return {
        "status": "invalid" if problems else "valid",
        "path": None,
        "authority": "repository",
        "selection_state": snapshot.goals.selection_state,
        "revision_id": snapshot.goals.head.revision_id if snapshot.goals.head else None,
        "problems": [_serialize_problem(problem) for problem in problems],
        "_problems": problems,
        "_has_errors": bool(problems),
        "_repository_meta": analysis_metadata(snapshot, "canonical_goals_validation.v1"),
    }
