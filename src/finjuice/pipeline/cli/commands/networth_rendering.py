"""Human-readable Rich rendering for ``finjuice networth`` commands."""

from __future__ import annotations

from typing import Any

from rich.table import Table

from finjuice.pipeline.cli.output import console, info, section, success, table_summary
from finjuice.pipeline.forecast import SCENARIO_NAMES


def _format_krw(amount: float) -> str:
    """Format amount as KRW."""
    sign = "-" if amount < 0 else ""
    return f"{sign}₩{abs(amount):,.0f}"


def _select_projection_rows(projections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep text output readable for long forecast horizons."""
    if len(projections) <= 24:
        return projections

    selected: list[dict[str, Any]] = [projections[0]]
    last_index = len(projections) - 1
    for index, row in enumerate(projections[1:], start=1):
        if index == last_index or index % 12 == 0 or row["events_fired"]:
            selected.append(row)
    return selected


def _render_overview(result: dict[str, Any]) -> None:
    """Render the top-level net worth summary."""
    section("Net Worth")
    table_summary(
        "Aggregated Position",
        [
            ("As Of", result["as_of"] or "-"),
            ("Total Assets", _format_krw(result["total_assets"])),
            ("Total Liabilities", _format_krw(result["total_liabilities"])),
            ("Net Worth", _format_krw(result["net_worth"])),
        ],
    )

    if not result["_assets"] and not result["_liabilities"]:
        info("자산 스냅샷과 assets.yaml 항목이 없어 총액은 0원입니다.")
        return

    success(
        f"Aggregated {len(result['_assets'])} assets and {len(result['_liabilities'])} liabilities"
    )


def _render_breakdown(as_of: str | None, rows: list[dict[str, Any]], *, by: str) -> None:
    """Render a breakdown table."""
    section("Net Worth Breakdown")

    if not rows:
        info("집계할 자산이 없습니다.")
        return

    table = Table(title=f"As Of {as_of or '-'}")
    table.add_column("Category" if by == "category" else "Asset", style="cyan")
    table.add_column("Value", justify="right", style="green")
    table.add_column("Share", justify="right")

    label_key = "category" if by == "category" else "asset_name"
    for row in rows:
        table.add_row(
            str(row[label_key]),
            _format_krw(float(row["value"])),
            f"{float(row['share_pct']):.2f}%",
        )

    console.print(table)
    success(f"{len(rows)} breakdown rows")


def _render_history(rows: list[dict[str, Any]]) -> None:
    """Render history rows."""
    section("Net Worth History")

    if not rows:
        info(
            "가용한 자산 스냅샷 이력이 없습니다."
            " 자산 스냅샷을 추가하려면 finjuice assets status 를 확인하거나"
            " assets.yaml 을 생성하세요."
        )
        return

    table = Table(title="Monthly Snapshot History")
    table.add_column("As Of", style="cyan")
    table.add_column("Net Worth", justify="right", style="green")
    for row in rows:
        table.add_row(str(row["as_of"]), _format_krw(float(row["net_worth"])))

    console.print(table)
    success(f"{len(rows)} historical points")


def _render_forecast(result: dict[str, Any]) -> None:
    """Render one scenario forecast result."""
    summary = result["summary"]
    section("Net Worth Forecast")
    summary_rows = [
        ("Scenario", str(result["scenario"])),
        ("Start", str(summary["start"])),
        ("End", str(summary["end"])),
        ("Years", str(summary["years"])),
        ("Start Net Worth", _format_krw(float(summary["start_net_worth"]))),
        ("End Net Worth", _format_krw(float(summary["end_net_worth"]))),
        (
            "CAGR",
            "-" if summary["cagr"] is None else f"{float(summary['cagr']) * 100:.2f}%",
        ),
        ("Events Fired", str(summary["events_count"])),
    ]
    if summary.get("target_net_worth") is not None:
        summary_rows.append(("Target", _format_krw(float(summary["target_net_worth"]))))
        reached_label = summary.get("target_reached_at") if summary.get("target_reached") else "No"
        summary_rows.append(("Reached", str(reached_label)))
    table_summary("Scenario Summary", summary_rows)

    checkpoints = _select_projection_rows(result["projections"])
    if not checkpoints:
        info("투영할 데이터가 없습니다.")
        return

    table = Table(title="Projection Checkpoints")
    table.add_column("Date", style="cyan")
    table.add_column("Net Worth", justify="right", style="green")
    table.add_column("Assets", justify="right")
    table.add_column("Liabilities", justify="right")
    table.add_column("Events")

    for row in checkpoints:
        events = ", ".join(event["name"] for event in row["events_fired"]) or "-"
        table.add_row(
            str(row["date"]),
            _format_krw(float(row["net_worth"])),
            _format_krw(float(row["total_assets"])),
            _format_krw(float(row["total_liabilities"])),
            events,
        )

    console.print(table)
    success(f"{len(result['projections'])} forecast points")


def _render_forecast_comparison(
    scenarios: dict[str, dict[str, Any]],
    *,
    years: int,
) -> None:
    """Render the multi-scenario comparison view."""
    show_goal_status = any(
        scenario_result["summary"].get("target_net_worth") is not None
        for scenario_result in scenarios.values()
    )
    section("Net Worth Forecast")
    table = Table(title=f"Scenario Comparison ({years}y)")
    table.add_column("Scenario", style="cyan")
    table.add_column("End Net Worth", justify="right", style="green")
    table.add_column("CAGR", justify="right")
    if show_goal_status:
        table.add_column("Reached", justify="center")
    table.add_column("Events", justify="right")

    for scenario_name in SCENARIO_NAMES:
        scenario_result = scenarios[scenario_name]
        summary = scenario_result["summary"]
        row = [
            scenario_name,
            _format_krw(float(summary["end_net_worth"])),
            "-" if summary["cagr"] is None else f"{float(summary['cagr']) * 100:.2f}%",
        ]
        if show_goal_status:
            reached_label = (
                summary.get("target_reached_at") if summary.get("target_reached") else "No"
            )
            row.append(str(reached_label))
        row.append(str(summary["events_count"]))
        table.add_row(*row)

    console.print(table)
    success(f"Compared {len(scenarios)} scenarios")


def _render_validate(result: dict[str, Any]) -> None:
    """Render assets.yaml validation output."""
    section("assets.yaml Validation")

    if not result["exists"]:
        info("assets.yaml 없음. networth는 자산 스냅샷만으로 계속 동작합니다.")
        return

    if result["valid"]:
        table_summary(
            "Schema Summary",
            [
                ("Version", str(result["version"])),
                ("Manual Assets", str(result["manual_assets"])),
                ("Liabilities", str(result["liabilities"])),
            ],
        )
        success("assets.yaml is valid")
        return

    for issue in result["problems"]:
        console.print(f"[red]❌ {issue['formatted']}[/red]")
