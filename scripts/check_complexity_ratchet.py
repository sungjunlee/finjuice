#!/usr/bin/env python3
"""Ruff-backed ratchet for existing complexity debt."""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

RULES = ("C901", "PLR0911", "PLR0912", "PLR0913", "PLR0915")
DEFAULT_PATHS = (Path("src"), Path("scripts"), Path("tests"), Path("tools"))
DEFAULT_BASELINE = Path("tools/ruff_complexity_baseline.json")
METRIC_RE = re.compile(r"\((?P<value>\d+) > (?P<limit>\d+)\)")


@dataclass(frozen=True)
class Finding:
    """A normalized Ruff complexity finding."""

    code: str
    path: str
    row: int
    column: int
    symbol: str | None
    message: str
    value: int | None
    limit: int | None

    @property
    def key(self) -> str:
        """Return the ratchet key used to survive ordinary line churn."""
        if self.symbol:
            return f"{self.code}|{self.path}|{self.symbol}"
        return f"{self.code}|{self.path}|{self.row}:{self.column}"

    @property
    def sort_key(self) -> tuple[str, str, str, int, int]:
        """Return a deterministic ordering key."""
        return (self.path, self.symbol or "", self.code, self.row, self.column)

    def to_baseline_record(self) -> dict[str, Any]:
        """Serialize a finding for the reviewable baseline file."""
        return {
            "code": self.code,
            "path": self.path,
            "symbol": self.symbol,
            "row": self.row,
            "column": self.column,
            "value": self.value,
            "limit": self.limit,
            "message": self.message,
        }


@dataclass(frozen=True)
class SymbolSpan:
    """A Python symbol span collected from AST."""

    name: str
    start: int
    end: int


@dataclass(frozen=True)
class RatchetDiff:
    """Current findings compared to the committed baseline."""

    new: tuple[Finding, ...]
    worsened: tuple[tuple[Finding, Finding], ...]
    improved: tuple[tuple[Finding, Finding], ...]
    resolved: tuple[Finding, ...]

    @property
    def failed(self) -> bool:
        """Return whether the ratchet should fail."""
        return bool(self.new or self.worsened)


class SymbolVisitor(ast.NodeVisitor):
    """Collect dotted class/function symbols with line spans."""

    def __init__(self) -> None:
        self.stack: list[str] = []
        self.spans: list[SymbolSpan] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802 - ast visitor API
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802 - ast visitor API
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        self._visit_function(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        symbol = ".".join([*self.stack, node.name])
        self.spans.append(SymbolSpan(symbol, node.lineno, node.end_lineno or node.lineno))
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description="Fail when Ruff complexity debt is new or worse than the baseline."
    )
    parser.add_argument("paths", nargs="*", type=Path, help="Paths to scan with Ruff.")
    parser.add_argument(
        "--baseline",
        type=Path,
        default=DEFAULT_BASELINE,
        help="Complexity baseline JSON path.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Repository root used for stable relative paths.",
    )
    parser.add_argument("--ruff", default="ruff", help="Ruff executable to run.")
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="Rewrite the baseline to the current Ruff findings.",
    )
    parser.add_argument(
        "--rebase-paths",
        action="store_true",
        help=(
            "Re-point baseline file paths for findings that a refactor moved to a "
            "new path without changing their measured value (a pure path migration), "
            "then fail only on genuinely new or worsened debt. Use after a code move "
            "to avoid the CI-fail / manual-edit / CI-pass loop."
        ),
    )
    args = parser.parse_args(argv)

    root = args.root.resolve()
    paths = tuple(args.paths or DEFAULT_PATHS)
    findings = collect_findings(paths, root=root, ruff=args.ruff)

    if args.update_baseline:
        write_baseline(args.baseline, findings, paths=paths)
        print(f"Updated {args.baseline} with {len(findings)} Ruff complexity findings")
        return 0

    baseline = read_baseline(args.baseline)

    if args.rebase_paths:
        baseline, migrations = rebase_paths(findings, baseline)
        if migrations:
            write_baseline(args.baseline, baseline, paths=paths)
            print(f"Re-pointed {len(migrations)} baseline path(s) after a refactor:")
            for old, new in migrations:
                print(f"  {old.code} {old.symbol}: {old.path} -> {new.path}")
        else:
            print("No path migrations detected; baseline left unchanged.")

    diff = compare_findings(findings, baseline)
    if diff.failed:
        print("Complexity ratchet failed.", file=sys.stderr)
        _print_failures(diff, file=sys.stderr)
        print(
            "Refactor the new/worse hotspot, or update the baseline only for accepted debt.",
            file=sys.stderr,
        )
        return 1

    print(f"Complexity ratchet passed: {len(findings)} current findings covered")
    if diff.improved or diff.resolved:
        improved_count = len(diff.improved) + len(diff.resolved)
        print(
            f"Baseline can be reduced for {improved_count} finding(s); "
            "run with --update-baseline after reviewing the improvement."
        )
    return 0


