#!/usr/bin/env python3
"""Fail-closed security scan baseline comparator for Bandit and pip-audit."""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

DEFAULT_BANDIT_BASELINE = Path("security/bandit-baseline.json")
DEFAULT_PIP_AUDIT_BASELINE = Path("security/pip-audit-baseline.json")
DEFAULT_BANDIT_REPORT = Path("bandit-report.json")
DEFAULT_PIP_AUDIT_REPORT = Path("audit-report.json")
DEFAULT_REQUIREMENTS = Path("requirements-audit.txt")
PIP_AUDIT_SCOPES = ("local", "requirements")

BANDIT_SEVERITY_RANK = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}
PIP_AUDIT_SEVERITY_RANK = {
    "LOW": 1,
    "MODERATE": 2,
    "MEDIUM": 2,
    "HIGH": 3,
    "CRITICAL": 4,
}


@dataclass(frozen=True)
class SymbolSpan:
    """A dotted Python symbol span."""

    name: str
    start: int
    end: int


@dataclass(frozen=True)
class BaselineValidation:
    """Validation result for a reviewed baseline document."""

    valid: bool
    errors: tuple[str, ...]


@dataclass(frozen=True)
class BanditFinding:
    """A normalized Bandit finding with a stable review key."""

    test_id: str
    filename: str
    function: str
    issue_severity: str
    issue_confidence: str
    test_name: str
    issue_text: str
    line_number: int | None
    line_range: tuple[int, ...]

    @property
    def key(self) -> tuple[str, str, str]:
        """Return the baseline identity key."""
        return (self.test_id, self.filename, self.function)

    @property
    def sort_key(self) -> tuple[str, str, str, int]:
        """Return deterministic ordering."""
        return (self.filename, self.function, self.test_id, self.line_number or 0)


@dataclass(frozen=True)
class PipAuditFinding:
    """A normalized pip-audit vulnerability finding."""

    vulnerability_id: str
    package: str
    installed_version: str
    affected_versions: str
    fix_versions: tuple[str, ...]
    aliases: tuple[str, ...]
    severity: str | None

    @property
    def key(self) -> tuple[str, str, str]:
        """Return the baseline identity key."""
        return (self.vulnerability_id, self.package, self.affected_versions)

    @property
    def sort_key(self) -> tuple[str, str, str]:
        """Return deterministic ordering."""
        return (self.package, self.vulnerability_id, self.affected_versions)


@dataclass(frozen=True)
class SecurityDiff:
    """Current security findings compared to a reviewed baseline."""

    tool: str
    new: tuple[BanditFinding | PipAuditFinding, ...]
    worsened: tuple[tuple[BanditFinding | PipAuditFinding, Mapping[str, Any]], ...]
    resolved: tuple[Mapping[str, Any], ...]
    baseline_errors: tuple[str, ...] = ()
    current_count: int = 0

    @property
    def failed(self) -> bool:
        """Return whether the security gate should fail."""
        return bool(self.baseline_errors or self.new or self.worsened)


@dataclass(frozen=True)
class PipAuditScanConfig:
    """Configuration for a pip-audit subprocess run."""

    report_path: Path
    requirements_path: Path
    executable: str
    uv_executable: str
    scope: str
    compile_requirements: bool


@dataclass(frozen=True)
class ComparisonSpec:
    """Tool-specific comparison behavior."""

    tool: str
    baseline_key: Callable[[Mapping[str, Any]], tuple[str, str, str]]
    severity_rank: Mapping[str, int]
    current_severity: Callable[[BanditFinding | PipAuditFinding], str]
    baseline_severity: Callable[[Mapping[str, Any]], str]


