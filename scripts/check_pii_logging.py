#!/usr/bin/env python3
"""Static checker for financial PII in logger calls.

The checker intentionally parses Python instead of grepping text. It only
inspects logger call arguments, so schema docs, fixtures, variable declarations,
and ordinary non-logging references to financial fields do not fail the gate.
"""

from __future__ import annotations

import argparse
import ast
import io
import re
import sys
import tokenize
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

LOGGER_METHODS = {
    "critical",
    "debug",
    "error",
    "exception",
    "info",
    "log",
    "warn",
    "warning",
}
DEFAULT_SCAN_PATHS = (Path("src"), Path("scripts"), Path("tests"))
EXCLUDED_DIR_NAMES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "data",
    "exports",
    "htmlcov",
    "venv",
}
ALLOW_MARKER = "finjuice-pii-log-allow:"
MIN_ALLOW_REASON_LENGTH = 12
SENSITIVE_TOKENS = {
    "account": "account",
    "accounts": "account",
    "amount": "amount",
    "amounts": "amount",
    "balance": "balance",
    "balances": "balance",
    "counterparty": "merchant",
    "memo": "memo",
    "memos": "memo",
    "merchant": "merchant",
    "merchants": "merchant",
}
SENSITIVE_FIELD_ALIASES = {
    "account_name": "account",
    "account_number": "account",
    "account_id": "account",
    "archive_path": "path",
    "archived_path": "path",
    "balance": "balance",
    "counterparty": "merchant",
    "data_dir": "path",
    "data_directory": "path",
    "export_path": "path",
    "import_path": "path",
    "imported_from": "path",
    "merchant_name": "merchant",
    "memo_raw": "memo",
    "memo_text": "memo",
    "merchant_raw": "merchant",
    "original_filename": "filename",
    "output_path": "path",
    "source_file_path": "path",
    "source_path": "path",
}
SENSITIVE_PATH_IDENTIFIERS = {
    "archive_path": "path",
    "archived_path": "path",
    "data_dir": "path",
    "data_directory": "path",
    "export_path": "path",
    "file_path": "path",
    "file_name": "filename",
    "filename": "filename",
    "import_path": "path",
    "imported_from": "path",
    "original_filename": "filename",
    "output_path": "path",
    "raw_path": "path",
    "source_file_path": "path",
    "source_path": "path",
}
RAW_RECORD_NAMES = {
    "record",
    "row",
    "row_dict",
    "rows",
    "transaction",
    "transaction_data",
    "transaction_dict",
    "transactions",
    "tx",
    "txn",
    "txn_dict",
}
SAFE_IDENTIFIERS = {
    "amount_ratio",
    "amount_tolerance",
    "default_transfer_amount_tolerance",
    "has_account",
    "has_amount",
    "has_balance",
    "has_memo",
    "has_merchant",
    "max_reasonable_amount_krw",
    "min_reasonable_amount_krw",
    "path_kind",
}
SAFE_CALL_NAMES = {"bool", "len", "type"}
PATH_EXCEPTION_TYPES = {
    "FileExistsError",
    "FileNotFoundError",
    "IOError",
    "IsADirectoryError",
    "NotADirectoryError",
    "OSError",
    "PermissionError",
}
PATH_EXCEPTION_HANDLER_MARKER = "__path_exception_handler__"


@dataclass(frozen=True)
class LoggingIssue:
    """A sanitized PII logging finding."""

    path: Path
    line: int
    column: int
    sensitive_name: str
    reason: str


@dataclass(frozen=True)
class SensitiveReference:
    """Sensitive reference found inside a logger argument."""

    sensitive_name: str
    reason: str


