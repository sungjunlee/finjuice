"""Tests for the PII-safe logging static checker."""

from __future__ import annotations

from pathlib import Path

from scripts import check_pii_logging


def _write_python(path: Path, source: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


def test_flags_logger_calls_with_sensitive_values(tmp_path: Path) -> None:
    """Logger calls should fail when they interpolate financial PII fields."""
    source = """
import logging

logger = logging.getLogger(__name__)


def run(amount, amounts, merchant_name, account):
    logger.info(f"amount={amount}")
    logger.info("amounts=%s", amounts)
    logger.warning("merchant=%s", merchant_name)
    logger.error("account=%s", account)
"""
    path = _write_python(tmp_path / "sample.py", source)

    issues = check_pii_logging.check_file(path, root=tmp_path)

    assert len(issues) == 4
    assert {issue.sensitive_name for issue in issues} == {"account", "amount", "merchant"}
    assert all(issue.path == Path("sample.py") for issue in issues)


def test_flags_raw_row_and_transaction_dicts(tmp_path: Path) -> None:
    """Raw row and transaction dicts should fail without printing the raw data."""
    source = """
import logging

logger = logging.getLogger(__name__)


def run(row, row_dict, transaction, transaction_data):
    logger.debug("row=%s", row)
    logger.debug("row_dict=%s", row_dict)
    logger.debug("transaction=%s", transaction_data)
    logger.info("memo=%s", transaction.get("memo_raw"))
    logger.warning("balance=%s", transaction["balance"])
"""
    path = _write_python(tmp_path / "sample.py", source)

    issues = check_pii_logging.check_file(path, root=tmp_path)

    assert len(issues) == 5
    assert [issue.sensitive_name for issue in issues] == [
        "row",
        "row",
        "transaction",
        "memo",
        "balance",
    ]


def test_flags_path_and_filename_logger_arguments(tmp_path: Path) -> None:
    """Source paths, filenames, archive paths, and data dirs are private metadata."""
    source = """
import logging

logger = logging.getLogger(__name__)


def run(source_file_path, original_filename, archived_path, data_dir):
    logger.info("source=%s", source_file_path)
    logger.info("filename=%s", original_filename)
    logger.info("archived=%s", archived_path)
    logger.info("data_dir=%s", data_dir)
"""
    path = _write_python(tmp_path / "sample.py", source)

    issues = check_pii_logging.check_file(path, root=tmp_path)

    assert len(issues) == 4
    assert {issue.sensitive_name for issue in issues} == {"filename", "path"}
    assert all("privacy-sensitive" in issue.reason for issue in issues)


def test_flags_source_name_and_config_data_dir_attributes(tmp_path: Path) -> None:
    """Common attribute forms should not bypass the path privacy check."""
    source = """
import logging

logger = logging.getLogger(__name__)


def run(source_file_path, archive_path, config):
    logger.warning("file=%s", source_file_path.name)
    logger.warning("archive=%s", archive_path.name)
    logger.warning("data=%s", config.data_dir)
"""
    path = _write_python(tmp_path / "sample.py", source)

    issues = check_pii_logging.check_file(path, root=tmp_path)

    assert len(issues) == 3
    assert {issue.sensitive_name for issue in issues} == {"path"}


def test_flags_generic_file_and_output_path_logger_arguments(tmp_path: Path) -> None:
    """Common file/output path names should not need bespoke source-specific entries."""
    source = """
import logging

logger = logging.getLogger(__name__)


def run(file_path, output_path, config):
    logger.warning("file=%s", file_path)
    logger.warning("name=%s", file_path.name)
    logger.warning("output=%s", output_path)
    logger.warning("config=%s", config.output_path)
"""
    path = _write_python(tmp_path / "sample.py", source)

    issues = check_pii_logging.check_file(path, root=tmp_path)

    assert len(issues) == 4
    assert {issue.sensitive_name for issue in issues} == {"path"}


def test_flags_path_bearing_exception_tracebacks(tmp_path: Path) -> None:
    """Tracebacks from path exceptions may contain raw local paths."""
    source = """
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def run(path: Path):
    try:
        path.exists()
    except OSError as exc:
        logger.exception("path operation failed")
    try:
        path.exists()
    except OSError as exc:
        logger.error("path operation failed", exc_info=True)
"""
    path = _write_python(tmp_path / "sample.py", source)

    issues = check_pii_logging.check_file(path, root=tmp_path)

    assert len(issues) == 2
    assert {issue.sensitive_name for issue in issues} == {"path"}
    assert all("traceback" in issue.reason for issue in issues)


def test_allows_counts_indices_boolean_presence_and_non_logging_references(
    tmp_path: Path,
) -> None:
    """Safe structural logging and non-logging references should not fail."""
    source = """
import logging

logger = logging.getLogger(__name__)


def run(transactions, row_idx, memo, amount, merchant):
    amount = amount + 1
    merchant = merchant.strip()
    logger.info("Processed %s transactions", len(transactions))
    logger.warning(f"Row {row_idx} has invalid amount format")
    logger.debug(f"has_memo={bool(memo)}")
    logger.debug(f"amount_ratio={0.991:.3f}")
"""
    path = _write_python(tmp_path / "sample.py", source)

    assert check_pii_logging.check_file(path, root=tmp_path) == []


def test_allow_comment_suppresses_one_logger_call(tmp_path: Path) -> None:
    """The escape hatch should be explicit and scoped to one logger call."""
    source = """
import logging

logger = logging.getLogger(__name__)


def run(amount):
    # finjuice-pii-log-allow: synthetic benchmark value, not user data
    logger.info("amount=%s", amount)
    logger.info("amount=%s", amount)
"""
    path = _write_python(tmp_path / "sample.py", source)

    issues = check_pii_logging.check_file(path, root=tmp_path)

    assert len(issues) == 1
    assert issues[0].sensitive_name == "amount"
    assert issues[0].line == 10


def test_directory_scan_excludes_private_data_and_export_dirs(tmp_path: Path) -> None:
    """Repository scans must not inspect private financial data directories."""
    _write_python(
        tmp_path / "data" / "private.py",
        "import logging\nlogger = logging.getLogger(__name__)\nlogger.info('%s', amount)\n",
    )
    _write_python(
        tmp_path / "exports" / "private.py",
        "import logging\nlogger = logging.getLogger(__name__)\nlogger.info('%s', amount)\n",
    )
    safe_file = _write_python(
        tmp_path / "src" / "safe.py",
        "import logging\nlogger = logging.getLogger(__name__)\nlogger.info('safe')\n",
    )

    assert list(check_pii_logging.iter_python_files([tmp_path])) == [safe_file]
    assert check_pii_logging.check_paths([tmp_path], root=tmp_path) == []


def test_cli_reports_only_location_and_reason(tmp_path: Path, capsys) -> None:
    """Checker output should not echo source lines or raw financial rows."""
    path = _write_python(
        tmp_path / "sample.py",
        """
import logging

logger = logging.getLogger(__name__)


def run(transaction):
    logger.info("transaction=%s", transaction)
""",
    )

    exit_code = check_pii_logging.main([str(path), "--root", str(tmp_path)])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "sample.py:8" in captured.err
    assert "raw transaction/row object" in captured.err
    assert "logger.info" not in captured.err
    assert "transaction=%s" not in captured.err


def test_import_history_path_fields_are_non_logging_metadata(tmp_path: Path) -> None:
    """Private local metadata may keep raw paths as long as it is not logged."""
    source = """
import logging

logger = logging.getLogger(__name__)


def build_record(source_file_path, archived_path):
    return {
        "original_filename": source_file_path.name,
        "imported_from": str(source_file_path),
        "archived_path": str(archived_path),
    }
"""
    path = _write_python(tmp_path / "sample.py", source)

    assert check_pii_logging.check_file(path, root=tmp_path) == []