class SymbolVisitor(ast.NodeVisitor):
    """Collect class and function spans for stable Bandit identities."""

    def __init__(self) -> None:
        self.stack: list[str] = []
        self.spans: list[SymbolSpan] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802 - ast visitor API
        name = ".".join([*self.stack, node.name])
        self.spans.append(SymbolSpan(name, node.lineno, node.end_lineno or node.lineno))
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802 - ast visitor API
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        self._visit_function(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        name = ".".join([*self.stack, node.name])
        self.spans.append(SymbolSpan(name, node.lineno, node.end_lineno or node.lineno))
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description="Fail on Bandit or pip-audit findings not covered by reviewed baselines."
    )
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Repository root.")
    parser.add_argument(
        "--bandit-baseline",
        type=Path,
        default=DEFAULT_BANDIT_BASELINE,
        help="Reviewed Bandit baseline JSON.",
    )
    parser.add_argument(
        "--pip-audit-baseline",
        type=Path,
        default=DEFAULT_PIP_AUDIT_BASELINE,
        help="Reviewed pip-audit baseline JSON.",
    )
    parser.add_argument(
        "--bandit-report",
        type=Path,
        default=DEFAULT_BANDIT_REPORT,
        help="Raw Bandit JSON report output path.",
    )
    parser.add_argument(
        "--pip-audit-report",
        type=Path,
        default=DEFAULT_PIP_AUDIT_REPORT,
        help="Raw pip-audit JSON report output path.",
    )
    parser.add_argument(
        "--requirements",
        type=Path,
        default=DEFAULT_REQUIREMENTS,
        help="Requirements file used when --pip-audit-scope=requirements.",
    )
    parser.add_argument("--bandit", default="bandit", help="Bandit executable.")
    parser.add_argument("--pip-audit", default="pip-audit", help="pip-audit executable.")
    parser.add_argument(
        "--uv",
        default="uv",
        help="uv executable used to compile the dependency audit requirements.",
    )
    parser.add_argument(
        "--pip-audit-scope",
        choices=PIP_AUDIT_SCOPES,
        default="local",
        help="Audit the installed local environment or a requirements file.",
    )
    parser.add_argument(
        "--compile-requirements",
        action="store_true",
        help="Regenerate --requirements with uv before a requirements-scoped audit.",
    )
    parser.add_argument("--skip-bandit", action="store_true", help="Skip the Bandit gate.")
    parser.add_argument("--skip-pip-audit", action="store_true", help="Skip the pip-audit gate.")
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Inject synthetic findings and assert the comparator fails closed.",
    )
    parser.add_argument(
        "--rebase-paths",
        action="store_true",
        help=(
            "Re-point Bandit baseline file paths for findings that a refactor moved "
            "to a new path without changing their severity (a pure path migration), "
            "then fail only on genuinely new findings. Reviewed rationales are kept. "
            "Use after a code move to avoid the CI-fail / manual-edit / CI-pass loop."
        ),
    )
    args = parser.parse_args(argv)

    if args.self_test:
        return run_self_test()

    root = args.root.resolve()

    if args.rebase_paths:
        return _rebase_bandit_baseline(root=root, args=args)

    diffs: list[SecurityDiff] = []

    try:
        if not args.skip_bandit:
            bandit_baseline = read_json(root / args.bandit_baseline)
            bandit_report = run_bandit_scan(
                root=root,
                report_path=root / args.bandit_report,
                executable=args.bandit,
            )
            bandit_findings = normalize_bandit_report(bandit_report, root=root)
            diffs.append(compare_bandit_findings(bandit_findings, bandit_baseline))

        if not args.skip_pip_audit:
            pip_audit_baseline = read_json(root / args.pip_audit_baseline)
            pip_audit_report = run_pip_audit_scan(
                root=root,
                config=PipAuditScanConfig(
                    report_path=root / args.pip_audit_report,
                    requirements_path=root / args.requirements,
                    executable=args.pip_audit,
                    uv_executable=args.uv,
                    scope=args.pip_audit_scope,
                    compile_requirements=args.compile_requirements,
                ),
            )
            pip_audit_findings = normalize_pip_audit_report(pip_audit_report)
            diffs.append(compare_pip_audit_findings(pip_audit_findings, pip_audit_baseline))
    except SecurityCheckError as error:
        print(str(error), file=sys.stderr)
        return 2

    failed = False
    for diff in diffs:
        if diff.failed:
            failed = True
            _print_diff(diff, file=sys.stderr)
        else:
            current_count = _covered_count(diff)
            print(f"{diff.tool} baseline gate passed: {current_count} current finding(s) covered")
            if diff.resolved:
                print(
                    f"{diff.tool}: {len(diff.resolved)} baseline finding(s) are no longer present; "
                    "prune after review."
                )

    if failed:
        print(
            "Security baseline gate failed. Fix the finding, or update the reviewed baseline "
            "with a rationale for accepted risk.",
            file=sys.stderr,
        )
        return 1
    return 0


