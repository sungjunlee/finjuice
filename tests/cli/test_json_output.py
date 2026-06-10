"""JSON output tests for read-only CLI commands."""

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import polars as pl
import pytest
from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app

runner = CliRunner()
REPO_ROOT = Path(__file__).resolve().parents[2]


def _subprocess_env() -> dict[str, str]:
    """Build an env that resolves the local src/ package in subprocess tests."""
    env = os.environ.copy()
    src_path = str(REPO_ROOT / "src")
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        src_path if not existing_pythonpath else f"{src_path}{os.pathsep}{existing_pythonpath}"
    )
    return env


def _run_cli_subprocess(data_dir: Path, cmd_args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run the real CLI entrypoint and capture stdout/stderr separately."""
    return subprocess.run(
        [
            sys.executable,
            "-c",
            "from finjuice.pipeline.cli.main import cli_entry; cli_entry()",
            "--data-dir",
            str(data_dir),
            *cmd_args,
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
        env=_subprocess_env(),
        text=True,
    )


class TestJsonOutput:
    """Machine-readable output tests for CLI commands."""

    @pytest.mark.parametrize(
        "cmd_args",
        [
            ["checkup", "--json"],
            ["status", "--json"],
            ["status", "--json", "--detailed"],
            ["tag", "--json"],
            ["transfer", "--json"],
            ["refresh", "--json"],
            ["doctor", "--json"],
            ["show", "--json"],
            ["history", "--json"],
            ["ingest", "--dry-run", "--json"],
            ["export", "--dry-run", "--json"],
            ["query", "SELECT 1 AS one", "--json"],
            ["explain", "Starbucks", "--json"],
            ["rules", "validate", "--json"],
            ["rules", "suggest", "--json"],
            [
                "rules",
                "add",
                "--name",
                "netflix",
                "--match",
                "Netflix",
                "--tags",
                "구독",
                "--dry-run",
                "--json",
            ],
            ["rules", "export", "--json"],
            ["rules", "gaps", "--json"],
            ["template", "list", "--json"],
            ["template", "run", "monthly_spend", "--json"],
            ["assets", "status", "--json"],
            ["assets", "show", "--json"],
        ],
    )
    def test_json_stdout_purity(self, json_output_data_dir: Path, cmd_args: list[str]) -> None:
        """Every --json command must produce valid JSON on stdout."""
        result = runner.invoke(
            app,
            ["--data-dir", str(json_output_data_dir)] + cmd_args,
        )

        assert result.exit_code == 0, f"Command failed: {cmd_args}, output: {result.output[:200]}"
        json.loads(result.output)

    @pytest.mark.parametrize(
        "cmd_args",
        [
            ["checkup", "--json"],
            ["status", "--json"],
            ["ingest", "--dry-run", "--json"],
            ["query", "SELECT 1 AS one", "--json"],
            ["query", "SELECT 1 AS one", "--output", "json"],
            ["assets", "show", "--json"],
        ],
    )
    def test_json_subprocess_stream_purity(
        self, json_output_data_dir: Path, cmd_args: list[str]
    ) -> None:
        """Real CLI invocations should keep stderr silent in JSON mode."""
        result = _run_cli_subprocess(json_output_data_dir, cmd_args)

        assert result.returncode == 0, (
            f"Command failed: {cmd_args}, stderr: {result.stderr[:200]}, "
            f"stdout: {result.stdout[:200]}"
        )
        assert result.stderr.strip() == ""
        json.loads(result.stdout)

    def test_template_run_json_file_subprocess_stream_purity(
        self, json_output_data_dir: Path, tmp_path: Path
    ) -> None:
        """template run --json --file should stay silent on stdout/stderr."""
        output_path = tmp_path / "template-result.json"

        result = _run_cli_subprocess(
            json_output_data_dir,
            [
                "template",
                "run",
                "monthly_spend",
                "--json",
                "--file",
                str(output_path),
            ],
        )

        assert result.returncode == 0, (
            f"Command failed, stderr: {result.stderr[:200]}, stdout: {result.stdout[:200]}"
        )
        assert result.stdout.strip() == ""
        assert result.stderr.strip() == ""
        payload = json.loads(output_path.read_text(encoding="utf-8"))
        assert payload["_meta"]["command"] == "template run"
        assert payload["template_name"] == "monthly_spend"
        assert payload["row_count"] == 2

    def test_json_verbose_subprocess_stream_purity(self, json_output_data_dir: Path) -> None:
        """--json --verbose should not leak DEBUG log lines to stderr."""
        result = _run_cli_subprocess(
            json_output_data_dir,
            ["--verbose", "status", "--json"],
        )

        assert result.returncode == 0, (
            f"Command failed, stderr: {result.stderr[:200]}, stdout: {result.stdout[:200]}"
        )
        assert result.stderr.strip() == ""
        json.loads(result.stdout)

    def test_json_subprocess_error_stream_purity(self, json_output_data_dir: Path) -> None:
        """Structured JSON errors should not be prefixed with logger output on stderr."""
        result = _run_cli_subprocess(
            json_output_data_dir,
            ["query", "SELECT * FROM missing_table", "--json"],
        )

        assert result.returncode == 1
        assert result.stderr.strip() == ""
        payload = json.loads(result.stdout)
        assert payload["error"]["code"] == "QUERY_ERROR"

    def test_json_subprocess_config_validation_error_stream_purity(self, tmp_path: Path) -> None:
        """Callback-level config validation errors should preserve JSON mode purity."""
        data_file = tmp_path / "not-a-directory"
        data_file.write_text("not a data dir\n", encoding="utf-8")

        result = _run_cli_subprocess(data_file, ["status", "--json"])

        assert result.returncode == 2
        assert result.stderr.strip() == ""
        payload = json.loads(result.stdout)
        assert payload["_meta"]["command"] == "status"
        assert payload["error"]["code"] == "DATA_DIR_NOT_INITIALIZED"
        assert payload["exit_code"] == 2

    def test_status_json(self, json_output_data_dir: Path) -> None:
        """status --json should return structured status data."""
        result = runner.invoke(
            app,
            ["--data-dir", str(json_output_data_dir), "status", "--json", "--detailed"],
        )

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["data_directory"]["path"] == str(json_output_data_dir.resolve())
        assert payload["transactions"]["count"] == 4
        assert payload["transactions"]["partition_count"] == 2
        assert payload["tagging"]["untagged_count"] == 1
        assert "detailed_stats" in payload
        assert payload["health"] == {
            "status": "warning",
            "reasons": ["untagged_transactions"],
        }
        assert payload["actionable"] is True
        assert payload["signals"]["detailed_requested"] is True
        assert payload["next_steps"][0]["command"] == "finjuice review --json"

    def test_history_json(self, json_output_data_dir: Path) -> None:
        """history --json should return an enveloped records payload."""
        result = runner.invoke(app, ["--data-dir", str(json_output_data_dir), "history", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["_meta"]["command"] == "history"
        assert payload["count"] == 2
        assert payload["records"][0]["file_id"] == "241120_1"

    def test_explain_json(self, json_output_data_dir: Path) -> None:
        """explain --json should return transaction details and rule trace."""
        result = runner.invoke(
            app,
            ["--data-dir", str(json_output_data_dir), "explain", "Starbucks", "--json"],
        )

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["transaction"]["merchant_raw"] == "Starbucks Gangnam"
        assert payload["classification"]["matched_rules"] == ["coffee"]
        assert payload["rule_trace"][0]["rule_name"] == "coffee"

    def test_tag_json(self, json_output_data_dir: Path) -> None:
        """tag --json should return structured tagging summary."""
        result = runner.invoke(
            app,
            ["--data-dir", str(json_output_data_dir), "tag", "--dry-run", "--json"],
        )

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["status"] == "ok"
        assert payload["dry_run"] is True
        assert payload["total"] == 4
        assert isinstance(payload["coverage_pct"], float)

    def test_transfer_json(self, json_output_data_dir: Path) -> None:
        """transfer --json should return machine-readable transfer counts."""
        result = runner.invoke(app, ["--data-dir", str(json_output_data_dir), "transfer", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["status"] == "ok"
        assert "candidate_rows" in payload
        assert "confirmed_transfer_rows" in payload
        assert "unconfirmed_candidate_rows" in payload
        assert payload["pairs_found"] == 0
        assert payload["pairs_linked"] == 0

    @patch("finjuice.pipeline.export.result._compute_export_result")
    @patch("finjuice.pipeline.transfer.detection.run_transfer_detection")
    @patch("finjuice.pipeline.tagging.pipeline.run_tagging")
    @patch("finjuice.pipeline.ingest.pipeline.ingest_all_files")
    def test_refresh_json(
        self,
        mock_ingest,
        mock_tag,
        mock_transfer,
        mock_export,
        json_output_data_dir: Path,
    ) -> None:
        """refresh --json should compose step payloads without Rich progress output."""
        mock_ingest.return_value = {
            "files": 1,
            "inserted": 4,
            "updated": 0,
            "failed": 0,
            "failed_files": [],
        }
        mock_tag.return_value = {
            "total": 4,
            "tagged": 3,
            "untagged": 1,
            "coverage_pct": 75.0,
        }
        mock_transfer.return_value = {"pairs": 1, "paired": 2}
        mock_export.return_value = {
            "command": "export",
            "dry_run": False,
            "format": "xlsx",
            "period": None,
            "transaction_count": 4,
            "output_files": [],
            "skipped_outputs": [],
        }

        result = runner.invoke(app, ["--data-dir", str(json_output_data_dir), "refresh", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["_meta"]["command"] == "refresh"
        assert payload["command"] == "refresh"
        assert payload["steps"]["ingest"]["summary"]["files_processed"] == 1
        assert payload["steps"]["tag"]["tagged"] == 3
        assert payload["steps"]["transfer"]["pairs_found"] == 1
        assert payload["steps"]["export"]["command"] == "export"
        assert mock_export.call_args.kwargs["emit_text"] is False

    @patch("finjuice.pipeline.export.result._compute_export_result")
    @patch("finjuice.pipeline.transfer.detection.run_transfer_detection")
    @patch("finjuice.pipeline.tagging.pipeline.run_tagging")
    @patch("finjuice.pipeline.ingest.pipeline.ingest_all_files")
    def test_refresh_text_keeps_export_errors_human_readable(
        self,
        mock_ingest,
        mock_tag,
        mock_transfer,
        mock_export,
        json_output_data_dir: Path,
    ) -> None:
        """refresh text mode should not force export report-filter errors into JSON."""
        mock_ingest.return_value = {
            "files": 1,
            "inserted": 4,
            "updated": 0,
            "failed": 0,
            "failed_files": [],
        }
        mock_tag.return_value = {
            "total": 4,
            "tagged": 3,
            "untagged": 1,
            "coverage_pct": 75.0,
        }
        mock_transfer.return_value = {"pairs": 1, "paired": 2}
        mock_export.return_value = {
            "command": "export",
            "dry_run": False,
            "format": "xlsx",
            "period": None,
            "transaction_count": 4,
            "output_files": [],
            "skipped_outputs": [],
        }

        result = runner.invoke(app, ["--data-dir", str(json_output_data_dir), "refresh"])

        assert result.exit_code == 0
        assert mock_export.call_args.kwargs["emit_text"] is True

    def test_doctor_json(self, json_output_data_dir: Path) -> None:
        """doctor --json should return named checks and summary counts."""
        result = runner.invoke(app, ["--data-dir", str(json_output_data_dir), "doctor", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert isinstance(payload["checks"], list)
        assert payload["summary"]["total"] == len(payload["checks"])
        assert isinstance(payload["missing_extras"], list)
        assert isinstance(payload["install_hint"], str)
        assert {"name", "status", "message", "detail", "suggestion"} <= set(
            payload["checks"][0].keys()
        )

    def test_show_json(self, json_output_data_dir: Path) -> None:
        """show --json should return an enveloped rows payload."""
        result = runner.invoke(
            app,
            [
                "--data-dir",
                str(json_output_data_dir),
                "show",
                "--month",
                "2024-11",
                "--json",
                "--limit",
                "1",
            ],
        )

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["_meta"]["command"] == "show"
        assert payload["row_count"] == 1
        assert payload["total_matches"] == 2
        assert payload["rows"][0]["date"].startswith("2024-11")
        assert "merchant_raw" in payload["rows"][0]

    def test_validate_rules_json(self, json_output_data_dir: Path) -> None:
        """rules validate --json should return structured severity arrays and counts."""
        result = runner.invoke(
            app,
            ["--data-dir", str(json_output_data_dir), "rules", "validate", "--json"],
        )

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["status"] == "valid"
        assert payload["total_rules"] == 2
        assert payload["errors"] == 0
        assert payload["warnings"] == 0
        assert payload["problems"] == []

    @patch("finjuice.pipeline.tagging.suggestions.get_suggestion_coverage_stats")
    @patch("finjuice.pipeline.tagging.suggestions.generate_merchant_context")
    def test_rules_suggest_json(
        self,
        mock_generate_merchant_context,
        mock_get_suggestion_coverage_stats,
        json_output_data_dir: Path,
    ) -> None:
        """rules suggest --json should return suggestion objects and coverage data."""
        mock_get_suggestion_coverage_stats.return_value = {
            "untagged_count": 2,
            "total_count": 4,
            "coverage_before_pct": 50.0,
        }
        mock_generate_merchant_context.return_value = [
            {
                "merchant": "스타벅스",
                "transaction_count": 12,
                "total_amount": 60000.0,
                "avg_amount": 5000.0,
                "amount_stddev": 0.0,
                "active_months": ["2024-10"],
                "is_recurring": True,
                "banksalad_category": {"major": "식비", "minor": "카페"},
                "payment_method": "신한카드",
                "time_patterns": {"weekday_pct": 1.0, "lunch_pct": 0.0},
                "similar_merchants": [],
                "pattern": "스타벅스|STARBUCKS",
                "sample_memos": ["Latte"],
            }
        ]

        result = runner.invoke(
            app,
            ["--data-dir", str(json_output_data_dir), "rules", "suggest", "--json"],
        )

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["untagged_count"] == 2
        assert payload["total_count"] == 4
        assert payload["coverage_before_pct"] == pytest.approx(50.0)
        assert payload["suggestions"][0] == {
            "merchant": "스타벅스",
            "transaction_count": 12,
            "total_amount": 60000.0,
            "avg_amount": 5000.0,
            "amount_stddev": 0.0,
            "active_months": ["2024-10"],
            "is_recurring": True,
            "banksalad_category": {"major": "식비", "minor": "카페"},
            "payment_method": "신한카드",
            "time_patterns": {"weekday_pct": 1.0, "lunch_pct": 0.0},
            "similar_merchants": [],
            "pattern": "스타벅스|STARBUCKS",
            "sample_memos": ["Latte"],
        }

    @patch("finjuice.pipeline.tagging.pipeline.run_tagging")
    @patch("finjuice.pipeline.tagging.suggestions.apply_suggestion_to_rules")
    @patch("finjuice.pipeline.tagging.suggestions.get_suggestion_coverage_stats")
    @patch("finjuice.pipeline.tagging.suggestions.generate_merchant_context")
    def test_rules_suggest_apply_yes_json(
        self,
        mock_generate_merchant_context,
        mock_get_suggestion_coverage_stats,
        mock_apply_suggestion_to_rules,
        mock_run_tagging,
        json_output_data_dir: Path,
    ) -> None:
        """rules suggest --apply --yes --json should return apply counts."""
        mock_get_suggestion_coverage_stats.return_value = {
            "untagged_count": 2,
            "total_count": 4,
            "coverage_before_pct": 50.0,
        }
        mock_generate_merchant_context.return_value = [
            {
                "merchant": "스타벅스",
                "transaction_count": 12,
                "total_amount": 60000.0,
                "avg_amount": 5000.0,
                "amount_stddev": 0.0,
                "active_months": ["2024-10"],
                "is_recurring": True,
                "banksalad_category": {"major": "식비", "minor": "카페"},
                "payment_method": "신한카드",
                "time_patterns": {"weekday_pct": 1.0, "lunch_pct": 0.0},
                "similar_merchants": [],
                "pattern": "스타벅스|STARBUCKS",
                "sample_memos": ["Latte"],
            },
            {
                "merchant": "Netflix",
                "transaction_count": 4,
                "total_amount": 68000.0,
                "avg_amount": 17000.0,
                "amount_stddev": 0.0,
                "active_months": ["2024-10"],
                "is_recurring": True,
                "banksalad_category": {"major": "정기지출", "minor": "구독"},
                "payment_method": "신한카드",
                "time_patterns": {"weekday_pct": 1.0, "lunch_pct": 0.0},
                "similar_merchants": [],
                "pattern": "Netflix",
                "sample_memos": ["Monthly plan"],
            },
        ]
        mock_run_tagging.return_value = {"coverage_pct": 99.8}

        result = runner.invoke(
            app,
            [
                "--data-dir",
                str(json_output_data_dir),
                "rules",
                "suggest",
                "--apply",
                "--yes",
                "--json",
            ],
        )

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["applied"] == 2
        assert payload["skipped"] == 0
        assert payload["coverage_before_pct"] == pytest.approx(50.0)
        assert payload["coverage_after_pct"] == pytest.approx(99.8)
        assert mock_apply_suggestion_to_rules.call_count == 2

    @patch("finjuice.pipeline.cli.commands.template_cmd.cli_output.warning")
    @patch("finjuice.pipeline.cli.commands.template_cmd.append_audit_event")
    def test_template_run_output_json_suppresses_audit_warning(
        self,
        mock_append_audit_event,
        mock_cli_warning,
        json_output_data_dir: Path,
    ) -> None:
        """template run --output json should not emit Rich audit warnings."""
        mock_append_audit_event.side_effect = OSError("disk full")

        result = runner.invoke(
            app,
            [
                "--data-dir",
                str(json_output_data_dir),
                "template",
                "run",
                "monthly_spend",
                "--output",
                "json",
            ],
        )

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["_meta"]["command"] == "template run"
        assert payload["row_count"] == 2
        assert payload["template_name"] == "monthly_spend"
        assert {row["month"] for row in payload["rows"]} == {"2024-10", "2024-11"}
        mock_cli_warning.assert_not_called()

    def test_rules_export_json(self, json_output_data_dir: Path) -> None:
        """rules export --json should return a rules array."""
        result = runner.invoke(
            app,
            ["--data-dir", str(json_output_data_dir), "rules", "export", "--json"],
        )

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["rule_count"] == 2
        assert payload["rules"] == [
            {
                "name": "coffee",
                "match": "Starbucks",
                "fields": ["merchant_raw"],
                "tags": ["카페"],
                "category": "카페",
                "priority": 90,
            },
            {
                "name": "streaming",
                "match": "Netflix",
                "fields": ["merchant_raw"],
                "tags": ["구독"],
                "category": "구독",
                "priority": 80,
            },
        ]

    @patch("finjuice.pipeline.tagging.gap_analyzer.simulate_coverage_improvement")
    @patch("finjuice.pipeline.tagging.gap_analyzer.analyze_tag_category_gaps")
    def test_rules_gaps_json(
        self,
        mock_analyze_tag_category_gaps,
        mock_simulate_coverage_improvement,
        json_output_data_dir: Path,
    ) -> None:
        """rules gaps --json should return summary counts and gap arrays."""
        from finjuice.pipeline.tagging.gap_analyzer import CoverageSimulation, GapAnalysis, GapType

        mock_analyze_tag_category_gaps.return_value = {
            GapType.CRITICAL: [
                GapAnalysis(
                    gap_type=GapType.CRITICAL,
                    merchant="새가맹점",
                    transaction_count=8,
                    total_amount=156000.0,
                    current_tags=[],
                    current_category="식비:기타",
                    suggested_action="규칙 추가 필요",
                )
            ],
            GapType.MISMATCH: [
                GapAnalysis(
                    gap_type=GapType.MISMATCH,
                    merchant="카페X",
                    transaction_count=3,
                    total_amount=22000.0,
                    current_tags=["카페"],
                    current_category="생활:기타",
                    suggested_action="카테고리 조정 필요",
                )
            ],
            GapType.PARTIAL: [
                GapAnalysis(
                    gap_type=GapType.PARTIAL,
                    merchant="편의점Y",
                    transaction_count=2,
                    total_amount=8000.0,
                    current_tags=["식비"],
                    current_category="생활:편의점",
                    suggested_action="태그 검토 필요",
                )
            ],
            GapType.COMPLETE: [
                GapAnalysis(
                    gap_type=GapType.COMPLETE,
                    merchant="스타벅스",
                    transaction_count=10,
                    total_amount=55000.0,
                    current_tags=["카페"],
                    current_category="식비:카페",
                    suggested_action="매칭됨",
                )
            ],
        }
        mock_simulate_coverage_improvement.return_value = [
            CoverageSimulation(
                top_n=5,
                expected_tagged=100,
                expected_coverage_pct=91.2,
                improvement_pct=1.2,
            ),
            CoverageSimulation(
                top_n=10,
                expected_tagged=110,
                expected_coverage_pct=91.8,
                improvement_pct=1.8,
            ),
        ]

        result = runner.invoke(
            app,
            ["--data-dir", str(json_output_data_dir), "rules", "gaps", "--json"],
        )

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["summary"]["critical_count"] == 8
        assert payload["summary"]["mismatch_count"] == 5
        assert payload["summary"]["complete_count"] == 10
        assert payload["summary"]["total_mismatch_count"] == 5
        assert payload["summary"]["filtered_mismatch_count"] == 5
        assert payload["summary"]["filtered_out_mismatch_count"] == 0
        assert payload["summary"]["actionable_mismatch_count"] == 5
        assert payload["summary"]["conflict_count"] == 0
        assert payload["summary"]["category_mismatch_count"] == 0
        assert payload["summary"]["multi_tag_noise_count"] == 0
        assert payload["summary"]["actionable_only"] is False
        assert payload["critical_gaps"][0]["merchant"] == "새가맹점"
        assert payload["critical_gaps"][0]["banksalad_category"] == "식비:기타"
        assert payload["mismatches"][0]["gap_type"] == "mismatch"
        assert payload["mismatches"][1]["gap_type"] == "partial"
        assert payload["mismatches"][0]["mismatch_type"] is None
        assert payload["mismatches"][0]["mismatch_severity"] == "none"
        assert payload["mismatches"][0]["actionable"] is True
        assert payload["simulations"] == [
            {
                "top_n": 5,
                "expected_tagged": 100,
                "expected_coverage_pct": 91.2,
                "coverage_improvement_pct": 1.2,
            },
            {
                "top_n": 10,
                "expected_tagged": 110,
                "expected_coverage_pct": 91.8,
                "coverage_improvement_pct": 1.8,
            },
        ]

    @patch(
        "finjuice.pipeline.cli.output._build_meta",
        return_value={
            "schema_version": "1.0",
            "finjuice_version": "test-version",
            "command": "query",
            "timestamp": "2026-04-05T00:00:00+00:00",
        },
    )
    @patch("finjuice.pipeline.cli.commands.query.DuckDBAnalytics")
    def test_query_json_alias(
        self,
        mock_duckdb_analytics,
        mock_build_meta,
        json_output_data_dir: Path,
    ) -> None:
        """query --json should behave the same as --output json."""

        def build_meta(
            command: str,
            schema_version: str = "1.0",
            extras: dict[str, object] | None = None,
        ) -> dict[str, object]:
            meta = {
                "schema_version": schema_version,
                "finjuice_version": "test-version",
                "command": command,
                "timestamp": "2026-04-05T00:00:00+00:00",
            }
            if extras:
                meta.update(extras)
            return meta

        mock_build_meta.side_effect = build_meta
        result_df = pl.DataFrame({"one": [1]})
        count_result = MagicMock()
        count_result.fetchone.return_value = [1]
        page_result = MagicMock()
        page_result.pl.return_value = result_df
        mock_analytics = MagicMock()
        mock_analytics.query_readonly.side_effect = [
            count_result,
            page_result,
            count_result,
            page_result,
        ]
        mock_duckdb_analytics.return_value.__enter__.return_value = mock_analytics

        json_flag_result = runner.invoke(
            app,
            ["--data-dir", str(json_output_data_dir), "query", "SELECT 1 AS one", "--json"],
        )
        output_option_result = runner.invoke(
            app,
            [
                "--data-dir",
                str(json_output_data_dir),
                "query",
                "SELECT 1 AS one",
                "--output",
                "json",
            ],
        )

        assert json_flag_result.exit_code == 0
        assert output_option_result.exit_code == 0
        json_flag_payload = json.loads(json_flag_result.output)
        output_option_payload = json.loads(output_option_result.output)
        assert json_flag_payload == output_option_payload
        assert json_flag_payload == {
            "_meta": {
                **mock_build_meta.return_value,
                "filters_applied": 0,
            },
            "rows": [{"one": 1}],
            "row_count": 1,
            "pagination": {
                "limit": 100,
                "cursor": "0",
                "next_cursor": None,
                "has_more": False,
                "total_estimate": 1,
                "truncated_by_bytes": False,
            },
        }

    def test_query_json_alias_conflict(self, json_output_data_dir: Path) -> None:
        """query should reject conflicting --json and --output values."""
        result = runner.invoke(
            app,
            [
                "--data-dir",
                str(json_output_data_dir),
                "query",
                "SELECT 1 AS one",
                "--json",
                "--output",
                "table",
            ],
        )

        assert result.exit_code == 2  # USAGE_ERROR
        payload = json.loads(result.output)
        assert payload["error"]["code"] == "INVALID_ARGS"
        assert "conflicting --output value" in payload["error"]["message"]


class TestMetaInjection:
    """Verify _meta envelope in dict-type JSON outputs (Issue #284)."""

    _META_REQUIRED_KEYS = {"schema_version", "finjuice_version", "command", "timestamp"}

    @pytest.mark.parametrize(
        ("cmd_args", "expected_command"),
        [
            (["checkup", "--json"], "checkup"),
            (["status", "--json"], "status"),
            (["tag", "--json"], "tag"),
            (["transfer", "--json"], "transfer"),
            (["doctor", "--json"], "doctor"),
            (["query", "SELECT 1 AS one", "--json"], "query"),
            (["explain", "Starbucks", "--json"], "explain"),
            (["rules", "validate", "--json"], "rules validate"),
            (
                [
                    "rules",
                    "add",
                    "--name",
                    "netflix",
                    "--match",
                    "Netflix",
                    "--tags",
                    "구독",
                    "--dry-run",
                    "--json",
                ],
                "rules add",
            ),
            (["template", "list", "--json"], "template list"),
            (["template", "run", "monthly_spend", "--json"], "template run"),
            (["template", "run", "monthly_spend", "--output", "json"], "template run"),
            (["history", "--json"], "history"),
            (["show", "--json"], "show"),
        ],
    )
    def test_meta_present_in_dict_outputs(
        self, json_output_data_dir: Path, cmd_args: list[str], expected_command: str
    ) -> None:
        """Dict-type JSON outputs must contain _meta with required fields."""
        result = runner.invoke(
            app,
            ["--data-dir", str(json_output_data_dir)] + cmd_args,
        )

        assert result.exit_code == 0, f"Command failed: {cmd_args}, output: {result.output[:300]}"
        payload = json.loads(result.output)
        assert isinstance(payload, dict), f"Expected dict output for {cmd_args}"
        assert "_meta" in payload, f"_meta missing in {cmd_args}"
        assert self._META_REQUIRED_KEYS <= set(payload["_meta"].keys())
        assert payload["_meta"]["command"] == expected_command
        assert payload["_meta"]["schema_version"] == "1.0"

    def test_meta_finjuice_version(self, json_output_data_dir: Path) -> None:
        """_meta.finjuice_version should match the package version."""
        from finjuice import __version__

        result = runner.invoke(
            app,
            ["--data-dir", str(json_output_data_dir), "status", "--json"],
        )

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["_meta"]["finjuice_version"] == __version__

    def test_meta_timestamp_is_iso8601(self, json_output_data_dir: Path) -> None:
        """_meta.timestamp should be a valid ISO 8601 datetime."""
        from datetime import datetime

        result = runner.invoke(
            app,
            ["--data-dir", str(json_output_data_dir), "doctor", "--json"],
        )

        assert result.exit_code == 0
        payload = json.loads(result.output)
        ts = payload["_meta"]["timestamp"]
        datetime.fromisoformat(ts)  # Raises ValueError if invalid
