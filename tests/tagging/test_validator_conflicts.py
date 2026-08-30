"""Identity checks for the split tagging validator conflict helpers."""

from pathlib import Path

from finjuice.pipeline.tagging import validator as validator_module
from finjuice.pipeline.tagging import validator_conflicts as conflicts_module

TAGGING_DIR = Path("src/finjuice/pipeline/tagging")


def test_conflict_helpers_live_in_helper_module() -> None:
    """Conflict-detection checks should not live in validator.py."""
    validator_text = (TAGGING_DIR / "validator.py").read_text(encoding="utf-8")
    conflicts_text = (TAGGING_DIR / "validator_conflicts.py").read_text(encoding="utf-8")

    assert "def _validate_rule" in validator_text
    assert "def validate_rules" in validator_text
    assert "def check_duplicate_names" not in validator_text
    assert "def check_pattern_overlaps" not in validator_text
    assert "def check_priority_inversions" not in validator_text
    assert "def check_regex_validity" not in validator_text
    assert "def _get_patterns" not in validator_text
    assert "def _patterns_overlap" not in validator_text
    assert "def _is_broader_pattern" not in validator_text
    assert "class ValidationIssue" not in validator_text
    assert "class ValidationResult" not in validator_text
    assert "def check_duplicate_names" in conflicts_text
    assert "def check_pattern_overlaps" in conflicts_text
    assert "def check_priority_inversions" in conflicts_text
    assert "def check_regex_validity" in conflicts_text
    assert "def _get_patterns" in conflicts_text
    assert "def _patterns_overlap" in conflicts_text
    assert "def _is_broader_pattern" in conflicts_text
    assert "class ValidationIssue" in conflicts_text
    assert "class ValidationResult" in conflicts_text


def test_conflict_helpers_reexport_from_validator() -> None:
    """Existing validator imports should keep resolving to the conflict helpers."""
    assert validator_module.ValidationIssue is conflicts_module.ValidationIssue
    assert validator_module.ValidationResult is conflicts_module.ValidationResult
    assert validator_module.check_duplicate_names is conflicts_module.check_duplicate_names
    assert validator_module.check_pattern_overlaps is conflicts_module.check_pattern_overlaps
    assert validator_module.check_priority_inversions is conflicts_module.check_priority_inversions
    assert validator_module.check_regex_validity is conflicts_module.check_regex_validity
    assert validator_module._get_patterns is conflicts_module._get_patterns
    assert validator_module._patterns_overlap is conflicts_module._patterns_overlap
    assert validator_module._is_broader_pattern is conflicts_module._is_broader_pattern
    assert callable(validator_module._validate_rule)
    assert callable(validator_module.validate_rules)


def test_conflict_helpers_do_not_import_cli() -> None:
    """Conflict helpers must not import finjuice.pipeline.cli.*."""
    for path in (
        TAGGING_DIR / "validator.py",
        TAGGING_DIR / "validator_conflicts.py",
    ):
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            assert "from finjuice.pipeline.cli" not in stripped
            assert "import finjuice.pipeline.cli" not in stripped