class SecurityCheckError(RuntimeError):
    """Raised when the fail-closed gate cannot complete a scan or parse inputs."""


def read_json(path: Path) -> Mapping[str, Any]:
    """Read a JSON document or fail closed."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise SecurityCheckError(f"Missing required JSON file: {path}") from error
    except json.JSONDecodeError as error:
        raise SecurityCheckError(f"Invalid JSON in {path}: {error}") from error

    if not isinstance(data, Mapping):
        raise SecurityCheckError(f"Expected a JSON object in {path}")
    return data


def run_bandit_scan(*, root: Path, report_path: Path, executable: str) -> Mapping[str, Any]:
    """Run Bandit at the reviewed severity threshold and return the JSON report."""
    command = [
        executable,
        "-r",
        "src/",
        "-f",
        "json",
        "-o",
        str(report_path),
        "-ll",
    ]
    result = _run_command(command, root=root)
    if result.returncode not in {0, 1}:
        raise SecurityCheckError(_command_error("Bandit scan failed", result))
    return read_json(report_path)


def run_pip_audit_scan(
    *,
    root: Path,
    config: PipAuditScanConfig,
) -> Mapping[str, Any]:
    """Run pip-audit and return the JSON report."""
    if config.scope not in PIP_AUDIT_SCOPES:
        raise SecurityCheckError(f"Unsupported pip-audit scope: {config.scope}")

    command = [
        config.executable,
        "--format",
        "json",
        "--output",
        str(config.report_path),
        "--progress-spinner",
        "off",
    ]

    if config.scope == "local":
        command.insert(1, "--local")
        result = _run_command(command, root=root)
        if result.returncode not in {0, 1}:
            raise SecurityCheckError(_command_error("pip-audit scan failed", result))
        return read_json(config.report_path)

    if config.compile_requirements:
        compile_command = [
            config.uv_executable,
            "pip",
            "compile",
            "pyproject.toml",
            "-o",
            str(config.requirements_path),
        ]
        compile_result = _run_command(compile_command, root=root)
        if compile_result.returncode != 0:
            raise SecurityCheckError(
                _command_error("Could not compile requirements for pip-audit", compile_result)
            )

    if not config.requirements_path.exists():
        raise SecurityCheckError(
            f"Missing requirements file for pip-audit: {config.requirements_path}"
        )

    command[1:1] = ["-r", str(config.requirements_path)]
    result = _run_command(command, root=root)
    if result.returncode not in {0, 1}:
        raise SecurityCheckError(_command_error("pip-audit scan failed", result))
    return read_json(config.report_path)


def normalize_bandit_report(report: Mapping[str, Any], *, root: Path) -> list[BanditFinding]:
    """Normalize raw Bandit JSON into stable comparison records."""
    raw_results = report.get("results", [])
    if not isinstance(raw_results, list):
        raise SecurityCheckError("Invalid Bandit report: expected results list")

    symbol_cache: dict[str, list[SymbolSpan]] = {}
    findings = [
        _bandit_finding_from_raw(raw, root=root, symbol_cache=symbol_cache)
        for raw in raw_results
        if isinstance(raw, Mapping)
    ]
    return sorted(findings, key=lambda finding: finding.sort_key)


def normalize_pip_audit_report(report: Mapping[str, Any]) -> list[PipAuditFinding]:
    """Normalize raw pip-audit JSON into stable comparison records."""
    dependencies = report.get("dependencies", [])
    if not isinstance(dependencies, list):
        raise SecurityCheckError("Invalid pip-audit report: expected dependencies list")

    findings: list[PipAuditFinding] = []
    for dependency in dependencies:
        if not isinstance(dependency, Mapping):
            continue
        package = _string_value(dependency.get("name"))
        installed_version = _string_value(dependency.get("version"))
        vulns = dependency.get("vulns", [])
        if not isinstance(vulns, list):
            continue
        for vuln in vulns:
            if isinstance(vuln, Mapping):
                findings.append(
                    _pip_audit_finding_from_raw(
                        vuln,
                        package=package,
                        installed_version=installed_version,
                    )
                )
    return sorted(findings, key=lambda finding: finding.sort_key)


def validate_baseline_document(
    document: Mapping[str, Any],
    *,
    tool: str,
    required_fields: Sequence[str],
) -> BaselineValidation:
    """Validate common reviewed baseline fields."""
    errors: list[str] = []
    if document.get("schema_version") != 1:
        errors.append("baseline schema_version must be 1")
    if document.get("tool") != tool:
        errors.append(f"baseline tool must be {tool!r}")

    findings = document.get("findings")
    if not isinstance(findings, list):
        errors.append("baseline findings must be a list")
        return BaselineValidation(valid=False, errors=tuple(errors))

    for index, finding in enumerate(findings):
        if not isinstance(finding, Mapping):
            errors.append(f"baseline finding #{index + 1} must be an object")
            continue
        for field in required_fields:
            if not _string_value(finding.get(field)):
                errors.append(f"baseline finding #{index + 1} missing required field: {field}")
        if not _string_value(finding.get("rationale")):
            errors.append(f"baseline finding #{index + 1} missing required rationale")

    return BaselineValidation(valid=not errors, errors=tuple(errors))


def compare_bandit_findings(
    current: Sequence[BanditFinding],
    baseline: Mapping[str, Any],
) -> SecurityDiff:
    """Compare current Bandit findings against the reviewed baseline."""
    validation = validate_baseline_document(
        baseline,
        tool="bandit",
        required_fields=("test_id", "filename", "function"),
    )
    if not validation.valid:
        return SecurityDiff("bandit", (), (), (), validation.errors, len(current))

    baseline_records = baseline.get("findings", [])
    records = [record for record in baseline_records if isinstance(record, Mapping)]
    return _compare_findings(
        current=current,
        baseline_records=records,
        spec=ComparisonSpec(
            tool="bandit",
            baseline_key=_bandit_baseline_key,
            severity_rank=BANDIT_SEVERITY_RANK,
            current_severity=lambda finding: (
                finding.issue_severity if isinstance(finding, BanditFinding) else ""
            ),
            baseline_severity=lambda record: _string_value(record.get("issue_severity")),
        ),
    )


def rebase_bandit_paths(
    current: Sequence[BanditFinding],
    baseline: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[tuple[Mapping[str, Any], BanditFinding]]]:
    """Re-point Bandit baseline filenames for findings a refactor moved.

    A path migration is a baseline finding that disappeared from its old file
    while an identical finding — same ``(test_id, function)`` and, where the
    baseline records them, the same severity and confidence — appeared in a new
    file. Only unambiguous one-to-one matches are rebased; genuinely new findings
    are left for the gate to fail on. Reviewed ``rationale`` notes are preserved.

    Returns the rebased finding records and the ``(old_record, new_finding)``
    pairs that moved.
    """
    records = [r for r in baseline.get("findings", []) if isinstance(r, Mapping)]
    diff = compare_bandit_findings(current, baseline)
    resolved_records = [r for r in diff.resolved if isinstance(r, Mapping)]
    new_findings = [f for f in diff.new if isinstance(f, BanditFinding)]

    def migration_key(test_id: str, function: str) -> tuple[str, str]:
        return (test_id, function)

    new_by_key: dict[tuple[str, str], list[BanditFinding]] = defaultdict(list)
    resolved_by_key: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for finding in new_findings:
        new_by_key[migration_key(finding.test_id, finding.function)].append(finding)
    for record in resolved_records:
        key = migration_key(
            _string_value(record.get("test_id")), _string_value(record.get("function"))
        )
        resolved_by_key[key].append(record)

    migrations: list[tuple[Mapping[str, Any], BanditFinding]] = []
    for key, found in new_by_key.items():
        resolved = resolved_by_key.get(key, [])
        # Only rebase a confident 1:1 move to a new file.
        if len(found) != 1 or len(resolved) != 1:
            continue
        new_finding = found[0]
        old_record = resolved[0]
        if new_finding.filename == _string_value(old_record.get("filename")):
            continue
        if not _severity_matches(old_record, new_finding):
            continue
        migrations.append((old_record, new_finding))

    rebased: list[dict[str, Any]] = []
    moved_records = {id(old): new for old, new in migrations}
    for record in records:
        updated = dict(record)
        if id(record) in moved_records:
            updated["filename"] = moved_records[id(record)].filename
        rebased.append(updated)
    return rebased, migrations


def _severity_matches(record: Mapping[str, Any], finding: BanditFinding) -> bool:
    """Return whether a baseline record's recorded severity/confidence still fit."""
    recorded_severity = _string_value(record.get("issue_severity")).upper()
    recorded_confidence = _string_value(record.get("issue_confidence")).upper()
    if recorded_severity and recorded_severity != finding.issue_severity:
        return False
    return not (recorded_confidence and recorded_confidence != finding.issue_confidence)


