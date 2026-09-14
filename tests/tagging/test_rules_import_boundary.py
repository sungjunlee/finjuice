"""Rules entrypoints can initialize before the storage package in fresh processes."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

import finjuice


@pytest.mark.parametrize(
    "entrypoint",
    ["rules_yaml_append", "rules_yaml_load", "rules_yaml_io", "rules_yaml_roundtrip"],
)
def test_rules_entrypoint_imports_in_fresh_process(entrypoint: str, tmp_path: Path) -> None:
    source = Path(finjuice.__file__).resolve().parent.parent
    script = """
import importlib
import sys
sys.path.insert(0, sys.argv[1])
module = importlib.import_module('finjuice.pipeline.tagging.' + sys.argv[2])
from pathlib import Path
assert Path(module.__file__).resolve().is_relative_to(Path(sys.argv[1]).resolve())
from finjuice.pipeline.tagging import rules_yaml_append, rules_yaml_io, rules_yaml_load
from finjuice.pipeline.tagging import rules_yaml_roundtrip
assert rules_yaml_io.append_rule is rules_yaml_append.append_rule
assert rules_yaml_io.load_rules is rules_yaml_load.load_rules
assert rules_yaml_io.add_rule_roundtrip is rules_yaml_roundtrip.add_rule_roundtrip
assert rules_yaml_io.update_rule_roundtrip is rules_yaml_roundtrip.update_rule_roundtrip
assert rules_yaml_io.remove_rule_roundtrip is rules_yaml_roundtrip.remove_rule_roundtrip
assert rules_yaml_io.save_rule_dicts_roundtrip is rules_yaml_roundtrip.save_rule_dicts_roundtrip
"""

    result = subprocess.run(
        [sys.executable, "-c", script, str(source), entrypoint],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert result.returncode == 0, result.stderr