def collect_findings(paths: Sequence[Path], *, root: Path, ruff: str) -> list[Finding]:
    """Run Ruff and return normalized complexity findings."""
    command = [
        ruff,
        "check",
        *[str(path) for path in paths],
        "--select",
        ",".join(RULES),
        "--output-format",
        "json",
    ]
    try:
        result = subprocess.run(command, cwd=root, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        print(f"Could not find Ruff executable: {ruff}", file=sys.stderr)
        raise SystemExit(2) from None

    if result.returncode not in {0, 1}:
        print(result.stderr.strip() or result.stdout.strip(), file=sys.stderr)
        raise SystemExit(result.returncode)

    raw_findings = json.loads(result.stdout or "[]")
    symbol_cache: dict[str, list[SymbolSpan]] = {}
    findings = [
        _finding_from_ruff(item, root=root, symbol_cache=symbol_cache) for item in raw_findings
    ]
    return sorted(findings, key=lambda finding: finding.sort_key)


def read_baseline(path: Path) -> list[Finding]:
    """Read baseline findings."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"Missing complexity baseline: {path}", file=sys.stderr)
        raise SystemExit(1) from None

    findings = data.get("findings")
    if not isinstance(findings, list):
        print(f"Invalid complexity baseline, expected findings list: {path}", file=sys.stderr)
        raise SystemExit(1)
    return [_finding_from_baseline(item) for item in findings]


def write_baseline(path: Path, findings: Sequence[Finding], *, paths: Sequence[Path]) -> None:
    """Write the current findings as the deterministic baseline."""
    document = {
        "description": "Ruff complexity ratchet baseline for existing debt.",
        "rules": list(RULES),
        "paths": [path.as_posix() for path in paths],
        "comparison_key": ["code", "path", "symbol"],
        "ratchet": "New rule/path/symbol findings or higher measured values fail.",
        "generated_by": "uv run python scripts/check_complexity_ratchet.py --update-baseline",
        "findings": [finding.to_baseline_record() for finding in findings],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def compare_findings(current: Sequence[Finding], baseline: Sequence[Finding]) -> RatchetDiff:
    """Compare current Ruff findings against the baseline."""
    current_by_key = _findings_by_key(current)
    baseline_by_key = _findings_by_key(baseline)

    new = tuple(
        current_by_key[key] for key in sorted(current_by_key.keys() - baseline_by_key.keys())
    )
    resolved = tuple(
        baseline_by_key[key] for key in sorted(baseline_by_key.keys() - current_by_key.keys())
    )
    worsened: list[tuple[Finding, Finding]] = []
    improved: list[tuple[Finding, Finding]] = []

    for key in sorted(current_by_key.keys() & baseline_by_key.keys()):
        current_finding = current_by_key[key]
        baseline_finding = baseline_by_key[key]
        if _is_worse(current_finding, baseline_finding):
            worsened.append((current_finding, baseline_finding))
        elif _is_better(current_finding, baseline_finding):
            improved.append((current_finding, baseline_finding))

    return RatchetDiff(new, tuple(worsened), tuple(improved), resolved)


def rebase_paths(
    current: Sequence[Finding], baseline: Sequence[Finding]
) -> tuple[list[Finding], list[tuple[Finding, Finding]]]:
    """Re-point baseline paths for findings a refactor moved without worsening.

    A path migration is a baseline finding that disappeared from its old path
    while an identical finding — same ``(code, symbol, value, limit)`` — appeared
    at a new path. Only unambiguous one-to-one matches are rebased; genuinely new
    debt is left for the ratchet to fail on.

    Returns the rebased baseline and the ``(old, new)`` pairs that moved.
    """
    diff = compare_findings(current, baseline)

    def migration_key(finding: Finding) -> tuple[str, str | None, int | None, int | None]:
        return (finding.code, finding.symbol, finding.value, finding.limit)

    new_by_key: dict[tuple[str, str | None, int | None, int | None], list[Finding]] = {}
    resolved_by_key: dict[tuple[str, str | None, int | None, int | None], list[Finding]] = {}
    for finding in diff.new:
        new_by_key.setdefault(migration_key(finding), []).append(finding)
    for finding in diff.resolved:
        resolved_by_key.setdefault(migration_key(finding), []).append(finding)

    migrations: list[tuple[Finding, Finding]] = []
    for key, new_findings in new_by_key.items():
        resolved_findings = resolved_by_key.get(key, [])
        # Only rebase a confident 1:1 move of a named symbol to a new path.
        if len(new_findings) != 1 or len(resolved_findings) != 1:
            continue
        new_finding = new_findings[0]
        old_finding = resolved_findings[0]
        if new_finding.symbol is None or new_finding.path == old_finding.path:
            continue
        migrations.append((old_finding, new_finding))

    rebased = list(baseline)
    for old_finding, new_finding in migrations:
        rebased[rebased.index(old_finding)] = new_finding
    rebased.sort(key=lambda finding: finding.sort_key)
    return rebased, migrations


def _finding_from_ruff(
    item: Mapping[str, Any], *, root: Path, symbol_cache: dict[str, list[SymbolSpan]]
) -> Finding:
    location = item["location"]
    row = int(location["row"])
    column = int(location["column"])
    path = _relative_path(Path(str(item["filename"])), root)
    spans = symbol_cache.setdefault(path, _collect_symbols(root / path))
    value, limit = _metric_from_message(str(item["message"]))
    return Finding(
        code=str(item["code"]),
        path=path,
        row=row,
        column=column,
        symbol=_symbol_for_row(spans, row),
        message=str(item["message"]),
        value=value,
        limit=limit,
    )


def _finding_from_baseline(item: Mapping[str, Any]) -> Finding:
    return Finding(
        code=str(item["code"]),
        path=str(item["path"]),
        row=int(item["row"]),
        column=int(item["column"]),
        symbol=str(item["symbol"]) if item.get("symbol") is not None else None,
        message=str(item["message"]),
        value=_optional_int(item.get("value")),
        limit=_optional_int(item.get("limit")),
    )


def _collect_symbols(path: Path) -> list[SymbolSpan]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError):
        return []
    visitor = SymbolVisitor()
    visitor.visit(tree)
    return visitor.spans


def _symbol_for_row(spans: Sequence[SymbolSpan], row: int) -> str | None:
    matches = [span for span in spans if span.start <= row <= span.end]
    if not matches:
        return None
    return max(matches, key=lambda span: (span.start, len(span.name))).name


def _metric_from_message(message: str) -> tuple[int | None, int | None]:
    match = METRIC_RE.search(message)
    if match is None:
        return None, None
    return int(match.group("value")), int(match.group("limit"))


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _findings_by_key(findings: Sequence[Finding]) -> dict[str, Finding]:
    findings_by_key: dict[str, Finding] = {}
    for finding in findings:
        if finding.key in findings_by_key:
            print(f"Duplicate complexity ratchet key: {finding.key}", file=sys.stderr)
            raise SystemExit(1)
        findings_by_key[finding.key] = finding
    return findings_by_key


def _is_worse(current: Finding, baseline: Finding) -> bool:
    return (
        current.value is not None and baseline.value is not None and current.value > baseline.value
    )


def _is_better(current: Finding, baseline: Finding) -> bool:
    return (
        current.value is not None and baseline.value is not None and current.value < baseline.value
    )


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _print_failures(diff: RatchetDiff, *, file: Any) -> None:
    if diff.new:
        print("New complexity findings:", file=file)
        for finding in diff.new:
            print(f"  {_format_finding(finding)}", file=file)
    if diff.worsened:
        print("Worsened complexity findings:", file=file)
        for current, baseline in diff.worsened:
            print(
                f"  {_format_finding(current)} "
                f"(baseline value: {baseline.value}, current value: {current.value})",
                file=file,
            )


def _format_finding(finding: Finding) -> str:
    symbol = f" {finding.symbol}" if finding.symbol else ""
    location = f"{finding.path}:{finding.row}:{finding.column}"
    return f"{location}: {finding.code}{symbol} {finding.message}"


if __name__ == "__main__":
    raise SystemExit(main())