class PiiLoggingVisitor(ast.NodeVisitor):
    """Find logger calls that pass sensitive values to logging."""

    def __init__(self, path: Path, comments_by_line: dict[int, list[str]]) -> None:
        self.path = path
        self.comments_by_line = comments_by_line
        self.issues: list[LoggingIssue] = []
        self.path_exception_names: list[set[str]] = []

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802 - ast visitor API
        logger_method = _logger_method(node)
        if logger_method is None:
            self.generic_visit(node)
            return

        if _has_allow_comment(node, self.comments_by_line):
            return

        args = list(node.args)
        if logger_method == "log" and args:
            args = args[1:]

        references: list[SensitiveReference] = []
        for arg in args:
            references.extend(_sensitive_references(arg, self._current_path_exception_names()))
        for keyword in node.keywords:
            references.extend(self._sensitive_keyword_references(keyword))
        if logger_method == "exception" and self._current_path_exception_names():
            references.append(
                SensitiveReference(
                    sensitive_name="path",
                    reason="logger call includes traceback for path-bearing exception",
                )
            )

        seen: set[tuple[str, str]] = set()
        for reference in references:
            key = (reference.sensitive_name, reference.reason)
            if key in seen:
                continue
            seen.add(key)
            self.issues.append(
                LoggingIssue(
                    path=self.path,
                    line=node.lineno,
                    column=node.col_offset + 1,
                    sensitive_name=reference.sensitive_name,
                    reason=reference.reason,
                )
            )

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:  # noqa: N802 - ast visitor API
        names = set(self._current_path_exception_names())
        if _is_path_exception_handler(node.type):
            names.add(PATH_EXCEPTION_HANDLER_MARKER)
            if node.name:
                names.add(node.name)
        self.path_exception_names.append(names)
        for statement in node.body:
            self.visit(statement)
        self.path_exception_names.pop()

    def visit_Try(self, node: ast.Try) -> None:  # noqa: N802 - ast visitor API
        for statement in node.body:
            self.visit(statement)

        for handler in node.handlers:
            self.visit(handler)

        for statement in [*node.orelse, *node.finalbody]:
            self.visit(statement)

    def _current_path_exception_names(self) -> set[str]:
        if not self.path_exception_names:
            return set()
        return self.path_exception_names[-1]

    def _sensitive_keyword_references(self, keyword: ast.keyword) -> list[SensitiveReference]:
        path_exception_names = self._current_path_exception_names()
        if keyword.arg not in {"exc_info", "stack_info", "stacklevel"}:
            return _sensitive_references(keyword.value, path_exception_names)
        if (
            keyword.arg == "exc_info"
            and path_exception_names
            and _is_truthy_constant(keyword.value)
        ):
            return [
                SensitiveReference(
                    sensitive_name="path",
                    reason="logger call includes traceback for path-bearing exception",
                )
            ]
        return []


def iter_python_files(paths: Iterable[Path]) -> Iterator[Path]:
    """Yield Python files under paths, excluding private data/export directories."""
    candidates: list[Path] = []
    for path in paths:
        if not path.exists():
            continue
        if path.is_file():
            candidates.append(path)
            continue
        candidates.extend(sorted(path.rglob("*.py")))

    for candidate in sorted(candidates):
        if candidate.suffix != ".py" or _is_excluded(candidate):
            continue
        yield candidate


def check_paths(paths: Iterable[Path], *, root: Path | None = None) -> list[LoggingIssue]:
    """Check all Python files under paths."""
    base = root or Path.cwd()
    issues: list[LoggingIssue] = []
    for path in iter_python_files(paths):
        issues.extend(check_file(path, root=base))
    return issues


def check_file(path: Path, *, root: Path | None = None) -> list[LoggingIssue]:
    """Check one Python file for risky logger calls."""
    display_path = _display_path(path, root)
    source = path.read_text(encoding="utf-8")
    comments_by_line = _comments_by_line(source)

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return [
            LoggingIssue(
                path=display_path,
                line=exc.lineno or 1,
                column=exc.offset or 1,
                sensitive_name="syntax",
                reason="could not parse Python file",
            )
        ]

    visitor = PiiLoggingVisitor(display_path, comments_by_line)
    visitor.visit(tree)
    return visitor.issues


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description="Check Python logger calls for financial PII references."
    )
    parser.add_argument("paths", nargs="*", type=Path, help="Files or directories to scan.")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Path used to render relative locations in findings.",
    )
    args = parser.parse_args(argv)

    paths = args.paths or list(DEFAULT_SCAN_PATHS)
    issues = check_paths(paths, root=args.root)
    if not issues:
        print("PII logging check passed")
        return 0

    print("PII logging check failed:", file=sys.stderr)
    for issue in issues:
        print(
            f"{issue.path}:{issue.line}:{issue.column}: {issue.reason}",
            file=sys.stderr,
        )
    print(
        f"False positive escape hatch: add '# {ALLOW_MARKER} <reason>' on the line "
        "before the specific logger call.",
        file=sys.stderr,
    )
    return 1


