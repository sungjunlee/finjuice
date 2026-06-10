"""Tests for reviewed security scan baselines."""

from __future__ import annotations

from pathlib import Path

from scripts import check_security_baselines


def test_bandit_compare_passes_when_current_finding_is_baselined(tmp_path: Path) -> None:
    """Reviewed Bandit findings should not fail the gate."""
    source = tmp_path / "src" / "finjuice" / "sample.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "def build_select(table):\n    query = 'SELECT * FROM ' + table\n    return query\n",
        encoding="utf-8",
    )
    report = {
        "results": [
            {
                "test_id": "B608",
                "test_name": "hardcoded_sql_expressions",
                "filename": str(source),
                "line_number": 2,
                "line_range": [2],
                "issue_severity": "MEDIUM",
                "issue_confidence": "LOW",
                "issue_text": "Possible SQL injection vector through string-based query.",
            }
        ]
    }
    current = check_security_baselines.normalize_bandit_report(report, root=tmp_path)
    baseline = {
        "schema_version": 1,
        "tool": "bandit",
        "findings": [
            {
                "test_id": "B608",
                "filename": "src/finjuice/sample.py",
                "function": "build_select",
                "rationale": "parametrized DuckDB SQL builder, no user input concatenation",
            }
        ],
    }

    diff = check_security_baselines.compare_bandit_findings(current, baseline)

    assert not diff.failed


def test_bandit_compare_fails_for_added_finding(tmp_path: Path) -> None:
    """A new Bandit finding beyond the reviewed baseline should fail."""
    source = tmp_path / "src" / "finjuice" / "sample.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "def build_select(table):\n"
        "    return 'SELECT * FROM ' + table\n"
        "\n"
        "def build_delete(table):\n"
        "    return 'DELETE FROM ' + table\n",
        encoding="utf-8",
    )
    report = {
        "results": [
            {
                "test_id": "B608",
                "test_name": "hardcoded_sql_expressions",
                "filename": str(source),
                "line_number": 2,
                "issue_severity": "MEDIUM",
                "issue_confidence": "LOW",
                "issue_text": "Possible SQL injection vector.",
            },
            {
                "test_id": "B608",
                "test_name": "hardcoded_sql_expressions",
                "filename": str(source),
                "line_number": 5,
                "issue_severity": "MEDIUM",
                "issue_confidence": "LOW",
                "issue_text": "Possible SQL injection vector.",
            },
        ]
    }
    current = check_security_baselines.normalize_bandit_report(report, root=tmp_path)
    baseline = {
        "schema_version": 1,
        "tool": "bandit",
        "findings": [
            {
                "test_id": "B608",
                "filename": "src/finjuice/sample.py",
                "function": "build_select",
                "rationale": "reviewed existing DuckDB query builder",
            }
        ],
    }

    diff = check_security_baselines.compare_bandit_findings(current, baseline)

    assert diff.failed
    assert [finding.function for finding in diff.new] == ["build_delete"]


def test_pip_audit_compare_fails_for_added_vulnerability() -> None:
    """A dependency advisory that is not in the baseline should fail."""
    report = {
        "dependencies": [
            {
                "name": "example",
                "version": "1.2.3",
                "vulns": [
                    {
                        "id": "GHSA-test-1234",
                        "aliases": ["CVE-2099-0001"],
                        "affected_versions": "<1.2.4",
                        "fix_versions": ["1.2.4"],
                    }
                ],
            }
        ]
    }
    current = check_security_baselines.normalize_pip_audit_report(report)
    baseline = {"schema_version": 1, "tool": "pip-audit", "findings": []}

    diff = check_security_baselines.compare_pip_audit_findings(current, baseline)

    assert diff.failed
    assert diff.new[0].package == "example"
    assert diff.new[0].vulnerability_id == "GHSA-test-1234"


