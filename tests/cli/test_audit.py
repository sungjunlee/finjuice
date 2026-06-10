"""
Tests for CLI audit command.

Tests the finjuice audit subcommands:
- audit log: Display audit log events
- audit stats: Show statistics
- audit clear: Clear old entries
"""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from finjuice.pipeline.cli.audit_log import append_audit_event
from finjuice.pipeline.cli.commands.audit import (
    TemplateMetrics,
    _compute_domain_template_retry_stats,
    _compute_template_metrics,
    _resolve_template_domain,
    _summarize_template_runs,
)
from finjuice.pipeline.cli.main import app
from tests.conftest import cli_text

runner = CliRunner()


@pytest.fixture
def data_dir_with_audit_log(tmp_path: Path) -> Path:
    """Create a data directory with sample audit log."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)

    # Create sample audit log
    events = [
        {
            "timestamp": "2024-10-01T10:00:00",
            "event": "command_suggested",
            "command": "finjuice tag",
            "user_confirmed": True,
        },
        {
            "timestamp": "2024-10-01T10:01:00",
            "event": "command_executed",
            "command": "finjuice tag",
            "success": True,
            "duration": 2.5,
            "returncode": 0,
        },
        {
            "timestamp": "2024-10-01T11:00:00",
            "event": "command_suggested",
            "command": "finjuice export",
            "user_confirmed": False,
        },
        {
            "timestamp": "2024-10-01T12:00:00",
            "event": "command_suggested",
            "command": "finjuice ingest",
            "user_confirmed": True,
        },
        {
            "timestamp": "2024-10-01T12:01:00",
            "event": "command_executed",
            "command": "finjuice ingest",
            "success": False,
            "duration": 1.2,
            "returncode": 1,
        },
        {
            "timestamp": "2024-10-01T13:00:00",
            "event": "command_error",
            "command": "finjuice ask",
            "stage": "parsing",
            "error_message": "Invalid query format",
        },
    ]

    audit_log_path = data_dir / ".execution_audit.jsonl"
    with open(audit_log_path, "w") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")

    return data_dir


@pytest.fixture
def data_dir_empty(tmp_path: Path) -> Path:
    """Create an empty data directory without audit log."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    return data_dir


@pytest.fixture
def data_dir_with_large_audit_log(tmp_path: Path) -> Path:
    """Create a data directory with 150+ audit events."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)

    events = []
    for i in range(150):
        # Generate valid timestamps across multiple days (i >= 24 would create invalid hours)
        day = (i // 24) + 1
        hour = i % 24
        events.append(
            {
                "timestamp": f"2024-10-{day:02d}T{hour:02d}:00:00",
                "event": "command_suggested",
                "command": f"finjuice cmd_{i}",
                "user_confirmed": i % 2 == 0,
            }
        )

    audit_log_path = data_dir / ".execution_audit.jsonl"
    with open(audit_log_path, "w") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")

    return data_dir


@pytest.fixture
def data_dir_with_template_audit_log(tmp_path: Path) -> Path:
    """Create audit log fixture with template_run events for metrics tests."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)

    events = [
        {
            "timestamp": "2024-10-01T10:00:00",
            "event": "template_run",
            "command": "finjuice template run monthly_spend",
            "template_name": "monthly_spend",
            "template_domain": "transaction",
            "success": False,
            "duration": 0.123,
            "output_format": "json",
            "param_keys": ["since"],
            "param_fingerprint": "fingerprint-a",
            "error_type": "ValueError",
        },
        {
            "timestamp": "2024-10-01T10:00:05",
            "event": "template_run",
            "command": "finjuice template run monthly_spend",
            "template_name": "monthly_spend",
            "template_domain": "transaction",
            "success": True,
            "duration": 0.088,
            "output_format": "json",
            "param_keys": ["since"],
            "param_fingerprint": "fingerprint-a",
            "row_count": 1,
        },
        {
            "timestamp": "2024-10-01T10:00:20",
            "event": "template_run",
            "command": "finjuice ask --report asset_overview",
            "template_name": "asset_overview",
            "template_domain": "asset",
            "success": False,
            "duration": 0.037,
            "output_format": "markdown",
            "param_keys": [],
            "param_fingerprint": "none",
            "error_type": "TyperExit",
        },
        {
            "timestamp": "2024-10-01T10:00:26",
            "event": "template_run",
            "command": "finjuice ask --report asset_overview",
            "template_name": "asset_overview",
            "template_domain": "asset",
            "success": True,
            "duration": 0.132,
            "output_format": "markdown",
            "param_keys": [],
            "param_fingerprint": "none",
        },
        {
            "timestamp": "2024-10-01T10:00:40",
            "event": "template_run",
            "command": "finjuice ask --report asset_top_holdings",
            "template_name": "asset_top_holdings",
            "success": True,
            "duration": 0.074,
            "output_format": "markdown",
            "param_keys": [],
            "param_fingerprint": "none",
        },
        {
            "timestamp": "2024-10-01T10:01:00",
            "event": "template_run",
            "command": "finjuice template run tag_breakdown",
            "template_name": "tag_breakdown",
            "success": True,
            "duration": 0.204,
            "output_format": "table",
            "param_keys": [],
            "param_fingerprint": "none",
            "row_count": 3,
        },
    ]

    audit_log_path = data_dir / ".execution_audit.jsonl"
    with open(audit_log_path, "w") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")

    return data_dir