def _is_excluded(path: Path) -> bool:
    return any(part in EXCLUDED_DIR_NAMES for part in path.parts)


def _display_path(path: Path, root: Path | None) -> Path:
    if root is None:
        return path
    try:
        return path.resolve().relative_to(root.resolve())
    except ValueError:
        return path


def _comments_by_line(source: str) -> dict[int, list[str]]:
    comments: dict[int, list[str]] = {}
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT:
            comments.setdefault(token.start[0], []).append(token.string)
    return comments


def _has_allow_comment(node: ast.AST, comments_by_line: dict[int, list[str]]) -> bool:
    start_line = getattr(node, "lineno", 0)
    end_line = getattr(node, "end_lineno", start_line)
    candidate_lines = [start_line - 1, *range(start_line, end_line + 1)]
    for line in candidate_lines:
        for comment in comments_by_line.get(line, []):
            marker_index = comment.find(ALLOW_MARKER)
            if marker_index == -1:
                continue
            reason = comment[marker_index + len(ALLOW_MARKER) :].strip()
            if len(reason) >= MIN_ALLOW_REASON_LENGTH:
                return True
    return False


def _logger_method(node: ast.Call) -> str | None:
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr not in LOGGER_METHODS:
        return None
    if _is_logger_object(func.value):
        return func.attr
    return None


