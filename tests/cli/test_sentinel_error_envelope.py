"""Tests for issue #373: sentinel stripping and error envelope standardization."""

import json

import pytest
import typer

from finjuice.pipeline.cli import output
from finjuice.pipeline.cli.output import ErrorCode, ExitCode
from finjuice.pipeline.tagging.manual import (
    MANUAL_CATEGORY_PREFIX,
    strip_sentinels,
    strip_sentinels_from_row,
)


class TestStripSentinels:
    """Tests for stripping __finjuice_* sentinels from tag lists."""

    def test_strip_sentinels_removes_category_override(self) -> None:
        """Sentinel prefixed tags should be removed from output."""
        tags = ["카페", f"{MANUAL_CATEGORY_PREFIX}식비:카페", "커피"]
        result = strip_sentinels(tags)
        assert result == ["카페", "커피"]

    def test_strip_sentinels_preserves_normal_tags(self) -> None:
        """Normal tags without sentinel prefix should be kept."""
        tags = ["보험", "정기지출"]
        assert strip_sentinels(tags) == ["보험", "정기지출"]

    def test_strip_sentinels_handles_empty_list(self) -> None:
        """Empty list should return empty list."""
        assert strip_sentinels([]) == []

    def test_strip_sentinels_handles_none(self) -> None:
        """None input should return empty list."""
        assert strip_sentinels(None) == []

    def test_strip_sentinels_removes_all_finjuice_prefixed(self) -> None:
        """Any tag starting with __finjuice_ should be removed."""
        tags = ["normal", "__finjuice_anything", "__finjuice_foo:bar"]
        result = strip_sentinels(tags)
        assert result == ["normal"]


class TestStripSentinelsFromRow:
    """Tests for stripping sentinels from a full transaction row dict."""

    def test_strips_from_tags_manual(self) -> None:
        """tags_manual field should have sentinels stripped."""
        row = {
            "row_hash": "abc123",
            "tags_manual": ["검진", f"{MANUAL_CATEGORY_PREFIX}의료"],
            "tags_final": ["보험", "검진"],
            "amount": -50000,
        }
        result = strip_sentinels_from_row(row)
        assert result["tags_manual"] == ["검진"]
        assert f"{MANUAL_CATEGORY_PREFIX}" not in str(result["tags_manual"])

    def test_strips_from_tags_final(self) -> None:
        """tags_final field should have sentinels stripped."""
        row = {
            "tags_manual": [],
            "tags_final": ["카페", "__finjuice_hidden"],
        }
        result = strip_sentinels_from_row(row)
        assert result["tags_final"] == ["카페"]

    def test_preserves_other_fields(self) -> None:
        """Non-tag fields should be passed through unchanged."""
        row = {
            "row_hash": "abc123",
            "amount": -50000,
            "merchant_raw": "스타벅스",
            "tags_manual": [f"{MANUAL_CATEGORY_PREFIX}식비"],
            "tags_final": ["카페"],
        }
        result = strip_sentinels_from_row(row)
        assert result["row_hash"] == "abc123"
        assert result["amount"] == -50000
        assert result["merchant_raw"] == "스타벅스"

    def test_returns_new_dict(self) -> None:
        """Should return a new dict, not mutate the original."""
        row = {
            "tags_manual": [f"{MANUAL_CATEGORY_PREFIX}x"],
            "tags_final": [],
        }
        result = strip_sentinels_from_row(row)
        assert result is not row
        # Original should still have the sentinel
        assert len(row["tags_manual"]) == 1


class TestErrorEnvelopeStandardization:
    """Tests for standardized error envelope with _meta and suggestion."""

    def test_error_always_includes_suggestion_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Error JSON should always have suggestion key, even when null."""
        captured: list[str] = []
        monkeypatch.setattr(output.typer, "echo", captured.append)

        with pytest.raises(typer.Exit):
            output.emit_error(
                "Something failed",
                error_code=ErrorCode.QUERY_ERROR,
                json_output=True,
            )

        payload = json.loads(captured[0])
        assert "suggestion" in payload["error"]
        assert payload["error"]["suggestion"] is None

    def test_error_includes_suggestion_when_provided(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Error JSON should include suggestion value when provided."""
        captured: list[str] = []
        monkeypatch.setattr(output.typer, "echo", captured.append)

        with pytest.raises(typer.Exit):
            output.emit_error(
                "Not initialized",
                error_code=ErrorCode.DATA_DIR_NOT_INITIALIZED,
                suggestion="finjuice init",
                json_output=True,
            )

        payload = json.loads(captured[0])
        assert payload["error"]["suggestion"] == "finjuice init"

    def test_error_always_includes_meta(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Error JSON should always have _meta, even without command arg."""
        captured: list[str] = []
        monkeypatch.setattr(output.typer, "echo", captured.append)

        with pytest.raises(typer.Exit):
            output.emit_error(
                "General failure",
                json_output=True,
            )

        payload = json.loads(captured[0])
        assert "_meta" in payload
        meta = payload["_meta"]
        assert "schema_version" in meta
        assert "finjuice_version" in meta
        assert "timestamp" in meta

    def test_error_meta_uses_command_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_meta.command should reflect the supplied command name."""
        captured: list[str] = []
        monkeypatch.setattr(output.typer, "echo", captured.append)

        with pytest.raises(typer.Exit):
            output.emit_error(
                "Query failed",
                error_code=ErrorCode.QUERY_ERROR,
                json_output=True,
                command="query",
            )

        payload = json.loads(captured[0])
        assert payload["_meta"]["command"] == "query"

    def test_error_meta_defaults_to_unknown(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_meta.command should be 'unknown' when no command is specified."""
        captured: list[str] = []
        monkeypatch.setattr(output.typer, "echo", captured.append)

        with pytest.raises(typer.Exit):
            output.emit_error(
                "Something broke",
                json_output=True,
            )

        payload = json.loads(captured[0])
        assert payload["_meta"]["command"] == "unknown"

    def test_error_envelope_structure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Error JSON should match the full expected structure."""
        captured: list[str] = []
        monkeypatch.setattr(output.typer, "echo", captured.append)

        with pytest.raises(typer.Exit) as exc_info:
            output.emit_error(
                "Validation failed",
                error_code=ErrorCode.VALIDATION_FAILED,
                exit_code=ExitCode.VALIDATION_ERROR,
                suggestion="finjuice rules validate",
                json_output=True,
                command="tag",
            )

        assert exc_info.value.exit_code == 3
        payload = json.loads(captured[0])

        # Check top-level keys
        assert set(payload.keys()) == {"_meta", "error", "exit_code"}

        # Check error keys
        assert set(payload["error"].keys()) == {"code", "message", "suggestion"}
        assert payload["error"]["code"] == "VALIDATION_FAILED"
        assert payload["error"]["message"] == "Validation failed"
        assert payload["error"]["suggestion"] == "finjuice rules validate"
        assert payload["exit_code"] == 3

    def test_text_mode_not_affected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Text mode error should still work without JSON envelope."""
        from io import StringIO

        from rich.console import Console

        string_io = StringIO()
        mock_console = Console(file=string_io, width=80)
        original_console = output.console
        output.console = mock_console

        try:
            with pytest.raises(typer.Exit):
                output.emit_error("Test error", json_output=False)

            result = string_io.getvalue()
            assert "Test error" in result
        finally:
            output.console = original_console