def write_bandit_baseline(path: Path, document: Mapping[str, Any]) -> None:
    """Write a Bandit baseline document, preserving the compact field layout."""
    text = json.dumps(document, indent=2, ensure_ascii=False)
    # Keep identity_fields on one line to match the reviewed baseline layout.
    identity = document.get("identity_fields")
    if isinstance(identity, list):
        expanded = json.dumps(identity, indent=2, ensure_ascii=False)
        indented = "\n".join(
            ("  " + line if index else line) for index, line in enumerate(expanded.splitlines())
        )
        text = text.replace(indented, json.dumps(identity, ensure_ascii=False))
    path.write_text(text + "\n", encoding="utf-8")


def _rebase_bandit_baseline(*, root: Path, args: argparse.Namespace) -> int:
    """Run the Bandit scan, re-point migrated baseline paths, then re-check."""
    baseline_path = root / args.bandit_baseline
    try:
        baseline = read_json(baseline_path)
        report = run_bandit_scan(
            root=root,
            report_path=root / args.bandit_report,
            executable=args.bandit,
        )
    except SecurityCheckError as error:
        print(str(error), file=sys.stderr)
        return 2

    current = normalize_bandit_report(report, root=root)
    rebased_findings, migrations = rebase_bandit_paths(current, baseline)

    if migrations:
        new_document = dict(baseline)
        new_document["findings"] = rebased_findings
        write_bandit_baseline(baseline_path, new_document)
        print(f"Re-pointed {len(migrations)} Bandit baseline path(s) after a refactor:")
        for old_record, new_finding in migrations:
            old_path = _string_value(old_record.get("filename"))
            print(
                f"  {new_finding.test_id} {new_finding.function}: "
                f"{old_path} -> {new_finding.filename}"
            )
    else:
        print("No Bandit path migrations detected; baseline left unchanged.")
        new_document = dict(baseline)
        new_document["findings"] = rebased_findings

    diff = compare_bandit_findings(current, new_document)
    if diff.failed:
        _print_diff(diff, file=sys.stderr)
        print(
            "Security baseline gate still fails after rebase. Fix the finding, or update "
            "the reviewed baseline with a rationale for accepted risk.",
            file=sys.stderr,
        )
        return 1
    print(f"bandit baseline gate passed: {diff.current_count} current finding(s) covered")
    return 0