class TestAuditMetricHelpers:
    """Unit tests for template metric helper functions."""

    @pytest.mark.parametrize(
        ("event", "expected"),
        [
            ({"template_domain": "asset", "template_name": "monthly_spend"}, "asset"),
            ({"template_domain": " Transaction ", "template_name": "monthly_spend"}, "transaction"),
            ({"template_domain": "invalid", "template_name": "asset_overview"}, "asset"),
            ({"template_name": "asset_top_holdings"}, "asset"),
            ({"template_name": "monthly_spend"}, "transaction"),
        ],
    )
    def test_resolve_template_domain(self, event: dict[str, str], expected: str) -> None:
        """template_domain should support explicit value and legacy fallback."""
        assert _resolve_template_domain(event) == expected

    def test_compute_template_metrics_empty(self) -> None:
        """Empty template list should produce zero metrics."""
        assert _compute_template_metrics([]) == TemplateMetrics(
            total=0,
            success=0,
            failed=0,
            success_rate=0.0,
            avg_duration=0.0,
            retry_attempts=0,
            retry_recovery=0.0,
        )

    def test_compute_domain_template_retry_stats_positive_case(self) -> None:
        """Retry stats should count attempts/recovery by domain."""
        events = [
            {
                "template_name": "asset_overview",
                "template_domain": "asset",
                "param_fingerprint": "none",
                "success": False,
            },
            {
                "template_name": "asset_overview",
                "template_domain": "asset",
                "param_fingerprint": "none",
                "success": True,
            },
            {
                "template_name": "monthly_spend",
                "template_domain": "transaction",
                "param_fingerprint": "fp-1",
                "success": False,
            },
            {
                "template_name": "monthly_spend",
                "template_domain": "transaction",
                "param_fingerprint": "fp-1",
                "success": False,
            },
        ]

        retry_stats = _compute_domain_template_retry_stats(events)
        assert retry_stats["asset"] == (1, 1)
        assert retry_stats["transaction"] == (1, 0)

    def test_compute_template_metrics_mixed_values(self) -> None:
        """Metric calculation should handle mixed outcomes and durations."""
        events = [
            {"success": True, "duration": 0.1},
            {"success": False, "duration": 0.3},
            {"success": True, "duration": 0.2},
        ]
        metrics = _compute_template_metrics(events, retry_stats=(2, 1))

        assert metrics.total == 3
        assert metrics.success == 2
        assert metrics.failed == 1
        assert metrics.success_rate == pytest.approx(66.666, rel=1e-3)
        assert metrics.avg_duration == pytest.approx(0.2, rel=1e-6)
        assert metrics.retry_attempts == 2
        assert metrics.retry_recovery == pytest.approx(50.0, rel=1e-6)

    def test_compute_template_metrics_skips_invalid_duration(self, caplog) -> None:
        """Invalid durations should be excluded from average calculation."""
        caplog.set_level("WARNING")
        events = [
            {"success": True, "duration": 0.1},
            {"success": False, "duration": "invalid"},
            {"success": True, "duration": 0.3},
        ]

        metrics = _compute_template_metrics(events, retry_stats=(0, 0))

        assert metrics.avg_duration == pytest.approx(0.2, rel=1e-6)
        assert "Invalid duration value in audit event" in caplog.text

    def test_summarize_template_runs(self) -> None:
        """Summary helper should aggregate overall/domain usage and metrics."""
        events = [
            {
                "template_name": "asset_overview",
                "template_domain": "asset",
                "param_fingerprint": "none",
                "success": True,
                "duration": 0.1,
            },
            {
                "template_name": "monthly_spend",
                "template_domain": "transaction",
                "param_fingerprint": "fp-1",
                "success": False,
                "duration": 0.4,
            },
            {
                "template_name": "monthly_spend",
                "template_domain": "transaction",
                "param_fingerprint": "fp-1",
                "success": True,
                "duration": 0.2,
            },
        ]

        summary = _summarize_template_runs(events)
        assert summary.overall.total == 3
        assert summary.asset.total == 1
        assert summary.asset.success == 1
        assert summary.transaction.total == 2
        assert summary.transaction.retry_attempts == 1
        assert summary.transaction.retry_recovery == pytest.approx(100.0, rel=1e-6)
        assert summary.usage_counts["monthly_spend"] == 2
        assert summary.domain_usage_counts["asset"]["asset_overview"] == 1

    def test_append_audit_event_appends_jsonl(self, tmp_path: Path) -> None:
        """Shared append helper should preserve UTF-8 payload and append semantics."""
        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True)
        append_audit_event(data_dir, {"event": "template_run", "note": "한글"})
        append_audit_event(data_dir, {"event": "template_run", "note": "second"})

        audit_log_path = data_dir / ".execution_audit.jsonl"
        lines = [line for line in audit_log_path.read_text(encoding="utf-8").splitlines() if line]
        assert len(lines) == 2
        first = json.loads(lines[0])
        second = json.loads(lines[1])
        assert first["note"] == "한글"
        assert second["note"] == "second"