def test_pip_audit_compare_rejects_baseline_without_rationale() -> None:
    """Accepted vulnerability baselines must document the review rationale."""
    baseline = {
        "schema_version": 1,
        "tool": "pip-audit",
        "findings": [
            {
                "id": "GHSA-test-1234",
                "package": "example",
                "affected_versions": "<1.2.4",
                "rationale": "",
            }
        ],
    }

    result = check_security_baselines.validate_baseline_document(
        baseline,
        tool="pip-audit",
        required_fields=("id", "package", "affected_versions"),
    )

    assert not result.valid
    assert "rationale" in result.errors[0]


def _bandit_report_for(source: Path, line_number: int) -> dict:
    """Build a minimal raw Bandit report for one B608 finding."""
    return {
        "results": [
            {
                "test_id": "B608",
                "test_name": "hardcoded_sql_expressions",
                "filename": str(source),
                "line_number": line_number,
                "issue_severity": "MEDIUM",
                "issue_confidence": "LOW",
                "issue_text": "Possible SQL injection vector.",
            }
        ]
    }


def test_rebase_bandit_paths_repoints_a_moved_finding(tmp_path: Path) -> None:
    """A finding moved to a new file should be re-pointed, keeping the rationale."""
    source = tmp_path / "src" / "finjuice" / "moved.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "def build_select(table):\n    return 'SELECT * FROM ' + table\n",
        encoding="utf-8",
    )
    current = check_security_baselines.normalize_bandit_report(
        _bandit_report_for(source, 2), root=tmp_path
    )
    baseline = {
        "schema_version": 1,
        "tool": "bandit",
        "findings": [
            {
                "test_id": "B608",
                "filename": "src/finjuice/original.py",
                "function": "build_select",
                "issue_severity": "MEDIUM",
                "issue_confidence": "LOW",
                "rationale": "parametrized DuckDB SQL builder, reviewed",
            }
        ],
    }

    rebased, migrations = check_security_baselines.rebase_bandit_paths(current, baseline)

    assert len(migrations) == 1
    assert rebased[0]["filename"] == "src/finjuice/moved.py"
    assert rebased[0]["rationale"] == "parametrized DuckDB SQL builder, reviewed"


def test_rebase_bandit_paths_skips_ambiguous_matches(tmp_path: Path) -> None:
    """Two findings sharing an identity must not be silently re-pointed."""
    source = tmp_path / "src" / "finjuice" / "moved.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "def build_select(table):\n"
        "    one = 'SELECT * FROM ' + table\n"
        "    two = 'SELECT 1 FROM ' + table\n"
        "    return one, two\n",
        encoding="utf-8",
    )
    report = {
        "results": [
            _bandit_report_for(source, 2)["results"][0],
            _bandit_report_for(source, 3)["results"][0],
        ]
    }
    current = check_security_baselines.normalize_bandit_report(report, root=tmp_path)
    baseline = {
        "schema_version": 1,
        "tool": "bandit",
        "findings": [
            {
                "test_id": "B608",
                "filename": "src/finjuice/original.py",
                "function": "build_select",
                "rationale": "reviewed",
            }
        ],
    }

    rebased, migrations = check_security_baselines.rebase_bandit_paths(current, baseline)

    assert migrations == []
    assert rebased[0]["filename"] == "src/finjuice/original.py"


def test_write_bandit_baseline_keeps_identity_fields_inline(tmp_path: Path) -> None:
    """The baseline writer must preserve the compact identity_fields layout."""
    document = {
        "schema_version": 1,
        "tool": "bandit",
        "identity_fields": ["test_id", "filename", "function"],
        "findings": [],
    }
    target = tmp_path / "bandit-baseline.json"

    check_security_baselines.write_bandit_baseline(target, document)
    text = target.read_text(encoding="utf-8")

    assert '"identity_fields": ["test_id", "filename", "function"]' in text
    assert text.endswith("\n")


def test_self_test_proves_added_findings_fail_closed(capsys) -> None:
    """The CLI self-test should pass only when synthetic findings fail comparison."""
    exit_code = check_security_baselines.main(["--self-test"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "fail-closed self-test passed" in captured.out
