"""Private-content-safe diagnostics for a pinned canonical rules selection."""

from __future__ import annotations

from collections import Counter
from typing import Any

from finjuice.pipeline.doctor.models import CheckResult
from finjuice.pipeline.storage.sqlite.portfolio_reads import PortfolioConfigSnapshot
from finjuice.pipeline.tagging.rules_yaml_io import load_rules_collecting_bytes
from finjuice.pipeline.tagging.validator import validate_rules


def rules_checks(selection: PortfolioConfigSnapshot) -> tuple[list[CheckResult], dict[str, Any]]:
    """Collect indexed validation failures without exposing rule names or values."""
    head = selection.head
    metadata: dict[str, Any] = {
        "rules_selection_state": selection.selection_state,
        "rules_revision_id": head.revision_id if head else None,
        "rules_parsed_status": head.parsed_status if head else None,
        "rules_issue_counts": {},
    }
    if head is None:
        absent = selection.selection_state == "absent" and not selection.revisions
        return [
            CheckResult(
                "warning" if absent else "error",
                "Canonical rules absent."
                if absent
                else "Canonical rules require explicit selection.",
                name="repository_rules",
            )
        ], metadata
    try:
        loaded = load_rules_collecting_bytes(head.content, validate_condition_regex=True)
        issues = Counter({"schema_error": len(loaded.errors)} if loaded.errors else {})
        validation = validate_rules(loaded.rules)
        issues.update(issue.issue_type for issue in validation.issues)
        if selection.selection_state != "selected" or head.parsed_status != "parsed":
            issues["selection_not_parsed"] += 1
        metadata["rules_issue_counts"] = dict(sorted(issues.items()))
        metadata["rules_count"] = len(loaded.rules) + len(loaded.errors)
        errors = bool(loaded.errors or issues["selection_not_parsed"]) or any(
            issue.severity == "error" for issue in validation.issues
        )
        warnings = any(issue.severity == "warning" for issue in validation.issues)
        status = "warning" if warnings else "ok"
        if errors:
            status = "error"
        return [
            CheckResult(
                status,
                f"Canonical rules: {metadata['rules_count']} rules.",
                detail=", ".join(f"{code}: {count}" for code, count in sorted(issues.items())),
                name="repository_rules",
            )
        ], metadata
    except Exception:
        metadata["rules_issue_counts"] = {"document_invalid": 1}
        return [
            CheckResult(
                "error",
                "Canonical rules could not be validated.",
                name="repository_rules",
            )
        ], metadata
