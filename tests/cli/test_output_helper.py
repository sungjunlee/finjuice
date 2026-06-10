"""
Tests for CLI output helper module.

Tests:
- Output formatting functions (success, info, warning, error)
- Rich console integration
"""

from io import StringIO

import pytest
from rich.console import Console

from finjuice.pipeline.cli import output


@pytest.fixture
def mock_console():
    """Create mock console for capturing output."""
    string_io = StringIO()
    mock_console = Console(file=string_io, width=80, legacy_windows=False)
    original_console = output.console
    output.console = mock_console
    yield string_io
    output.console = original_console


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