def compare_pip_audit_findings(
    current: Sequence[PipAuditFinding],
    baseline: Mapping[str, Any],
) -> SecurityDiff:
    """Compare current pip-audit findings against the reviewed baseline."""
    validation = validate_baseline_document(
        baseline,
        tool="pip-audit",
        required_fields=("id", "package", "affected_versions"),
    )
    if not validation.valid:
        return SecurityDiff("pip-audit", (), (), (), validation.errors, len(current))

    baseline_records = baseline.get("findings", [])
    records = [record for record in baseline_records if isinstance(record, Mapping)]
    return _compare_findings(
        current=current,
        baseline_records=records,
        spec=ComparisonSpec(
            tool="pip-audit",
            baseline_key=_pip_audit_baseline_key,
            severity_rank=PIP_AUDIT_SEVERITY_RANK,
            current_severity=lambda finding: (
                finding.severity
                if isinstance(finding, PipAuditFinding) and finding.severity
                else ""
            ),
            baseline_severity=lambda record: _string_value(record.get("severity")),
        ),
    )


def run_self_test() -> int:
    """Assert synthetic added findings are surfaced as failures."""
    bandit_report = {
        "results": [
            {
                "test_id": "B999",
                "test_name": "synthetic_bandit_check",
                "filename": "src/finjuice/synthetic.py",
                "line_number": 1,
                "issue_severity": "MEDIUM",
                "issue_confidence": "HIGH",
                "issue_text": "Synthetic fail-closed finding.",
            }
        ]
    }
    pip_audit_report = {
        "dependencies": [
            {
                "name": "synthetic-package",
                "version": "0.0.1",
                "vulns": [
                    {
                        "id": "GHSA-synthetic",
                        "affected_versions": "<0.0.2",
                        "fix_versions": ["0.0.2"],
                    }
                ],
            }
        ]
    }
    empty_bandit = {"schema_version": 1, "tool": "bandit", "findings": []}
    empty_pip_audit = {"schema_version": 1, "tool": "pip-audit", "findings": []}

    bandit = compare_bandit_findings(
        normalize_bandit_report(bandit_report, root=Path.cwd()),
        empty_bandit,
    )
    pip_audit = compare_pip_audit_findings(
        normalize_pip_audit_report(pip_audit_report),
        empty_pip_audit,
    )

    if bandit.failed and pip_audit.failed and bandit.new and pip_audit.new:
        print("fail-closed self-test passed: synthetic findings were rejected")
        return 0

    print("fail-closed self-test failed: synthetic findings were not rejected", file=sys.stderr)
    return 1


