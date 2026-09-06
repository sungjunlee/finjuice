"""Identity and structure coverage for the rules test match/compute split."""

from __future__ import annotations

import importlib
from pathlib import Path

COMMANDS_DIR = Path("src/finjuice/pipeline/cli/commands")
TESTING_MODULE = "finjuice.pipeline.cli.commands.rules_cmd.testing"
MATCH_MODULE = "finjuice.pipeline.cli.commands.rules_cmd.testing_match"

MATCH_HELPER_NAMES = (
    "_normalize_rules_test_tags",
    "_serialize_rules_test_sample",
    "_build_rules_test_monthly_distribution",
    "_build_rules_test_cross_tags",
    "_rule_matches_row",
    "_record_rules_test_match",
    "_collect_rules_test_matches",
)


def test_rules_test_match_helpers_live_in_helper_module() -> None:
    """Row matching and match-result aggregation should not live in the Typer command."""
    testing_text = (COMMANDS_DIR / "rules_cmd" / "testing.py").read_text(encoding="utf-8")
    match_text = (COMMANDS_DIR / "rules_cmd" / "testing_match.py").read_text(encoding="utf-8")

    assert "def test_rule_command" in testing_text
    assert "def _compute_rules_test" in testing_text
    for name in MATCH_HELPER_NAMES:
        assert f"def {name}" not in testing_text
        assert f"def {name}" in match_text
        assert name in testing_text


def test_rules_test_match_names_stay_on_entrypoint() -> None:
    """Match helpers stay importable from the stable testing module."""
    testing = importlib.import_module(TESTING_MODULE)
    match = importlib.import_module(MATCH_MODULE)

    for name in MATCH_HELPER_NAMES:
        assert getattr(testing, name) is getattr(match, name)
        assert getattr(match, name).__module__ == MATCH_MODULE
        assert getattr(testing, name).__module__ == MATCH_MODULE

    assert testing._RULE_EVAL_FIELDS is match._RULE_EVAL_FIELDS
    assert callable(testing.test_rule_command)
    assert callable(testing._compute_rules_test)
    assert testing._compute_rules_test.__module__ == TESTING_MODULE
