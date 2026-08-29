"""
Tests for CLI output helper module.

Tests:
- Output formatting functions (success, info, warning, error)
- Rich console integration
"""

from io import StringIO

import pytest
from rich.console import Console

from finjuice.pipeline.cli import output, output_pagination


@pytest.fixture
def mock_console():
    """Create mock console for capturing output."""
    string_io = StringIO()
    mock_console = Console(file=string_io, width=80, legacy_windows=False)
    original_console = output.console
    output.console = mock_console
    yield string_io
    output.console = original_console


class TestPublicNames:
    """Public emit/error/exit names stay on the output module after the split."""

    def test_emit_error_exit_names_remain_on_output_module(self) -> None:
        """Issue #78: callers can keep importing emit/error/exit helpers from output."""
        assert callable(output.emit)
        assert callable(output.emit_error)
        assert callable(output.emit_list)
        assert callable(output.error)
        assert output.ErrorCode.GENERAL_ERROR == "GENERAL_ERROR"
        assert int(output.ExitCode.GENERAL_ERROR) == 1

    def test_pagination_meta_helpers_are_reexported(self) -> None:
        """Pagination/meta helpers remain importable from output via re-export."""
        assert output._build_meta is output_pagination._build_meta
        assert output.Pagination is output_pagination.Pagination
        assert output.validate_pagination_args is output_pagination.validate_pagination_args
        assert output.build_offset_pagination is output_pagination.build_offset_pagination
        assert output.truncate_rows_to_max_bytes is output_pagination.truncate_rows_to_max_bytes
        assert output.wrap_paginated_result is output_pagination.wrap_paginated_result
        assert output.render_pagination_footer is output_pagination.render_pagination_footer
        assert output.DEFAULT_PAGINATION_LIMIT is output_pagination.DEFAULT_PAGINATION_LIMIT
        assert output.DEFAULT_MAX_BYTES is output_pagination.DEFAULT_MAX_BYTES
        assert output.MAX_PAGINATION_LIMIT is output_pagination.MAX_PAGINATION_LIMIT


class TestOutputHelpers:
    """Tests for output helper functions."""

    def test_success_message(self, mock_console):
        """Test success message formatting."""
        output.success("Operation completed")
        result = mock_console.getvalue()
        assert "✅" in result
        assert "Operation completed" in result

    def test_info_message(self, mock_console):
        """Test info message formatting."""
        output.info("Processing data")
        result = mock_console.getvalue()
        assert "ℹ️" in result
        assert "Processing data" in result

    def test_warning_message(self, mock_console):
        """Test warning message formatting."""
        output.warning("Potential issue detected")
        result = mock_console.getvalue()
        assert "⚠️" in result
        assert "Potential issue detected" in result

    def test_error_message(self, mock_console):
        """Test error message formatting."""
        output.error("Operation failed")
        result = mock_console.getvalue()
        assert "❌" in result
        assert "Operation failed" in result

    def test_step_message(self, mock_console):
        """Test numbered step formatting."""
        output.step(1, "First step")
        result = mock_console.getvalue()
        assert "[1]" in result
        assert "First step" in result

    def test_section_header(self, mock_console):
        """Test section header formatting."""
        output.section("Test Section")
        result = mock_console.getvalue()
        assert "Test Section" in result

    def test_bullet_list(self, mock_console):
        """Test bullet list formatting."""
        items = ["Item 1", "Item 2", "Item 3"]
        output.bullet_list(items)
        result = mock_console.getvalue()
        assert "Item 1" in result
        assert "Item 2" in result
        assert "Item 3" in result
        assert "•" in result

    def test_progress_indicator(self, mock_console):
        """Test progress indicator formatting."""
        output.progress_indicator(7, 10, "Processing")
        result = mock_console.getvalue()
        assert "70%" in result
        assert "Processing" in result
        assert "(7/10)" in result

    def test_newline_and_hr(self, mock_console):
        """Test newline and horizontal rule helpers."""
        output.newline()
        output.hr()
        result = mock_console.getvalue()
        # Should have output (newline and hr)
        assert len(result) > 0