def _compare_findings(
    *,
    current: Sequence[BanditFinding | PipAuditFinding],
    baseline_records: Sequence[Mapping[str, Any]],
    spec: ComparisonSpec,
) -> SecurityDiff:
    current_by_key: dict[tuple[str, str, str], list[BanditFinding | PipAuditFinding]] = defaultdict(
        list
    )
    baseline_by_key: dict[tuple[str, str, str], list[Mapping[str, Any]]] = defaultdict(list)

    for finding in current:
        current_by_key[finding.key].append(finding)
    for record in baseline_records:
        baseline_by_key[spec.baseline_key(record)].append(record)

    new: list[BanditFinding | PipAuditFinding] = []
    worsened: list[tuple[BanditFinding | PipAuditFinding, Mapping[str, Any]]] = []
    resolved: list[Mapping[str, Any]] = []

    for key in sorted(current_by_key):
        current_items = sorted(current_by_key[key], key=_finding_sort_value)
        baseline_items = sorted(baseline_by_key.get(key, []), key=_record_sort_value)
        covered_count = min(len(current_items), len(baseline_items))
        for index in range(covered_count):
            current_item = current_items[index]
            baseline_item = baseline_items[index]
            current_rank = _rank_severity(spec.current_severity(current_item), spec.severity_rank)
            baseline_rank = _rank_severity(
                spec.baseline_severity(baseline_item), spec.severity_rank
            )
            if baseline_rank and current_rank > baseline_rank:
                worsened.append((current_item, baseline_item))
        if len(current_items) > len(baseline_items):
            new.extend(current_items[len(baseline_items) :])

    for key in sorted(baseline_by_key):
        current_count = len(current_by_key.get(key, []))
        baseline_items = sorted(baseline_by_key[key], key=_record_sort_value)
        if len(baseline_items) > current_count:
            resolved.extend(baseline_items[current_count:])

    return SecurityDiff(
        tool=spec.tool,
        new=tuple(sorted(new, key=_finding_sort_value)),
        worsened=tuple(sorted(worsened, key=lambda item: _finding_sort_value(item[0]))),
        resolved=tuple(sorted(resolved, key=_record_sort_value)),
        current_count=len(current),
    )


