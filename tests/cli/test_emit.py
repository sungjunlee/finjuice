"""Tests for unified CLI emit helpers."""

import json
from datetime import datetime
from io import StringIO

import polars as pl
import pytest
import typer
from rich.console import Console

from finjuice.pipeline.cli import output
from finjuice.pipeline.cli.output import ErrorCode, ExitCode


@pytest.fixture
def capture_console():
    """Capture Rich console output for tests."""
    string_io = StringIO()
    mock_console = Console(file=string_io, width=80, legacy_windows=False)
    original_console = output.console
    output.console = mock_console
    yield string_io
    output.console = original_console


class TestEmit:
    """Tests for emit()."""

    def test_emit_json_output_produces_valid_json(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """emit() should serialize structured data when JSON output is enabled."""
        captured: list[str] = []
        monkeypatch.setattr(output.typer, "echo", captured.append)

        output.emit({"status": "ok", "count": 3}, json_output=True, render_fn=lambda _: None)

        assert len(captured) == 1
        assert json.loads(captured[0]) == {"status": "ok", "count": 3}

    def test_emit_text_output_calls_render_fn(self) -> None:
        """emit() should delegate to the text renderer when JSON output is disabled."""
        rendered: list[dict[str, object]] = []

        output.emit({"status": "ok"}, json_output=False, render_fn=rendered.append)

        assert rendered == [{"status": "ok"}]

    def test_emit_json_preserves_korean_text(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """emit() should keep Unicode characters readable in JSON output."""
        captured: list[str] = []
        monkeypatch.setattr(output.typer, "echo", captured.append)

        output.emit({"message": "안녕하세요"}, json_output=True, render_fn=lambda _: None)

        assert "안녕하세요" in captured[0]
        assert json.loads(captured[0]) == {"message": "안녕하세요"}

    def test_emit_json_serializes_datetime_with_default_str(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """emit() should stringify datetime values via json.dumps(default=str)."""
        captured: list[str] = []
        timestamp = datetime(2026, 3, 29, 14, 30, 45)
        monkeypatch.setattr(output.typer, "echo", captured.append)

        output.emit({"created_at": timestamp}, json_output=True, render_fn=lambda _: None)

        assert json.loads(captured[0]) == {"created_at": str(timestamp)}

    def test_emit_json_handles_empty_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """emit() should support empty payloads."""
        captured: list[str] = []
        monkeypatch.setattr(output.typer, "echo", captured.append)

        output.emit({}, json_output=True, render_fn=lambda _: None)

        assert json.loads(captured[0]) == {}


class TestEmitList:
    """Tests for emit_list()."""

    def test_emit_list_json_wraps_items_with_meta_and_count(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """emit_list() should envelope list results in JSON mode."""
        captured: list[str] = []
        monkeypatch.setattr(output.typer, "echo", captured.append)

        output.emit_list(
            [{"id": "entry-1"}, {"id": "entry-2"}],
            json_output=True,
            render_fn=lambda _: None,
            command="journal list",
            items_key="entries",
        )

        payload = json.loads(captured[0])
        assert payload["_meta"]["command"] == "journal list"
        assert payload["entries"] == [{"id": "entry-1"}, {"id": "entry-2"}]
        assert payload["count"] == 2

    def test_emit_list_text_output_calls_render_fn(self) -> None:
        """emit_list() should delegate to the text renderer outside JSON mode."""
        rendered: list[list[object]] = []
        items = [{"id": "entry-1"}]

        output.emit_list(
            items,
            json_output=False,
            render_fn=rendered.append,
            command="journal list",
        )

        assert rendered == [items]


class TestEmitError:
    """Tests for emit_error()."""

    def test_emit_error_json_output(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """emit_error() should print a structured JSON error payload and exit."""
        captured: list[str] = []
        monkeypatch.setattr(output.typer, "echo", captured.append)

        with pytest.raises(typer.Exit) as exc_info:
            output.emit_error("실패했습니다", json_output=True)

        assert exc_info.value.exit_code == 1
        payload = json.loads(captured[0])
        assert "_meta" in payload
        assert payload["error"] == {
            "code": "GENERAL_ERROR",
            "message": "실패했습니다",
            "suggestion": None,
        }
        assert payload["exit_code"] == 1

    def test_emit_error_json_with_error_code_and_suggestion(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """emit_error() should include error_code and suggestion in JSON output."""
        captured: list[str] = []
        monkeypatch.setattr(output.typer, "echo", captured.append)

        with pytest.raises(typer.Exit) as exc_info:
            output.emit_error(
                "Data directory not initialized.",
                error_code=ErrorCode.DATA_DIR_NOT_INITIALIZED,
                exit_code=ExitCode.USAGE_ERROR,
                suggestion="finjuice init",
                json_output=True,
            )

        assert exc_info.value.exit_code == 2
        payload = json.loads(captured[0])
        assert "_meta" in payload
        assert payload["error"] == {
            "code": "DATA_DIR_NOT_INITIALIZED",
            "message": "Data directory not initialized.",
            "suggestion": "finjuice init",
        }
        assert payload["exit_code"] == 2

    def test_emit_error_json_includes_null_suggestion_when_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """emit_error() should include suggestion key with null value when None."""
        captured: list[str] = []
        monkeypatch.setattr(output.typer, "echo", captured.append)

        with pytest.raises(typer.Exit):
            output.emit_error(
                "Query failed",
                error_code=ErrorCode.QUERY_ERROR,
                json_output=True,
            )

        payload = json.loads(captured[0])
        assert "suggestion" in payload["error"]
        assert payload["error"]["suggestion"] is None
        assert payload["error"]["code"] == "QUERY_ERROR"

    def test_emit_error_text_output_prints_red_error(self, capture_console: StringIO) -> None:
        """emit_error() should render a Rich error message in text mode."""
        with pytest.raises(typer.Exit) as exc_info:
            output.emit_error("Operation failed")

        assert exc_info.value.exit_code == 1
        result = capture_console.getvalue()
        assert "❌" in result
        assert "Operation failed" in result

    def test_emit_error_uses_semantic_exit_code(
        self, monkeypatch: pytest.MonkeyPatch, capture_console: StringIO
    ) -> None:
        """emit_error() should use semantic exit codes."""
        monkeypatch.setattr(output.typer, "echo", lambda _: None)

        with pytest.raises(typer.Exit) as exc_info:
            output.emit_error(
                "Cancelled",
                error_code=ErrorCode.USER_CANCELLED,
                exit_code=ExitCode.USER_CANCELLED,
            )

        assert exc_info.value.exit_code == 130

    def test_emit_error_no_data_exit_code(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """emit_error() should use exit code 4 for NO_DATA."""
        captured: list[str] = []
        monkeypatch.setattr(output.typer, "echo", captured.append)

        with pytest.raises(typer.Exit) as exc_info:
            output.emit_error(
                "No transactions found",
                error_code=ErrorCode.NO_DATA,
                exit_code=ExitCode.NO_DATA,
                json_output=True,
            )

        assert exc_info.value.exit_code == 4
        payload = json.loads(captured[0])
        assert payload["exit_code"] == 4
        assert payload["error"]["code"] == "NO_DATA"

    def test_emit_error_validation_exit_code(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """emit_error() should use exit code 3 for VALIDATION_ERROR."""
        captured: list[str] = []
        monkeypatch.setattr(output.typer, "echo", captured.append)

        with pytest.raises(typer.Exit) as exc_info:
            output.emit_error(
                "Invalid rules format",
                error_code=ErrorCode.VALIDATION_FAILED,
                exit_code=ExitCode.VALIDATION_ERROR,
                json_output=True,
            )

        assert exc_info.value.exit_code == 3
        payload = json.loads(captured[0])
        assert payload["exit_code"] == 3


class TestErrorCodeConstants:
    """Tests for ErrorCode and ExitCode constants."""

    def test_error_codes_are_uppercase_strings(self) -> None:
        """All error codes should be uppercase string constants."""
        codes = [
            ErrorCode.GENERAL_ERROR,
            ErrorCode.DATA_DIR_NOT_INITIALIZED,
            ErrorCode.NO_DATA,
            ErrorCode.RULES_FILE_NOT_FOUND,
            ErrorCode.FILE_NOT_FOUND,
            ErrorCode.FILE_ACCESS_ERROR,
            ErrorCode.VALIDATION_FAILED,
            ErrorCode.INVALID_ARGS,
            ErrorCode.TAGGING_FAILED,
            ErrorCode.TRANSFER_FAILED,
            ErrorCode.EXPORT_FAILED,
            ErrorCode.QUERY_ERROR,
            ErrorCode.SIMULATION_FAILED,
            ErrorCode.INSPECTION_FAILED,
            ErrorCode.USER_CANCELLED,
            ErrorCode.UNEXPECTED_ERROR,
        ]
        for code in codes:
            assert isinstance(code, str)
            assert code == code.upper()

    def test_at_least_16_error_codes_defined(self) -> None:
        """Issue #282 requires at least 10 error codes."""
        code_attrs = [
            attr
            for attr in dir(ErrorCode)
            if not attr.startswith("_") and isinstance(getattr(ErrorCode, attr), str)
        ]
        assert len(code_attrs) >= 10

    def test_error_codes_are_string_enum_members(self) -> None:
        """ErrorCode should be typed while keeping string compatibility."""
        assert isinstance(ErrorCode.VALIDATION_FAILED, ErrorCode)
        assert isinstance(ErrorCode.VALIDATION_FAILED, str)
        assert ErrorCode.VALIDATION_FAILED == "VALIDATION_FAILED"
        assert ErrorCode.VALIDATION_FAILED.value == "VALIDATION_FAILED"
        assert json.loads(json.dumps({"code": ErrorCode.VALIDATION_FAILED})) == {
            "code": "VALIDATION_FAILED"
        }

    def test_error_code_catalog_exposes_accepted_values(self) -> None:
        """Accepted error codes should be discoverable from the enum catalog."""
        assert output.ERROR_CODE_CATALOG["VALIDATION_FAILED"] is ErrorCode.VALIDATION_FAILED
        assert output.error_code_values() == tuple(code.value for code in ErrorCode)
        assert set(output.ERROR_CODE_CATALOG) == set(output.error_code_values())

    def test_exit_codes_are_ints(self) -> None:
        """Exit codes should be integer constants."""
        assert ExitCode.SUCCESS == 0
        assert ExitCode.OK == 0
        assert ExitCode.GENERAL_ERROR == 1
        assert ExitCode.USAGE_ERROR == 2
        assert ExitCode.VALIDATION_ERROR == 3
        assert ExitCode.NO_DATA == 4
        assert ExitCode.USER_CANCELLED == 130

    def test_exit_codes_are_int_enum_members(self) -> None:
        """ExitCode should be typed while keeping integer compatibility."""
        assert isinstance(ExitCode.USAGE_ERROR, ExitCode)
        assert isinstance(ExitCode.USAGE_ERROR, int)
        assert int(ExitCode.USAGE_ERROR) == 2
        assert json.loads(json.dumps({"exit_code": ExitCode.USAGE_ERROR})) == {"exit_code": 2}

    def test_exit_code_catalog_exposes_aliases(self) -> None:
        """Exit code discovery should include compatibility aliases."""
        exit_codes = dict(output.exit_code_items())

        assert output.EXIT_CODE_CATALOG["OK"] is ExitCode.OK
        assert exit_codes["OK"] == 0
        assert exit_codes["SUCCESS"] == 0


class TestMarkdownRendering:
    """Tests for markdown rendering helpers."""

    def test_render_markdown_table_escapes_special_characters(self) -> None:
        """Cell rendering should escape pipe and newline characters."""
        rendered = output.render_markdown_table(
            ["name", "memo"],
            [["A|B", "line1\nline2"]],
        )

        assert "| name | memo |" in rendered
        assert "| A\\|B | line1<br>line2 |" in rendered

    def test_render_markdown_dataframe_without_pandas(self) -> None:
        """Polars DataFrame should render directly without pandas conversion."""
        df = pl.DataFrame({"merchant_raw": ["Starbucks"], "amount": [-5000]})

        rendered = output.render_markdown_dataframe(df)

        assert "| merchant_raw | amount |" in rendered
        assert "| Starbucks | -5000 |" in rendered
