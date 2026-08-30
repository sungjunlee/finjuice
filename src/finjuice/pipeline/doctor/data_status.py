"""Transaction data and partition-schema doctor checks."""

from __future__ import annotations

from pathlib import Path

import polars as pl

from finjuice.pipeline.config import Config
from finjuice.pipeline.doctor.models import CheckResult
from finjuice.pipeline.storage.schema_registry import (
    PartitionSchemaSummary,
    SchemaCompatibilityState,
    get_schema_migration_guidance,
    summarize_partition_schema_versions,
)


def _check_data_status(config: Config) -> list[CheckResult]:
    """Check data status."""
    results = []

    transactions_dir = config.csv_base_dir
    if not transactions_dir.exists():
        results.append(
            CheckResult(
                status="warning",
                message="트랜잭션 데이터 없음",
                suggestion="finjuice import 실행 필요",
                name="transactions_directory",
            )
        )
        return results

    # Count partitions and rows
    partitions = list(transactions_dir.rglob("*.csv"))
    if not partitions:
        results.append(
            CheckResult(
                status="warning",
                message="CSV 파티션 없음",
                suggestion="finjuice import 실행 필요",
                name="transaction_partitions",
            )
        )
        return results

    schema_summary = summarize_partition_schema_versions(
        partitions,
        metadata_dir=config.data_dir / "metadata",
    )
    results.append(_schema_summary_check(schema_summary, config.data_dir))

    total_rows = 0
    min_date = None
    max_date = None

    for partition_path in partitions:
        try:
            df = pl.read_csv(partition_path)
            total_rows += len(df)

            if len(df) > 0 and "date" in df.columns:
                partition_min = df.select(pl.col("date").min()).item()
                partition_max = df.select(pl.col("date").max()).item()

                if min_date is None or partition_min < min_date:
                    min_date = partition_min
                if max_date is None or partition_max > max_date:
                    max_date = partition_max
        except (OSError, pl.exceptions.ComputeError):
            pass

    # Calculate period in months
    month_count = len(partitions)
    date_range = ""
    if min_date and max_date:
        date_range = f" ({min_date} ~ {max_date})"

    results.append(
        CheckResult(
            status="ok",
            message=f"transactions/: {total_rows:,}건 ({month_count}개월){date_range}",
            name="transactions_summary",
        )
    )

    # Check imports
    imports_dir = config.import_dir
    if imports_dir.exists():
        xlsx_files = list(imports_dir.glob("*.xlsx"))
        if xlsx_files:
            results.append(
                CheckResult(
                    status="ok",
                    message=f"imports/: {len(xlsx_files)}개 XLSX 파일",
                    name="imports_directory",
                )
            )

            # Check for unprocessed XLSX (compare with import history)
            import_history_path = config.data_dir / "metadata" / "import_history.csv"
            if import_history_path.exists():
                try:
                    history_df = pl.read_csv(import_history_path)
                    processed_files = set(
                        history_df["original_filename"].to_list()
                        if "original_filename" in history_df.columns
                        else []
                    )
                    unprocessed = [f for f in xlsx_files if f.name not in processed_files]
                    if unprocessed:
                        results.append(
                            CheckResult(
                                status="warning",
                                message=f"처리되지 않은 XLSX {len(unprocessed)}개",
                                suggestion="finjuice refresh 실행 권장",
                                name="unprocessed_imports",
                            )
                        )
                except (OSError, pl.exceptions.ComputeError):
                    pass
        else:
            results.append(
                CheckResult(
                    status="ok",
                    message="imports/: XLSX 파일 없음",
                    name="imports_directory",
                )
            )

    return results


def _schema_summary_check(schema_summary: PartitionSchemaSummary, data_dir: Path) -> CheckResult:
    """Render transaction partition schema compatibility as a doctor check."""
    guidance = get_schema_migration_guidance(schema_summary, metadata_dir=data_dir / "metadata")

    if schema_summary.state is SchemaCompatibilityState.ACTIVE:
        version = (
            schema_summary.active_versions[-1] if schema_summary.active_versions else "unknown"
        )
        return CheckResult(
            status="ok",
            message=f"CSV schema: active v{version}",
            name="transaction_schema_compatibility",
        )

    if schema_summary.state is SchemaCompatibilityState.COMPATIBLE_LEGACY:
        versions = ", ".join(f"v{version}" for version in schema_summary.compatible_legacy_versions)
        return CheckResult(
            status="warning",
            message=f"CSV schema: compatible legacy schema {versions} detected",
            detail=guidance["message"],
            suggestion=guidance["command"],
            name="transaction_schema_compatibility",
        )

    unsupported_versions = ", ".join(
        f"v{version}" if version is not None else "unknown"
        for version in schema_summary.unsupported_versions
    )
    return CheckResult(
        status="error",
        message=f"CSV schema: unsupported partitions detected ({unsupported_versions})",
        detail=guidance["message"],
        suggestion=guidance["command"],
        name="transaction_schema_compatibility",
    )