def _run_command(command: Sequence[str], *, root: Path) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, cwd=root, capture_output=True, text=True, check=False)
    except FileNotFoundError as error:
        raise SecurityCheckError(f"Could not find executable: {command[0]}") from error


def _command_error(message: str, result: subprocess.CompletedProcess[str]) -> str:
    output = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
    if output:
        return f"{message} (exit {result.returncode}):\n{output}"
    return f"{message} (exit {result.returncode})"


def _bandit_finding_from_raw(
    raw: Mapping[str, Any],
    *,
    root: Path,
    symbol_cache: dict[str, list[SymbolSpan]],
) -> BanditFinding:
    filename = _normalize_filename(raw.get("filename"), root=root)
    line_number = _int_value(raw.get("line_number"))
    line_range = tuple(
        item for item in (_int_value(value) for value in raw.get("line_range", [])) if item
    )
    function = _symbol_for_line(root / filename, line_number, symbol_cache=symbol_cache)
    return BanditFinding(
        test_id=_string_value(raw.get("test_id")),
        filename=filename,
        function=function,
        issue_severity=_string_value(raw.get("issue_severity")).upper(),
        issue_confidence=_string_value(raw.get("issue_confidence")).upper(),
        test_name=_string_value(raw.get("test_name")),
        issue_text=_string_value(raw.get("issue_text")),
        line_number=line_number,
        line_range=line_range,
    )


def _pip_audit_finding_from_raw(
    raw: Mapping[str, Any],
    *,
    package: str,
    installed_version: str,
) -> PipAuditFinding:
    affected_versions = _first_string(
        raw.get("affected_versions"),
        raw.get("vulnerable_versions"),
        raw.get("specifier"),
        f"installed=={installed_version or 'unknown'}",
    )
    return PipAuditFinding(
        vulnerability_id=_string_value(raw.get("id")),
        package=package,
        installed_version=installed_version,
        affected_versions=affected_versions,
        fix_versions=_string_tuple(raw.get("fix_versions")),
        aliases=_string_tuple(raw.get("aliases")),
        severity=_normalize_severity(raw.get("severity") or raw.get("cvss")),
    )


def _normalize_filename(value: Any, *, root: Path) -> str:
    raw = _string_value(value)
    path = Path(raw)
    if path.is_absolute():
        try:
            return path.resolve().relative_to(root).as_posix()
        except ValueError:
            return path.as_posix()
    return path.as_posix().removeprefix("./")


