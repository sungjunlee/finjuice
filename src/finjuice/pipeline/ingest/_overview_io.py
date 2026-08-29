"""Banksalad overview preview and write helpers for the ingest pipeline.

Public ingest entry points stay in ``pipeline.py``. This module owns overview
table preview, partition writes, and summary merging.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl

from ..storage import csv_partition
from ._overview_processor import parse_banksalad_overview
from ._partition_preview import (
    _OverviewPreviewSpec,
    _preview_append_banksalad_cashflow,
    _preview_append_banksalad_overview_table,
)

_OVERVIEW_TABLE_NAMES = (
    "overview_facts",
    "balance",
    "cashflow",
    "insurance",
    "investments",
    "loans",
)


@dataclass
class _OverviewPreviewCaches:
    overview_facts: dict[tuple[int, int], set[tuple[object, ...]]]
    balance: dict[tuple[int, int], set[tuple[object, ...]]]
    cashflow: dict[tuple[int, int], set[tuple[object, ...]]]
    insurance: dict[tuple[int, int], set[tuple[object, ...]]]
    investments: dict[tuple[int, int], set[tuple[object, ...]]]
    loans: dict[tuple[int, int], set[tuple[object, ...]]]


@dataclass(frozen=True)
class _OverviewPreviewFrames:
    overview_facts: pl.DataFrame
    balance: pl.DataFrame
    cashflow: pl.DataFrame
    insurance: pl.DataFrame
    investments: pl.DataFrame
    loans: pl.DataFrame
    warnings: list[str]


def _banksalad_overview_base_dir(csv_base_dir: Path) -> Path:
    return csv_base_dir.parent / "banksalad"


def _empty_overview_preview_summary() -> dict[str, Any]:
    return {
        table_name: {
            "estimated_new_rows": 0,
            "estimated_dedup_skips": 0,
            "affected_partitions": [],
        }
        for table_name in _OVERVIEW_TABLE_NAMES
    } | {"warnings": []}


def _empty_overview_write_summary() -> dict[str, Any]:
    return {
        table_name: {
            "inserted": 0,
            "dedup_skips": 0,
            "partitions_updated": 0,
        }
        for table_name in _OVERVIEW_TABLE_NAMES
    } | {"warnings": []}


def _preview_banksalad_overview(
    banksalad_base_dir: Path,
    caches: _OverviewPreviewCaches,
    frames: _OverviewPreviewFrames,
) -> dict[str, Any]:
    result = _empty_overview_preview_summary()
    result["overview_facts"] = _preview_overview_table_result(
        _preview_append_banksalad_overview_table(
            banksalad_base_dir / "overview_facts",
            frames.overview_facts,
            caches.overview_facts,
            _OverviewPreviewSpec(
                dedup_key=csv_partition.BANKSALAD_OVERVIEW_FACT_DEDUP_KEY,
                read_month=csv_partition.read_banksalad_overview_facts_month,
                path_builder=csv_partition.get_banksalad_overview_facts_partition_path,
                partition_column="snapshot_date",
            ),
        )
    )
    result["balance"] = _preview_overview_table_result(
        _preview_append_banksalad_overview_table(
            banksalad_base_dir / "balance",
            frames.balance,
            caches.balance,
            _OverviewPreviewSpec(
                dedup_key=csv_partition.BANKSALAD_BALANCE_DEDUP_KEY,
                read_month=csv_partition.read_banksalad_balance_month,
                path_builder=csv_partition.get_banksalad_balance_partition_path,
                partition_column="snapshot_date",
            ),
        )
    )
    result["cashflow"] = _preview_overview_table_result(
        _preview_append_banksalad_cashflow(
            banksalad_base_dir / "cashflow",
            frames.cashflow,
            caches.cashflow,
        )
    )
    result["insurance"] = _preview_overview_table_result(
        _preview_append_banksalad_overview_table(
            banksalad_base_dir / "insurance",
            frames.insurance,
            caches.insurance,
            _OverviewPreviewSpec(
                dedup_key=csv_partition.BANKSALAD_INSURANCE_DEDUP_KEY,
                read_month=csv_partition.read_banksalad_insurance_month,
                path_builder=csv_partition.get_banksalad_insurance_partition_path,
                partition_column="snapshot_date",
            ),
        )
    )
    result["investments"] = _preview_overview_table_result(
        _preview_append_banksalad_overview_table(
            banksalad_base_dir / "investments",
            frames.investments,
            caches.investments,
            _OverviewPreviewSpec(
                dedup_key=csv_partition.BANKSALAD_INVESTMENT_DEDUP_KEY,
                read_month=csv_partition.read_banksalad_investment_month,
                path_builder=csv_partition.get_banksalad_investment_partition_path,
                partition_column="snapshot_date",
            ),
        )
    )
    result["loans"] = _preview_overview_table_result(
        _preview_append_banksalad_overview_table(
            banksalad_base_dir / "loans",
            frames.loans,
            caches.loans,
            _OverviewPreviewSpec(
                dedup_key=csv_partition.BANKSALAD_LOAN_DEDUP_KEY,
                read_month=csv_partition.read_banksalad_loan_month,
                path_builder=csv_partition.get_banksalad_loan_partition_path,
                partition_column="snapshot_date",
            ),
        )
    )
    result["warnings"] = frames.warnings
    return result


def _write_banksalad_overview(
    file_path: Path,
    csv_base_dir: Path,
    file_id: str,
    file_mtime: str,
) -> dict[str, Any]:
    parsed = parse_banksalad_overview(file_path=file_path, file_id=file_id, file_mtime=file_mtime)
    banksalad_base_dir = _banksalad_overview_base_dir(csv_base_dir)
    result = _empty_overview_write_summary()

    result["overview_facts"] = _write_overview_table_result(
        csv_partition.append_banksalad_overview_facts(
            banksalad_base_dir / "overview_facts",
            parsed.overview_facts,
        )
    )
    result["balance"] = _write_overview_table_result(
        csv_partition.append_banksalad_balance(banksalad_base_dir / "balance", parsed.balance)
    )
    result["cashflow"] = _write_overview_table_result(
        csv_partition.append_banksalad_cashflow(banksalad_base_dir / "cashflow", parsed.cashflow)
    )
    result["insurance"] = _write_overview_table_result(
        csv_partition.append_banksalad_insurance(
            banksalad_base_dir / "insurance",
            parsed.insurance,
        )
    )
    result["investments"] = _write_overview_table_result(
        csv_partition.append_banksalad_investments(
            banksalad_base_dir / "investments",
            parsed.investments,
        )
    )
    result["loans"] = _write_overview_table_result(
        csv_partition.append_banksalad_loans(
            banksalad_base_dir / "loans",
            parsed.loans,
        )
    )
    result["warnings"] = parsed.warnings
    return result


def _write_overview_table_result(append_result: dict[str, Any]) -> dict[str, int]:
    return {
        "inserted": int(append_result["rows_inserted"]),
        "dedup_skips": int(append_result["rows_skipped"]),
        "partitions_updated": int(append_result["partitions_updated"]),
    }


def _preview_overview_table_result(preview_result: dict[str, Any]) -> dict[str, Any]:
    return {
        "estimated_new_rows": int(preview_result["rows_inserted"]),
        "estimated_dedup_skips": int(preview_result["rows_skipped"]),
        "affected_partitions": preview_result["affected_partitions"],
    }


def _merge_overview_preview_totals(total: dict[str, Any], item: dict[str, Any]) -> None:
    for table_name in _OVERVIEW_TABLE_NAMES:
        total[table_name]["estimated_new_rows"] += int(item[table_name]["estimated_new_rows"])
        total[table_name]["estimated_dedup_skips"] += int(item[table_name]["estimated_dedup_skips"])
        total[table_name]["affected_partitions"].extend(item[table_name]["affected_partitions"])
    total["warnings"].extend(item["warnings"])


def _merge_overview_write_totals(total: dict[str, Any], item: dict[str, Any]) -> None:
    for table_name in _OVERVIEW_TABLE_NAMES:
        total[table_name]["inserted"] += int(item[table_name]["inserted"])
        total[table_name]["dedup_skips"] += int(item[table_name]["dedup_skips"])
        total[table_name]["partitions_updated"] += int(item[table_name]["partitions_updated"])
    total["warnings"].extend(item["warnings"])


def _sorted_overview_summary(summary: dict[str, Any]) -> dict[str, Any]:
    sorted_summary = {key: value.copy() for key, value in summary.items() if key != "warnings"}
    for table_name in _OVERVIEW_TABLE_NAMES:
        sorted_summary[table_name]["affected_partitions"] = sorted(
            set(sorted_summary[table_name]["affected_partitions"])
        )
    sorted_summary["warnings"] = list(summary["warnings"])
    return sorted_summary


def _overview_has_writes(summary: dict[str, Any]) -> bool:
    return any(summary[table_name]["inserted"] > 0 for table_name in _OVERVIEW_TABLE_NAMES)