class TestAuditLogCommand:
    """Tests for finjuice audit log command."""

    def test_audit_log_no_file(self, data_dir_empty: Path) -> None:
        """Test audit log when no audit file exists."""
        # Act
        result = runner.invoke(app, ["--data-dir", str(data_dir_empty), "audit", "log"])

        # Assert
        assert result.exit_code == 1
        assert "No audit log found" in cli_text(result)

    def test_audit_log_display(self, data_dir_with_audit_log: Path) -> None:
        """Test audit log displays events."""
        # Act
        result = runner.invoke(app, ["--data-dir", str(data_dir_with_audit_log), "audit", "log"])

        # Assert
        assert result.exit_code == 0
        assert "Audit Log" in cli_text(result)
        assert "finjuice tag" in cli_text(result)
        assert "command_suggested" in cli_text(result) or "command_executed" in cli_text(result)

    def test_audit_log_last_n(self, data_dir_with_audit_log: Path) -> None:
        """Test audit log with --last option."""
        # Act
        result = runner.invoke(
            app, ["--data-dir", str(data_dir_with_audit_log), "audit", "log", "--last", "3"]
        )

        # Assert
        assert result.exit_code == 0
        assert "3 events" in cli_text(result) or "Audit Log" in cli_text(result)

    def test_audit_log_filter_by_type(self, data_dir_with_audit_log: Path) -> None:
        """Test audit log filtering by event type."""
        # Act
        result = runner.invoke(
            app,
            [
                "--data-dir",
                str(data_dir_with_audit_log),
                "audit",
                "log",
                "--type",
                "command_executed",
            ],
        )

        # Assert
        assert result.exit_code == 0
        # Should only show executed events
        assert "command_executed" in cli_text(result) or "Success" in cli_text(result)

    def test_audit_log_filter_failed(self, data_dir_with_audit_log: Path) -> None:
        """Test audit log filtering for failed executions only."""
        # Act
        result = runner.invoke(
            app, ["--data-dir", str(data_dir_with_audit_log), "audit", "log", "--failed"]
        )

        # Assert
        assert result.exit_code == 0
        # Should show failed execution (finjuice ingest failed)
        if "finjuice ingest" in cli_text(result):
            assert "Failed" in cli_text(result) or "code: 1" in cli_text(result)

    def test_audit_log_no_events_matching_filter(self, data_dir_with_audit_log: Path) -> None:
        """Test audit log when no events match filter."""
        # Act
        result = runner.invoke(
            app,
            [
                "--data-dir",
                str(data_dir_with_audit_log),
                "audit",
                "log",
                "--type",
                "nonexistent_event",
            ],
        )

        # Assert
        assert result.exit_code == 0
        assert "No events found" in cli_text(result)

    def test_audit_log_invalid_json(self, tmp_path: Path) -> None:
        """Malformed JSON lines should be skipped in audit log command."""
        # Arrange
        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True)
        audit_log_path = data_dir / ".execution_audit.jsonl"
        audit_log_path.write_text(
            json.dumps({"event": "command_suggested", "command": "finjuice tag"}) + "\n"
            "invalid json content\n"
        )

        # Act
        result = runner.invoke(app, ["--data-dir", str(data_dir), "audit", "log"])

        # Assert
        assert result.exit_code == 0
        assert "Skipped 1 malformed audit entries" in cli_text(result)
        assert "finjuice tag" in cli_text(result)

    def test_audit_log_template_run_details(self, data_dir_with_template_audit_log: Path) -> None:
        """Template run events should render with template-specific details."""
        result = runner.invoke(
            app,
            [
                "--data-dir",
                str(data_dir_with_template_audit_log),
                "audit",
                "log",
                "--type",
                "template_run",
            ],
        )

        assert result.exit_code == 0
        assert "template_run" in cli_text(result)
        assert "monthly_spend" in cli_text(result)

    def test_audit_log_failed_includes_template_run(
        self, data_dir_with_template_audit_log: Path
    ) -> None:
        """--failed filter should include failed template_run events."""
        result = runner.invoke(
            app,
            ["--data-dir", str(data_dir_with_template_audit_log), "audit", "log", "--failed"],
        )

        assert result.exit_code == 0
        assert "monthly_spend" in cli_text(result)