def _symbol_for_line(
    path: Path,
    line_number: int | None,
    *,
    symbol_cache: dict[str, list[SymbolSpan]],
) -> str:
    if not line_number:
        return "<module>"

    cache_key = path.as_posix()
    if cache_key not in symbol_cache:
        symbol_cache[cache_key] = _collect_symbol_spans(path)

    matches = [span for span in symbol_cache[cache_key] if span.start <= line_number <= span.end]
    if not matches:
        return "<module>"
    return max(matches, key=lambda span: (span.start, len(span.name))).name


def _collect_symbol_spans(path: Path) -> list[SymbolSpan]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return []
    visitor = SymbolVisitor()
    visitor.visit(tree)
    return visitor.spans


def _bandit_baseline_key(record: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        _string_value(record.get("test_id")),
        _string_value(record.get("filename")),
        _string_value(record.get("function")),
    )


def _pip_audit_baseline_key(record: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        _string_value(record.get("id")),
        _string_value(record.get("package")),
        _string_value(record.get("affected_versions")),
    )


def _covered_count(diff: SecurityDiff) -> int:
    return diff.current_count


def _print_diff(diff: SecurityDiff, *, file: TextIO) -> None:
    print(f"{diff.tool} baseline gate failed.", file=file)
    if diff.baseline_errors:
        print("Invalid reviewed baseline:", file=file)
        for error in diff.baseline_errors:
            print(f"  - {error}", file=file)
    if diff.new:
        print("New findings:", file=file)
        for finding in diff.new:
            print(f"  - {_format_finding(finding)}", file=file)
    if diff.worsened:
        print("Worsened findings:", file=file)
        for current, baseline in diff.worsened:
            baseline_severity = _string_value(
                baseline.get("issue_severity") or baseline.get("severity")
            )
            print(
                f"  - {_format_finding(current)} (baseline severity: {baseline_severity})",
                file=file,
            )


def _format_finding(finding: BanditFinding | PipAuditFinding) -> str:
    if isinstance(finding, BanditFinding):
        location = f"{finding.filename}:{finding.function}"
        line = f":{finding.line_number}" if finding.line_number else ""
        return (
            f"{finding.test_id} {location}{line} "
            f"{finding.issue_severity}/{finding.issue_confidence} {finding.test_name}"
        )
    fixes = f" fix={','.join(finding.fix_versions)}" if finding.fix_versions else ""
    return (
        f"{finding.vulnerability_id} {finding.package} "
        f"{finding.affected_versions} installed={finding.installed_version}{fixes}"
    )


def _finding_sort_value(finding: BanditFinding | PipAuditFinding) -> tuple[str, ...]:
    if isinstance(finding, BanditFinding):
        return (
            finding.filename,
            finding.function,
            finding.test_id,
            str(finding.line_number or 0),
        )
    return finding.sort_key


def _record_sort_value(record: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(str(record.get(key, "")) for key in sorted(record))


def _rank_severity(value: str | None, severity_rank: Mapping[str, int]) -> int:
    if not value:
        return 0
    return severity_rank.get(value.upper(), 0)


def _string_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _int_value(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value)
    return None


def _first_string(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _string_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(sorted(item.strip() for item in value if isinstance(item, str) and item.strip()))


def _normalize_severity(value: Any) -> str | None:
    result: str | None = None
    if isinstance(value, str) and value.strip():
        result = value.strip().upper()
    elif isinstance(value, Mapping):
        result = _normalize_severity(value.get("severity"))
    elif isinstance(value, list):
        scores = [
            float(item.get("score"))
            for item in value
            if isinstance(item, Mapping) and isinstance(item.get("score"), int | float)
        ]
        if scores:
            result = _severity_from_score(max(scores))
    return result


def _severity_from_score(score: float) -> str:
    if score >= 9:
        return "CRITICAL"
    if score >= 7:
        return "HIGH"
    if score >= 4:
        return "MEDIUM"
    return "LOW"


if __name__ == "__main__":
    raise SystemExit(main())