def _is_logger_object(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return node.id == "logging" or node.id == "logger" or node.id.endswith("_logger")
    if isinstance(node, ast.Attribute):
        return node.attr == "logger"
    return False


def _sensitive_references(
    node: ast.AST, path_exception_names: set[str] | None = None
) -> list[SensitiveReference]:
    path_exception_names = path_exception_names or set()
    if _is_safe_call(node):
        return []

    if isinstance(node, ast.JoinedStr):
        references: list[SensitiveReference] = []
        for value in node.values:
            if isinstance(value, ast.FormattedValue):
                references.extend(_sensitive_references(value.value, path_exception_names))
        return references

    if isinstance(node, ast.FormattedValue):
        return _sensitive_references(node.value, path_exception_names)

    if isinstance(node, ast.Name):
        reference = _reference_from_identifier(node.id)
        return [reference] if reference else []

    if isinstance(node, ast.Attribute):
        reference = _reference_from_identifier(node.attr)
        references = [reference] if reference else []
        references.extend(_sensitive_references(node.value, path_exception_names))
        return _dedupe_references(references)

    if isinstance(node, ast.Subscript):
        reference = _reference_from_subscript(node)
        references = [reference] if reference else []
        if not isinstance(node.slice, ast.Constant):
            references.extend(_sensitive_references(node.slice, path_exception_names))
        return references

    if isinstance(node, ast.Call):
        mapping_reference = _reference_from_mapping_get(node)
        references = [mapping_reference] if mapping_reference else []
        for arg in node.args:
            references.extend(_sensitive_references(arg, path_exception_names))
        for keyword in node.keywords:
            references.extend(_sensitive_references(keyword.value, path_exception_names))
        return _dedupe_references(references)

    if isinstance(node, ast.Dict):
        references = []
        for key, value in zip(node.keys, node.values):
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                reference = _reference_from_field_name(key.value)
                if reference:
                    references.append(reference)
            references.extend(_sensitive_references(value, path_exception_names))
        return _dedupe_references(references)

    if isinstance(node, ast.BinOp):
        return _dedupe_references(
            [
                *_sensitive_references(node.left, path_exception_names),
                *_sensitive_references(node.right, path_exception_names),
            ]
        )

    if isinstance(node, (ast.List, ast.Set, ast.Tuple)):
        references = []
        for element in node.elts:
            references.extend(_sensitive_references(element, path_exception_names))
        return _dedupe_references(references)

    if isinstance(node, ast.UnaryOp):
        return _sensitive_references(node.operand, path_exception_names)

    if isinstance(node, ast.IfExp):
        return _dedupe_references(
            [
                *_sensitive_references(node.body, path_exception_names),
                *_sensitive_references(node.orelse, path_exception_names),
            ]
        )

    return []


def _is_safe_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    return isinstance(node.func, ast.Name) and node.func.id in SAFE_CALL_NAMES


def _is_truthy_constant(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and bool(node.value)


def _is_path_exception_handler(node: ast.AST | None) -> bool:
    if node is None:
        return False
    if isinstance(node, ast.Name):
        return node.id in PATH_EXCEPTION_TYPES
    if isinstance(node, ast.Attribute):
        return node.attr in PATH_EXCEPTION_TYPES
    if isinstance(node, ast.Tuple):
        return any(_is_path_exception_handler(element) for element in node.elts)
    return False


def _reference_from_mapping_get(node: ast.Call) -> SensitiveReference | None:
    if not isinstance(node.func, ast.Attribute) or node.func.attr != "get" or not node.args:
        return None
    first_arg = node.args[0]
    if not isinstance(first_arg, ast.Constant) or not isinstance(first_arg.value, str):
        return None
    return _reference_from_field_name(first_arg.value)


def _reference_from_subscript(node: ast.Subscript) -> SensitiveReference | None:
    key = node.slice
    if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
        return None
    return _reference_from_field_name(key.value)


def _reference_from_field_name(field_name: str) -> SensitiveReference | None:
    normalized = field_name.lower()
    sensitive_name = SENSITIVE_FIELD_ALIASES.get(normalized) or SENSITIVE_TOKENS.get(normalized)
    if sensitive_name is None:
        return None
    return SensitiveReference(
        sensitive_name=sensitive_name,
        reason=_sensitive_reason("field", sensitive_name),
    )


def _reference_from_identifier(identifier: str) -> SensitiveReference | None:
    normalized = identifier.lower()
    if normalized in SAFE_IDENTIFIERS:
        return None
    if normalized.endswith(("_count", "_counts")):
        return None
    raw_reference = _reference_from_raw_record_name(normalized)
    if raw_reference:
        return raw_reference
    path_reference = _reference_from_path_identifier(normalized)
    if path_reference:
        return path_reference
    return _reference_from_sensitive_identifier_tokens(identifier)


def _reference_from_raw_record_name(identifier: str) -> SensitiveReference | None:
    if identifier not in RAW_RECORD_NAMES:
        return None
    sensitive_name = "row" if identifier in {"record", "row", "row_dict", "rows"} else "transaction"
    return SensitiveReference(
        sensitive_name=sensitive_name,
        reason="logger argument references raw transaction/row object",
    )


def _reference_from_path_identifier(identifier: str) -> SensitiveReference | None:
    if identifier not in SENSITIVE_PATH_IDENTIFIERS:
        return None
    sensitive_name = SENSITIVE_PATH_IDENTIFIERS[identifier]
    return SensitiveReference(
        sensitive_name=sensitive_name,
        reason=_sensitive_reason("value", sensitive_name),
    )


def _reference_from_sensitive_identifier_tokens(identifier: str) -> SensitiveReference | None:
    for token in _identifier_tokens(identifier):
        if token == "filename":
            return SensitiveReference(
                sensitive_name="filename",
                reason=_sensitive_reason("value", "filename"),
            )
        if token in SENSITIVE_TOKENS:
            sensitive_name = SENSITIVE_TOKENS[token]
            return SensitiveReference(
                sensitive_name=sensitive_name,
                reason=f"logger argument references sensitive value '{sensitive_name}'",
            )
    return None


def _sensitive_reason(kind: str, sensitive_name: str) -> str:
    if sensitive_name in {"filename", "path"}:
        if kind == "field":
            return f"logger argument reads privacy-sensitive {sensitive_name} field"
        return f"logger argument references privacy-sensitive {sensitive_name}"
    if kind == "field":
        return f"logger argument reads sensitive field '{sensitive_name}'"
    return f"logger argument references sensitive value '{sensitive_name}'"


def _identifier_tokens(identifier: str) -> list[str]:
    words = re.sub(r"(?<!^)(?=[A-Z])", "_", identifier).lower()
    return [token for token in re.split(r"[^a-z0-9]+", words) if token]


def _dedupe_references(references: Iterable[SensitiveReference]) -> list[SensitiveReference]:
    deduped: list[SensitiveReference] = []
    seen: set[tuple[str, str]] = set()
    for reference in references:
        key = (reference.sensitive_name, reference.reason)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(reference)
    return deduped


if __name__ == "__main__":
    raise SystemExit(main())