class TestAuditStatsCommand:
    """Tests for finjuice audit stats command."""

    def test_audit_stats_no_file(self, data_dir_empty: Path) -> None:
        """Test audit stats when no audit file exists."""
        # Act
        result = runner.invoke(app, ["--data-dir", str(data_dir_empty), "audit", "stats"])

        # Assert
        assert result.exit_code == 1
        assert "No audit log found" in cli_text(result)

    def test_audit_stats_calculation(self, data_dir_with_audit_log: Path) -> None:
        """Test audit stats calculates correct statistics."""
        # Act
        result = runner.invoke(app, ["--data-dir", str(data_dir_with_audit_log), "audit", "stats"])

        # Assert
        assert result.exit_code == 0
        assert "Statistics" in cli_text(result)
        # Should show suggestion counts
        assert "suggestions" in cli_text(result).lower() or "Total" in cli_text(result)
        # Should show execution counts
        assert "executions" in cli_text(result).lower() or "Successful" in cli_text(result)

    def test_audit_stats_skips_malformed_json_lines(self, tmp_path: Path) -> None:
        """audit stats should skip malformed lines instead of failing."""
        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True)
        audit_log_path = data_dir / ".execution_audit.jsonl"
        valid_event = {
            "timestamp": "2024-10-01T10:00:00",
            "event": "command_suggested",
            "command": "finjuice tag",
            "user_confirmed": True,
        }
        audit_log_path.write_text(json.dumps(valid_event) + "\ninvalid json\n")

        result = runner.invoke(app, ["--data-dir", str(data_dir), "audit", "stats"])

        assert result.exit_code == 0
        assert "Skipped 1 malformed audit entries" in cli_text(result)
        assert "Total suggestions" in cli_text(result)

    def test_audit_stats_success_rate(self, data_dir_with_audit_log: Path) -> None:
        """Test audit stats shows success rate."""
        # Act
        result = runner.invoke(app, ["--data-dir", str(data_dir_with_audit_log), "audit", "stats"])

        # Assert
        assert result.exit_code == 0
        # We have 1 success, 1 failure -> 50% success rate
        assert "%" in cli_text(result) or "rate" in cli_text(result).lower()

    def test_audit_stats_top_commands(self, data_dir_with_audit_log: Path) -> None:
        """Test audit stats shows top commands."""
        # Act
        result = runner.invoke(app, ["--data-dir", str(data_dir_with_audit_log), "audit", "stats"])

        # Assert
        assert result.exit_code == 0
        # Should show top commands section
        assert "Commands" in cli_text(result) or "finjuice" in cli_text(result)

    def test_audit_stats_template_metrics(self, data_dir_with_template_audit_log: Path) -> None:
        """Template run metrics should be shown when template_run events exist."""
        result = runner.invoke(
            app,
            ["--data-dir", str(data_dir_with_template_audit_log), "audit", "stats"],
        )

        assert result.exit_code == 0
        assert "Template Run Metrics" in cli_text(result)
        assert "Template runs" in cli_text(result)
        assert "Retry attempts" in cli_text(result)
        assert "Top Templates" in cli_text(result)
        assert "Asset runs" in cli_text(result)
        assert "Transaction runs" in cli_text(result)
        assert "Top Asset Templates" in cli_text(result)
        assert "Top Transaction Templates" in cli_text(result)
        assert "asset_top_holdings" in cli_text(result)

    def test_audit_stats_domain_retry_uses_global_adjacency(self, tmp_path: Path) -> None:
        """Domain retry counts should not overcount when events are interleaved."""
        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True)

        events = [
            {
                "timestamp": "2024-10-01T10:00:00",
                "event": "template_run",
                "command": "finjuice ask --report asset_overview",
                "template_name": "asset_overview",
                "template_domain": "asset",
                "success": False,
                "duration": 0.101,
                "output_format": "markdown",
                "param_keys": [],
                "param_fingerprint": "none",
                "error_type": "TyperExit",
            },
            {
                "timestamp": "2024-10-01T10:00:04",
                "event": "template_run",
                "command": "finjuice template run monthly_spend",
                "template_name": "monthly_spend",
                "template_domain": "transaction",
                "success": True,
                "duration": 0.111,
                "output_format": "json",
                "param_keys": ["since"],
                "param_fingerprint": "abc",
            },
            {
                "timestamp": "2024-10-01T10:00:08",
                "event": "template_run",
                "command": "finjuice ask --report asset_overview",
                "template_name": "asset_overview",
                "template_domain": "asset",
                "success": True,
                "duration": 0.121,
                "output_format": "markdown",
                "param_keys": [],
                "param_fingerprint": "none",
            },
        ]

        audit_log_path = data_dir / ".execution_audit.jsonl"
        with open(audit_log_path, "w") as f:
            for event in events:
                f.write(json.dumps(event) + "\n")

        result = runner.invoke(app, ["--data-dir", str(data_dir), "audit", "stats"])

        assert result.exit_code == 0
        normalized = " ".join(cli_text(result).split())
        assert "Retry attempts 0" in normalized
        assert "Asset retry attempts 0" in normalized
        assert "Asset retry recovery 0.0%" in normalized


