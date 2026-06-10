"""Contract tests for finjuice skill side-effect declarations."""

import re
from pathlib import Path

ALLOWED_MODES = {
    "read-only",
    "mutating-with-confirmation",
    "artifact-writing",
    "journal-writing",
    "runtime-install/update",
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _finjuice_skill_files() -> list[Path]:
    skill_root = _repo_root() / "skills"
    return sorted(path for path in skill_root.glob("finjuice*/SKILL.md") if path.is_file())


def _side_effect_block(skill_text: str) -> str:
    match = re.search(r"(?ms)^## Side Effects\n(?P<body>.*?)(?=^## |\Z)", skill_text)
    assert match, "missing ## Side Effects block"
    return match.group("body")


def _declared_modes(block: str) -> set[str]:
    modes_line = next(
        (line for line in block.splitlines() if line.startswith("- Modes:")),
        "",
    )
    assert modes_line, "missing '- Modes:' declaration"
    modes = set(re.findall(r"`([^`]+)`", modes_line))
    assert modes, "side-effect modes must use backticked taxonomy values"
    return modes


def test_all_finjuice_skills_declare_allowed_side_effect_modes() -> None:
    """Every finjuice skill should expose its side-effect contract near the top."""
    skill_files = _finjuice_skill_files()
    assert skill_files

    for path in skill_files:
        text = path.read_text(encoding="utf-8")
        block = _side_effect_block(text)
        unknown_modes = _declared_modes(block) - ALLOWED_MODES

        assert not unknown_modes, f"{path.relative_to(_repo_root())}: {unknown_modes}"


def test_side_effect_policy_defines_required_taxonomy() -> None:
    """The shared policy should define every allowed side-effect mode."""
    policy = (_repo_root() / "skills/finjuice/references/persistence-policy.md").read_text(
        encoding="utf-8"
    )

    for mode in ALLOWED_MODES:
        assert f"`{mode}`" in policy


def test_finjuice_review_refresh_requires_confirmation() -> None:
    """Review should not claim file-safe chat-only behavior while refresh can mutate."""
    review = (_repo_root() / "skills/finjuice-review/SKILL.md").read_text(encoding="utf-8")
    block = _side_effect_block(review)
    modes = _declared_modes(block)
    step_zero = re.search(r"(?ms)^## Step 0 .*?\n(?P<body>.*?)(?=^## |\Z)", review)

    assert "mutating-with-confirmation" in modes
    assert "finjuice refresh --json" in block
    assert "explicit user confirmation" in block
    assert "chat-only skill" not in review
    assert step_zero
    assert "explicit user" in step_zero.group("body")
    assert "update generated outputs/runtime data" in step_zero.group("body")
