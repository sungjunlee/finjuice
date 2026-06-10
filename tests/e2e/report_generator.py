"""Test report generator for E2E testing.

This module generates comprehensive markdown reports from E2E test metrics,
including performance benchmarks, rule effectiveness, and recommendations.
"""

from datetime import datetime
from pathlib import Path
from typing import Optional

from tests.e2e.metrics import PipelineMetrics, load_performance_budget


class ReportGenerator:
    """Generator for E2E test reports in markdown format."""

    def __init__(self, metrics: PipelineMetrics):
        """Initialize report generator.

        Args:
            metrics: Pipeline metrics to include in report
        """
        self.metrics = metrics
        self.report_lines: list[str] = []

    def _add_line(self, line: str = "") -> None:
        """Add a line to the report."""
        self.report_lines.append(line)

    def _add_header(self, text: str, level: int = 1) -> None:
        """Add a markdown header.

        Args:
            text: Header text
            level: Header level (1-6)
        """
        self._add_line(f"{'#' * level} {text}")
        self._add_line()

    def _add_table(self, headers: list[str], rows: list[list[str]]) -> None:
        """Add a markdown table.

        Args:
            headers: Table header row
            rows: Table data rows
        """
        # Header
        self._add_line("| " + " | ".join(headers) + " |")
        self._add_line("| " + " | ".join(["---"] * len(headers)) + " |")

        # Rows
        for row in rows:
            self._add_line("| " + " | ".join(str(cell) for cell in row) + " |")
        self._add_line()

    def generate_report(self, output_path: Optional[Path] = None) -> str:
        """Generate complete E2E test report.

        Args:
            output_path: Optional path to save report file

        Returns:
            Complete markdown report as string
        """
        self.report_lines = []

        # Header
        self._add_header("End-to-End Test Report")
        self._add_line(f"**Generated:** {datetime.now().isoformat()}")
        self._add_line()

        # Executive Summary
        self._generate_executive_summary()

        # Performance Metrics
        self._generate_performance_section()

        # Coverage Analysis
        self._generate_coverage_section()

        # Rule Effectiveness
        self._generate_rule_effectiveness_section()

        # Transfer Detection
        self._generate_transfer_section()

        # Storage Metrics
        self._generate_storage_section()

        # Recommendations
        self._generate_recommendations()

        # Conclusion
        self._generate_conclusion()

        report = "\n".join(self.report_lines)

        # Save to file if requested
        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(report)

        return report

    def _generate_executive_summary(self) -> None:
        """Generate executive summary section."""
        self._add_header("Executive Summary", 2)

        m = self.metrics
        budget = load_performance_budget()

        # Determine overall status
        all_phases_success = all(p.success for p in m.phases)
        meets_performance = m.total_execution_time < budget
        meets_coverage = m.tag_coverage_pct >= 60

        status = (
            "✅ PASS"
            if (all_phases_success and meets_performance and meets_coverage)
            else "⚠️ NEEDS ATTENTION"
        )  # noqa: E501

        self._add_line(f"**Overall Status:** {status}")
        self._add_line()

        summary_data = [
            ["Metric", "Value", "Target", "Status"],
            [
                "Execution Time",
                f"{m.total_execution_time:.2f}s",
                f"< {budget:.0f}s",
                "✅" if meets_performance else "⚠️",
            ],
            [
                "Total Transactions",
                str(m.total_transactions),
                "N/A",
                "✅" if m.total_transactions > 0 else "❌",
            ],
            [
                "Tag Coverage",
                f"{m.tag_coverage_pct:.1f}%",
                "> 60%",
                "✅" if meets_coverage else "⚠️",
            ],
            [
                "Transfer Pairs Found",
                str(m.transfer_pairs_found),
                "N/A",
                "✅" if m.transfer_pairs_found > 0 else "⚠️",
            ],
            [
                "All Phases Success",
                "Yes" if all_phases_success else "No",
                "Yes",
                "✅" if all_phases_success else "❌",
            ],
        ]

        self._add_table(summary_data[0], summary_data[1:])

    def _generate_performance_section(self) -> None:
        """Generate performance metrics section."""
        self._add_header("Performance Metrics", 2)

        m = self.metrics

        # Phase breakdown table
        self._add_header("Phase Execution Time", 3)
        phase_data = [["Phase", "Time (s)", "Status"]]
        for phase in m.phases:
            status = "✅ Success" if phase.success else f"❌ Failed: {phase.error_message}"
            phase_data.append([phase.name, f"{phase.execution_time:.2f}", status])

        # Add total
        phase_data.append(["**TOTAL**", f"**{m.total_execution_time:.2f}**", ""])

        self._add_table(phase_data[0], phase_data[1:])

        # Throughput metrics
        self._add_header("Throughput", 3)
        throughput_data = [
            ["Metric", "Value"],
            ["Transactions/second", f"{m.transactions_per_second:.2f}"],
            ["Files/second", f"{m.files_per_second:.4f}"],
            [
                "Total execution time",
                f"{m.total_execution_time:.2f}s ({m.total_execution_time / 60:.2f} min)",
            ],
        ]
        self._add_table(throughput_data[0], throughput_data[1:])

    def _generate_coverage_section(self) -> None:
        """Generate coverage analysis section."""
        self._add_header("Coverage Analysis", 2)

        m = self.metrics

        coverage_data = [
            ["Metric", "Value"],
            ["Total Transactions", str(m.total_transactions)],
            ["Tagged Transactions", f"{m.tagged_count} ({m.tag_coverage_pct:.1f}%)"],
            [
                "Untagged Transactions",
                f"{m.total_transactions - m.tagged_count} ({100 - m.tag_coverage_pct:.1f}%)",
            ],
        ]

        self._add_table(coverage_data[0], coverage_data[1:])

        # Coverage interpretation
        if m.tag_coverage_pct >= 75:
            self._add_line("✅ **Excellent coverage** - Tag coverage exceeds expectations.")
        elif m.tag_coverage_pct >= 60:
            self._add_line("✅ **Good coverage** - Tag coverage meets target threshold.")
        else:
            self._add_line(
                "⚠️ **Low coverage** - Tag coverage below 60% target. Review rules and untagged merchants."  # noqa: E501
            )
        self._add_line()

    def _generate_rule_effectiveness_section(self) -> None:
        """Generate rule effectiveness section."""
        self._add_header("Rule Effectiveness", 2)

        m = self.metrics

        if m.untagged_merchants:
            self._add_header("Top Untagged Merchants", 3)
            self._add_line("These merchants appear frequently but are not matched by any rules:")
            self._add_line()

            for i, merchant in enumerate(m.untagged_merchants[:10], 1):
                self._add_line(f"{i}. `{merchant}`")
            self._add_line()

            self._add_line(
                "💡 **Recommendation:** Consider adding rules for these merchants to improve coverage."  # noqa: E501
            )
            self._add_line()
        else:
            self._add_line("✅ All merchants are tagged - excellent rule coverage!")
            self._add_line()

    def _generate_transfer_section(self) -> None:
        """Generate transfer detection section."""
        self._add_header("Transfer Detection", 2)

        m = self.metrics

        transfer_data = [
            ["Metric", "Value"],
            ["Transfer Candidates", str(m.transfer_candidates)],
            ["Transfer Pairs Found", str(m.transfer_pairs_found)],
            [
                "Detection Rate",
                f"{m.transfer_detection_rate:.1f}%" if m.transfer_candidates > 0 else "N/A",
            ],
            [
                "Unpaired Transfers",
                str(max(m.transfer_candidates - m.transfer_paired_transactions, 0))
                if m.transfer_candidates > 0
                else "0",
            ],
        ]

        self._add_table(transfer_data[0], transfer_data[1:])

        # Interpretation
        if m.transfer_candidates == 0:
            self._add_line("ℹ️ No transfer candidates found in the dataset.")
        elif m.transfer_detection_rate >= 80:
            self._add_line(
                "✅ **Excellent transfer detection** - Most transfers are paired correctly."
            )  # noqa: E501
        elif m.transfer_detection_rate >= 50:
            self._add_line(
                "⚠️ **Moderate transfer detection** - Some transfers remain unpaired. This may be expected for one-way transfers."  # noqa: E501
            )
        else:
            self._add_line(
                "⚠️ **Low transfer detection** - Many transfers are unpaired. Review pairing algorithm parameters."  # noqa: E501
            )
        self._add_line()

    def _generate_storage_section(self) -> None:
        """Generate CSV storage metrics section."""
        self._add_header("CSV Storage Metrics", 2)

        m = self.metrics

        storage_data = [
            ["Metric", "Value"],
            [
                "CSV Partition Size",
                f"{m.storage_size_mb:.2f} MB ({m.storage_size_bytes:,} bytes)",
            ],
            ["Transactions Stored", str(m.total_transactions)],
            [
                "Average Size per Transaction",
                f"{m.storage_size_bytes / m.total_transactions:.0f} bytes"
                if m.total_transactions > 0
                else "N/A",
            ],
        ]

        self._add_table(storage_data[0], storage_data[1:])

    def _generate_recommendations(self) -> None:
        """Generate recommendations section."""
        self._add_header("Recommendations", 2)

        m = self.metrics
        recommendations = []

        # Performance recommendations
        budget = load_performance_budget()
        if m.total_execution_time > budget:
            recommendations.append(
                f"⚠️ **Performance**: Execution time exceeds the {budget:.0f}s baseline. "
                "Consider narrowing the date range or using partition-aware queries."
            )

        # Coverage recommendations
        if m.tag_coverage_pct < 60:
            recommendations.append(
                f"⚠️ **Coverage**: Tag coverage ({m.tag_coverage_pct:.1f}%) is below 60% target. Add rules for top untagged merchants."  # noqa: E501
            )

        # Transfer recommendations
        if m.transfer_candidates > 0 and m.transfer_detection_rate < 50:
            recommendations.append(
                f"⚠️ **Transfers**: Transfer detection rate ({m.transfer_detection_rate:.1f}%) is low. Review time window and amount tolerance parameters."  # noqa: E501
            )

        # Storage size recommendations
        if m.storage_size_mb > 100:
            recommendations.append(
                f"ℹ️ **Storage**: CSV partitions ({m.storage_size_mb:.1f} MB) are growing large. Consider archiving old transactions."  # noqa: E501
            )

        # Phase failure recommendations
        failed_phases = [p for p in m.phases if not p.success]
        if failed_phases:
            for phase in failed_phases:
                recommendations.append(
                    f"❌ **{phase.name.capitalize()} Phase**: Failed with error: {phase.error_message}"  # noqa: E501
                )

        if recommendations:
            for rec in recommendations:
                self._add_line(f"- {rec}")
            self._add_line()
        else:
            self._add_line("✅ All metrics meet targets - no action required!")
            self._add_line()

    def _generate_conclusion(self) -> None:
        """Generate conclusion section."""
        self._add_header("Conclusion", 2)

        m = self.metrics

        all_phases_success = all(p.success for p in m.phases)
        meets_performance = m.total_execution_time < load_performance_budget()
        meets_coverage = m.tag_coverage_pct >= 60

        if all_phases_success and meets_performance and meets_coverage:
            self._add_line(
                "✅ **PIPELINE READY FOR PRODUCTION** - All tests passed and metrics meet targets."  # noqa: E501
            )
        elif all_phases_success:
            self._add_line(
                "⚠️ **PIPELINE FUNCTIONAL BUT NEEDS OPTIMIZATION** - All phases completed successfully, but some metrics need improvement."  # noqa: E501
            )
        else:
            self._add_line(
                "❌ **PIPELINE HAS ISSUES** - Some phases failed. Review errors and fix before proceeding."  # noqa: E501
            )
        self._add_line()

        # Next steps
        self._add_header("Next Steps", 3)
        if all_phases_success and meets_performance and meets_coverage:
            self._add_line("1. Proceed with production deployment")
            self._add_line("2. Monitor performance metrics in production")
            self._add_line("3. Continue adding rules for edge cases")
        else:
            self._add_line("1. Review and address recommendations above")
            self._add_line("2. Fix any failed phases")
            self._add_line("3. Re-run E2E tests to validate improvements")
            self._add_line("4. Iterate until all metrics meet targets")
        self._add_line()