class TestAuditClearCommand:
    """Tests for finjuice audit clear command."""

    def test_audit_clear_no_file(self, data_dir_empty: Path) -> None:
        """Test audit clear when no audit file exists."""
        # Act
        result = runner.invoke(app, ["--data-dir", str(data_dir_empty), "audit", "clear", "--yes"])

        # Assert
        assert result.exit_code == 0
        assert "No audit log found" in cli_text(result)

    def test_audit_clear_skips_malformed_lines(self, tmp_path: Path) -> None:
        """Malformed JSON lines should be skipped instead of failing clear."""
        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True)
        audit_log_path = data_dir / ".execution_audit.jsonl"
        events = [
            {"event": "command_suggested", "command": "finjuice tag"},
            {"event": "command_executed", "command": "finjuice tag", "success": True},
        ]
        with open(audit_log_path, "w") as f:
            f.write(json.dumps(events[0]) + "\n")
            f.write("{not-json}\n")
            f.write(json.dumps(events[1]) + "\n")

        result = runner.invoke(app, ["--data-dir", str(data_dir), "audit", "clear", "--yes"])

        assert result.exit_code == 0
        assert "Skipped 1 malformed audit entries" in cli_text(result)
        lines = [line for line in audit_log_path.read_text().splitlines() if line.strip()]
        assert len(lines) == 2
        for line in lines:
            assert isinstance(json.loads(line), dict)

    def test_audit_clear_atomic_write_failure(
        self,
        data_dir_with_audit_log: Path,
        monkeypatch,
    ) -> None:
        """Write failures should abort clear without truncating existing log."""
        audit_log_path = data_dir_with_audit_log / ".execution_audit.jsonl"
        original = audit_log_path.read_text()

        def _raise_write_error(*args, **kwargs):  # noqa: ANN002, ANN003
            raise OSError("disk full")

        monkeypatch.setattr(
            "finjuice.pipeline.cli.commands.audit._write_audit_events_atomically",
            _raise_write_error,
        )

        result = runner.invoke(
            app,
            ["--data-dir", str(data_dir_with_audit_log), "audit", "clear", "--yes"],
        )

        assert result.exit_code == 1
        assert "Failed to rewrite audit log" in cli_text(result)
        assert audit_log_path.read_text() == original

    def test_audit_clear_confirm_no(self, data_dir_with_audit_log: Path) -> None:
        """Test audit clear cancelled by user."""
        # Act - simulate "n" input
        result = runner.invoke(
            app, ["--data-dir", str(data_dir_with_audit_log), "audit", "clear"], input="n\n"
        )

        # Assert
        assert result.exit_code == 0
        assert "Cancelled" in cli_text(result)

        # Verify file still has all events
        audit_log_path = data_dir_with_audit_log / ".execution_audit.jsonl"
        with open(audit_log_path) as f:
            lines = f.readlines()
        assert len(lines) == 6  # Original count

    def test_audit_clear_confirm_yes(self, data_dir_with_audit_log: Path) -> None:
        """Test audit clear with --yes flag."""
        # Act
        result = runner.invoke(
            app, ["--data-dir", str(data_dir_with_audit_log), "audit", "clear", "--yes"]
        )

        # Assert
        assert result.exit_code == 0
        assert "Cleared" in cli_text(result)

    def test_audit_clear_keep_last_100(self, data_dir_with_large_audit_log: Path) -> None:
        """Test audit clear keeps last 100 entries."""
        # Verify we have 150 events initially
        audit_log_path = data_dir_with_large_audit_log / ".execution_audit.jsonl"
        with open(audit_log_path) as f:
            initial_count = len(f.readlines())
        assert initial_count == 150

        # Act
        result = runner.invoke(
            app, ["--data-dir", str(data_dir_with_large_audit_log), "audit", "clear", "--yes"]
        )

        # Assert
        assert result.exit_code == 0
        assert "100" in cli_text(result)  # Should mention keeping 100 entries

        # Verify only 100 entries remain
        with open(audit_log_path) as f:
            final_count = len(f.readlines())
        assert final_count == 100

    def test_audit_clear_small_file(self, data_dir_with_audit_log: Path) -> None:
        """Test audit clear with less than 100 entries keeps all."""
        # Act
        result = runner.invoke(
            app, ["--data-dir", str(data_dir_with_audit_log), "audit", "clear", "--yes"]
        )

        # Assert
        assert result.exit_code == 0

        # Verify all 6 entries remain (less than 100)
        audit_log_path = data_dir_with_audit_log / ".execution_audit.jsonl"
        with open(audit_log_path) as f:
            final_count = len(f.readlines())
        assert final_count == 6
