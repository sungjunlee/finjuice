"""Fence regressions for remaining legacy finance writers."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import polars as pl
import pytest

from finjuice.pipeline.metadata import import_history
from finjuice.pipeline.storage import atomic_files, csv_assets
from finjuice.pipeline.storage import csv_banksalad_overview_helpers as overview_helpers
from finjuice.pipeline.storage import csv_banksalad_overview_write as overview_write
from finjuice.pipeline.storage.csv_schema import get_asset_snapshot_partition_path
from finjuice.pipeline.storage.sqlite.errors import (
    AuthorityEvidenceUnavailableError,
    RepositoryPathError,
)

_EMPTY_APPEND = {
    "total_rows": 0,
    "partitions_updated": 0,
    "rows_inserted": 0,
    "rows_skipped": 0,
}
_SOURCE_STAMP_NS = 1_000_000_000_123_456_789
_REPLACEMENT_STAMP_NS = 1_000_000_001_123_456_789


def _data_dir(tmp_path: Path) -> Path:
    return tmp_path.resolve()


def _activate(data_dir: Path) -> None:
    activation = data_dir / ".finjuice" / "authority" / "active.json"
    activation.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    activation.parent.chmod(0o700)
    activation.write_text("{}", encoding="utf-8")


def _asset_df() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "snapshot_date": ["2026-02-20"],
            "account_id": ["acc_kb"],
            "instrument_id": ["ins_aapl"],
            "quantity": [10.0],
            "market_value": [1_500_000.0],
            "currency": ["KRW"],
            "file_id": ["260220_1"],
            "source_row": [2],
        }
    )


def _facts_df() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "fact_id": ["fact_a"],
            "snapshot_date": ["2026-06-15"],
            "sheet_name": ["overview"],
            "block_id": ["balance"],
            "block_title": ["Synthetic Balance"],
            "fact_kind": ["table_value"],
            "row_label": ["asset_total"],
            "column_label": ["current"],
            "value_numeric": [200.0],
            "value_text": [None],
            "value_type": ["number"],
            "file_id": ["260615_1"],
            "source_row": [4],
            "source_col": [2],
        }
    )


def _balance_df() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "snapshot_date": ["2026-06-15"],
            "side": ["asset"],
            "category": ["deposit"],
            "item_name": ["item_a"],
            "amount": [200.0],
            "currency": ["KRW"],
            "source_fact_id": ["fact_a"],
            "file_id": ["260615_1"],
            "source_row": [5],
        }
    )


def _cashflow_df() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "snapshot_date": ["2026-06-15"],
            "period_month": ["2026-06"],
            "category": ["income"],
            "amount": [120.0],
            "source_fact_id": ["fact_income"],
            "file_id": ["260615_1"],
        }
    )


def _insurance_df() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "snapshot_date": ["2026-06-15"],
            "institution": ["insurer_a"],
            "policy_name": ["policy_a"],
            "contract_status": ["active"],
            "paid_amount": [120.0],
            "contract_date": ["2024-02-01"],
            "maturity_date": ["2034-02-01"],
            "currency": ["KRW"],
            "source_fact_id": ["fact_a"],
            "file_id": ["260615_1"],
            "source_row": [5],
        }
    )


def _investment_df() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "snapshot_date": ["2026-06-15"],
            "product_type": ["stock"],
            "institution": ["broker_a"],
            "product_name": ["holding_a"],
            "principal_amount": [100.0],
            "valuation_amount": [120.0],
            "return_rate": [20.0],
            "start_date": ["2025-02-01"],
            "maturity_date": [None],
            "currency": ["KRW"],
            "source_fact_id": ["fact_a"],
            "file_id": ["260615_1"],
            "source_row": [5],
        }
    )


def _loan_df() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "snapshot_date": ["2026-06-15"],
            "loan_type": ["mortgage"],
            "institution": ["bank_a"],
            "product_name": ["loan_a"],
            "principal_amount": [500.0],
            "balance_amount": [450.0],
            "interest_rate": [3.8],
            "start_date": ["2024-02-01"],
            "maturity_date": ["2029-02-01"],
            "currency": ["KRW"],
            "source_fact_id": ["fact_a"],
            "file_id": ["260615_1"],
            "source_row": [5],
        }
    )


def _xlsx_source(tmp_path: Path) -> Path:
    source = tmp_path.resolve() / "source.xlsx"
    source.write_bytes(b"synthetic-xlsx")
    return source


def _stamp(path: Path, stamp: int = _SOURCE_STAMP_NS) -> int:
    os.utime(path, ns=(stamp, stamp))
    return stamp


def _seed_archive(tmp_path: Path) -> tuple[Path, Path, Path, bytes, int]:
    data_dir = _data_dir(tmp_path)
    source = _xlsx_source(tmp_path)
    source.chmod(0o640)
    stamp = _stamp(source)
    archived = import_history.archive_source_file(source, "241027_1", authority_data_dir=data_dir)
    return data_dir, source, archived, b"synthetic-xlsx", stamp


Writer = Callable[[Path], Any]


def _writers(empty: bool) -> list[tuple[str, Writer, Path]]:
    empty_df = pl.DataFrame()
    asset = _asset_df() if not empty else empty_df
    facts = _facts_df() if not empty else empty_df
    balance = _balance_df() if not empty else empty_df
    cashflow = _cashflow_df() if not empty else empty_df
    insurance = _insurance_df() if not empty else empty_df
    investment = _investment_df() if not empty else empty_df
    loan = _loan_df() if not empty else empty_df
    return [
        (
            "write_asset",
            lambda data_dir: csv_assets.write_asset_snapshot_month(
                asset, 2026, 2, authority_data_dir=data_dir
            ),
            Path("assets") / "snapshots" / "2026" / "02" / "snapshots.csv",
        ),
        (
            "append_asset",
            lambda data_dir: csv_assets.append_asset_snapshots(asset, authority_data_dir=data_dir),
            Path("assets") / "snapshots" / "2026" / "02" / "snapshots.csv",
        ),
        (
            "write_facts",
            lambda data_dir: overview_write.write_banksalad_overview_facts_month(
                facts, 2026, 6, authority_data_dir=data_dir
            ),
            Path("banksalad") / "overview_facts" / "2026" / "06" / "facts.csv",
        ),
        (
            "append_facts",
            lambda data_dir: overview_write.append_banksalad_overview_facts(
                facts, authority_data_dir=data_dir
            ),
            Path("banksalad") / "overview_facts" / "2026" / "06" / "facts.csv",
        ),
        (
            "write_balance",
            lambda data_dir: overview_write.write_banksalad_balance_month(
                balance, 2026, 6, authority_data_dir=data_dir
            ),
            Path("banksalad") / "balance" / "2026" / "06" / "balance.csv",
        ),
        (
            "append_balance",
            lambda data_dir: overview_write.append_banksalad_balance(
                balance, authority_data_dir=data_dir
            ),
            Path("banksalad") / "balance" / "2026" / "06" / "balance.csv",
        ),
        (
            "write_cashflow",
            lambda data_dir: overview_write.write_banksalad_cashflow_month(
                cashflow, 2026, 6, authority_data_dir=data_dir
            ),
            Path("banksalad") / "cashflow" / "2026" / "06" / "cashflow.csv",
        ),
        (
            "append_cashflow",
            lambda data_dir: overview_write.append_banksalad_cashflow(
                cashflow, authority_data_dir=data_dir
            ),
            Path("banksalad") / "cashflow" / "2026" / "06" / "cashflow.csv",
        ),
        (
            "write_insurance",
            lambda data_dir: overview_write.write_banksalad_insurance_month(
                insurance, 2026, 6, authority_data_dir=data_dir
            ),
            Path("banksalad") / "insurance" / "2026" / "06" / "insurance.csv",
        ),
        (
            "append_insurance",
            lambda data_dir: overview_write.append_banksalad_insurance(
                insurance, authority_data_dir=data_dir
            ),
            Path("banksalad") / "insurance" / "2026" / "06" / "insurance.csv",
        ),
        (
            "write_investments",
            lambda data_dir: overview_write.write_banksalad_investment_month(
                investment, 2026, 6, authority_data_dir=data_dir
            ),
            Path("banksalad") / "investments" / "2026" / "06" / "investments.csv",
        ),
        (
            "append_investments",
            lambda data_dir: overview_write.append_banksalad_investments(
                investment, authority_data_dir=data_dir
            ),
            Path("banksalad") / "investments" / "2026" / "06" / "investments.csv",
        ),
        (
            "write_loans",
            lambda data_dir: overview_write.write_banksalad_loan_month(
                loan, 2026, 6, authority_data_dir=data_dir
            ),
            Path("banksalad") / "loans" / "2026" / "06" / "loans.csv",
        ),
        (
            "append_loans",
            lambda data_dir: overview_write.append_banksalad_loans(
                loan, authority_data_dir=data_dir
            ),
            Path("banksalad") / "loans" / "2026" / "06" / "loans.csv",
        ),
    ]


def _finance_paths(data_dir: Path) -> list[Path]:
    return [
        data_dir / "assets",
        data_dir / "banksalad",
        data_dir / "metadata" / "import_history.csv",
        data_dir / "metadata" / "archives",
    ]


def test_inactive_asset_and_overview_writes_are_idempotent(tmp_path: Path) -> None:
    data_dir = _data_dir(tmp_path)
    first = csv_assets.append_asset_snapshots(_asset_df(), authority_data_dir=data_dir)
    second = csv_assets.append_asset_snapshots(_asset_df(), authority_data_dir=data_dir)
    facts_first = overview_write.append_banksalad_overview_facts(
        _facts_df(), authority_data_dir=data_dir
    )
    facts_second = overview_write.append_banksalad_overview_facts(
        _facts_df(), authority_data_dir=data_dir
    )
    cashflow_empty = overview_write.append_banksalad_cashflow(
        pl.DataFrame(), authority_data_dir=data_dir
    )

    partition = get_asset_snapshot_partition_path(data_dir / "assets" / "snapshots", 2026, 2)
    assert first["rows_inserted"] == 1
    assert second == {
        "total_rows": 1,
        "partitions_updated": 0,
        "rows_inserted": 0,
        "rows_skipped": 1,
    }
    assert facts_first["rows_inserted"] == 1
    assert facts_second["rows_inserted"] == 0
    assert cashflow_empty == _EMPTY_APPEND
    assert partition.exists()
    assert not (data_dir / "banksalad" / "cashflow").exists()


def test_inactive_metadata_record_and_archive_keep_counts_and_paths(tmp_path: Path) -> None:
    data_dir = _data_dir(tmp_path)
    source = _xlsx_source(tmp_path)
    file_id = import_history.record_import(
        source, "2026-02-20T00:00:00", 3, authority_data_dir=data_dir
    )
    archived = import_history.archive_source_file(source, file_id, authority_data_dir=data_dir)
    again = import_history.record_import(
        source,
        "2026-02-20T00:00:00",
        4,
        archived=True,
        archived_path=archived,
        authority_data_dir=data_dir,
    )

    history = data_dir / "metadata" / "import_history.csv"
    assert file_id == again
    assert archived == data_dir / "metadata" / "archives" / f"{file_id}.xlsx"
    assert archived.read_bytes() == b"synthetic-xlsx"
    assert history.exists()
    assert pl.read_csv(history).height == 1


@pytest.mark.parametrize("empty", [False, True])
def test_active_root_rejects_every_entrypoint_before_writes(tmp_path: Path, empty: bool) -> None:
    data_dir = _data_dir(tmp_path)
    _activate(data_dir)
    source = _xlsx_source(tmp_path)

    for _name, writer, relative in _writers(empty=empty):
        with pytest.raises(AuthorityEvidenceUnavailableError):
            writer(data_dir)
        assert not (data_dir / relative).exists()

    with pytest.raises(AuthorityEvidenceUnavailableError):
        import_history.record_import(source, "2026-02-20T00:00:00", 1, authority_data_dir=data_dir)
    with pytest.raises(AuthorityEvidenceUnavailableError):
        import_history.archive_source_file(source, "241027_1", authority_data_dir=data_dir)
    for path in _finance_paths(data_dir):
        assert not path.exists()


def test_inactive_alias_to_active_target_is_rejected(tmp_path: Path) -> None:
    root = _data_dir(tmp_path)
    active = root / "active"
    alias = root / "alias"
    active.mkdir()
    alias.symlink_to(active, target_is_directory=True)
    _activate(active)
    sentinel = active / "victim.csv"
    sentinel.write_bytes(b"unchanged")

    with pytest.raises(RepositoryPathError):
        csv_assets.append_asset_snapshots(_asset_df(), authority_data_dir=alias)
    with pytest.raises(RepositoryPathError):
        overview_write.append_banksalad_cashflow(pl.DataFrame(), authority_data_dir=alias)
    with pytest.raises(RepositoryPathError):
        import_history.record_import(
            _xlsx_source(tmp_path), "2026-02-20T00:00:00", 1, authority_data_dir=alias
        )

    assert sentinel.read_bytes() == b"unchanged"
    assert not (active / "assets").exists()
    assert not (active / "banksalad").exists()
    assert not (active / "metadata" / "import_history.csv").exists()


def test_nested_target_symlink_is_rejected_without_victim_changes(tmp_path: Path) -> None:
    data_dir = _data_dir(tmp_path)
    victim = tmp_path.resolve() / "victim"
    victim.mkdir()
    sentinel = victim / "sentinel.csv"
    sentinel.write_bytes(b"unchanged")
    snapshots = data_dir / "assets" / "snapshots"
    snapshots.parent.mkdir(parents=True)
    snapshots.symlink_to(victim, target_is_directory=True)
    cashflow = data_dir / "banksalad" / "cashflow"
    cashflow.parent.mkdir(parents=True)
    cashflow.symlink_to(victim, target_is_directory=True)
    archives = data_dir / "metadata" / "archives"
    archives.parent.mkdir(parents=True)
    archives.symlink_to(victim, target_is_directory=True)

    with pytest.raises(RepositoryPathError):
        csv_assets.write_asset_snapshot_month(_asset_df(), 2026, 2, authority_data_dir=data_dir)
    with pytest.raises(RepositoryPathError):
        overview_write.write_banksalad_cashflow_month(
            _cashflow_df(), 2026, 6, authority_data_dir=data_dir
        )
    with pytest.raises(RepositoryPathError):
        import_history.archive_source_file(
            _xlsx_source(tmp_path), "241027_1", authority_data_dir=data_dir
        )

    assert sentinel.read_bytes() == b"unchanged"
    assert set(victim.iterdir()) == {sentinel}


def test_replace_failure_preserves_original_asset_and_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = _data_dir(tmp_path)
    csv_assets.write_asset_snapshot_month(_asset_df(), 2026, 2, authority_data_dir=data_dir)
    partition = get_asset_snapshot_partition_path(data_dir / "assets" / "snapshots", 2026, 2)
    original = partition.read_bytes()
    import_history.record_import(
        _xlsx_source(tmp_path), "2026-02-20T00:00:00", 1, authority_data_dir=data_dir
    )
    history = data_dir / "metadata" / "import_history.csv"
    history_original = history.read_bytes()

    def fail_replace(*_args: object, **_kwargs: object) -> None:
        raise OSError("synthetic replace failure")

    monkeypatch.setattr(csv_assets, "_replace_with_owned_temp", fail_replace)
    monkeypatch.setattr(import_history, "_replace_with_owned_temp", fail_replace)

    with pytest.raises(OSError, match="synthetic replace failure"):
        csv_assets.write_asset_snapshot_month(_asset_df(), 2026, 2, authority_data_dir=data_dir)
    with pytest.raises(OSError, match="synthetic replace failure"):
        import_history.record_import(
            Path("other.xlsx"), "2026-02-20T00:00:00", 2, authority_data_dir=data_dir
        )

    assert partition.read_bytes() == original
    assert history.read_bytes() == history_original


def test_overview_replace_failure_preserves_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = _data_dir(tmp_path)
    overview_write.write_banksalad_overview_facts_month(
        _facts_df(), 2026, 6, authority_data_dir=data_dir
    )
    partition = data_dir / "banksalad" / "overview_facts" / "2026" / "06" / "facts.csv"
    original = partition.read_bytes()

    def fail_replace(*_args: object, **_kwargs: object) -> None:
        raise OSError("synthetic replace failure")

    monkeypatch.setattr(overview_helpers, "_replace_with_owned_temp", fail_replace)

    with pytest.raises(OSError, match="synthetic replace failure"):
        overview_write.write_banksalad_overview_facts_month(
            _facts_df(), 2026, 6, authority_data_dir=data_dir
        )
    assert partition.read_bytes() == original


def test_prefixed_fixed_temp_symlink_cannot_overwrite_victim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = _data_dir(tmp_path)
    csv_assets.write_asset_snapshot_month(_asset_df(), 2026, 2, authority_data_dir=data_dir)
    partition_dir = data_dir / "assets" / "snapshots" / "2026" / "02"
    partition = partition_dir / "snapshots.csv"
    original = partition.read_bytes()
    outside = tmp_path.resolve() / "outside.csv"
    outside.write_bytes(b"outside unchanged")
    staging = partition_dir / ".snapshots.csv.fixed.tmp"
    staging.symlink_to(outside)
    leftover = partition_dir / "snapshots.tmp"
    leftover.symlink_to(outside)
    monkeypatch.setattr(atomic_files.uuid, "uuid4", lambda: SimpleNamespace(hex="fixed"))

    with pytest.raises(OSError, match="could not be created safely"):
        csv_assets.write_asset_snapshot_month(_asset_df(), 2026, 2, authority_data_dir=data_dir)

    assert partition.read_bytes() == original
    assert outside.read_bytes() == b"outside unchanged"
    assert staging.is_symlink()
    assert leftover.is_symlink()


@pytest.mark.parametrize(
    "file_id",
    [
        "../escape",
        "..\\escape",
        "/tmp/abs",
        "nested/id",
        "..",
        ".",
        "",
        "item:stream",
        "241027_1:hidden",
        "CON",
        "con",
        "PRN",
        "AUX",
        "NUL",
        "COM1",
        "LPT9",
        "CON.txt",
        "foo.",
        "foo ",
    ],
)
def test_archive_file_id_traversal_is_rejected(tmp_path: Path, file_id: str) -> None:
    data_dir = _data_dir(tmp_path)
    source = _xlsx_source(tmp_path)
    outside = tmp_path.resolve() / "outside.xlsx"
    outside.write_bytes(b"outside unchanged")

    with pytest.raises(ValueError, match="single filename component"):
        import_history.archive_source_file(source, file_id, authority_data_dir=data_dir)

    assert outside.read_bytes() == b"outside unchanged"
    assert not (data_dir / "metadata" / "archives").exists()


@pytest.mark.parametrize("file_id", ["241027_1", "241027_100", "a3f2b1c4"])
def test_archive_generated_file_ids_remain_valid(tmp_path: Path, file_id: str) -> None:
    data_dir = _data_dir(tmp_path)
    source = _xlsx_source(tmp_path)

    archived = import_history.archive_source_file(source, file_id, authority_data_dir=data_dir)

    assert archived == data_dir / "metadata" / "archives" / f"{file_id}.xlsx"
    assert archived.read_bytes() == b"synthetic-xlsx"


def test_archive_preserves_source_bytes_mtime_and_mode(tmp_path: Path) -> None:
    _, source, archived, payload, stamp = _seed_archive(tmp_path)
    source_stat = source.stat()

    assert payload == b"synthetic-xlsx"
    assert archived.stat().st_mtime_ns == stamp
    assert archived.stat().st_atime_ns == stamp
    assert stat.S_IMODE(archived.stat().st_mode) == 0o640
    assert source.read_bytes() == b"synthetic-xlsx"
    assert source.stat().st_mtime_ns == source_stat.st_mtime_ns


def test_archive_replace_updates_bytes_and_mtime_atomically(tmp_path: Path) -> None:
    data_dir, source, archived, original, _old_stamp = _seed_archive(tmp_path)
    source.write_bytes(b"replacement-xlsx")
    source.chmod(0o640)
    _stamp(source, _REPLACEMENT_STAMP_NS)

    result = import_history.archive_source_file(source, "241027_1", authority_data_dir=data_dir)

    assert result == archived
    assert original != b"replacement-xlsx"
    assert archived.stat().st_mtime_ns == _REPLACEMENT_STAMP_NS
    assert archived.stat().st_atime_ns == _REPLACEMENT_STAMP_NS
    assert archived.read_bytes() == b"replacement-xlsx"


def test_archive_write_failure_preserves_prior_bytes_and_mtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir, source, archived, original, stamp = _seed_archive(tmp_path)
    _prepare_replacement_source(source)
    source_mtime = source.stat().st_mtime_ns
    monkeypatch.setattr(atomic_files.os, "write", _fail_os("synthetic write failure"))

    with pytest.raises(OSError, match="synthetic write failure"):
        import_history.archive_source_file(source, "241027_1", authority_data_dir=data_dir)

    _assert_archive_preserved(archived, original, stamp)
    _assert_source_preserved(source, b"replacement-xlsx", source_mtime)


def test_archive_metadata_failure_preserves_prior_bytes_and_mtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir, source, archived, original, stamp = _seed_archive(tmp_path)
    _prepare_replacement_source(source)
    source_mtime = source.stat().st_mtime_ns
    monkeypatch.setattr(atomic_files, "_apply_owned_times", _fail_os("synthetic metadata failure"))

    with pytest.raises(OSError, match="synthetic metadata failure"):
        import_history.archive_source_file(source, "241027_1", authority_data_dir=data_dir)

    _assert_archive_preserved(archived, original, stamp)
    _assert_source_preserved(source, b"replacement-xlsx", source_mtime)


def test_archive_replace_failure_preserves_prior_bytes_and_mtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir, source, archived, original, stamp = _seed_archive(tmp_path)
    _prepare_replacement_source(source)
    source_mtime = source.stat().st_mtime_ns
    monkeypatch.setattr(atomic_files.os, "replace", _fail_os("synthetic replace failure"))

    with pytest.raises(OSError, match="synthetic replace failure"):
        import_history.archive_source_file(source, "241027_1", authority_data_dir=data_dir)

    _assert_archive_preserved(archived, original, stamp)
    _assert_source_preserved(source, b"replacement-xlsx", source_mtime)


def test_archive_fixed_temp_symlink_cannot_overwrite_victim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir, source, archived, original, stamp = _seed_archive(tmp_path)
    outside = tmp_path.resolve() / "outside.xlsx"
    outside.write_bytes(b"outside unchanged")
    staging = archived.parent / f".{archived.name}.fixed.tmp"
    staging.symlink_to(outside)
    monkeypatch.setattr(atomic_files.uuid, "uuid4", lambda: SimpleNamespace(hex="fixed"))

    with pytest.raises(OSError, match="could not be created safely"):
        import_history.archive_source_file(source, "241027_1", authority_data_dir=data_dir)

    assert archived.read_bytes() == original
    assert archived.stat().st_mtime_ns == stamp
    assert outside.read_bytes() == b"outside unchanged"
    assert staging.is_symlink()


def _prepare_replacement_source(source: Path) -> None:
    source.write_bytes(b"replacement-xlsx")
    source.chmod(0o640)
    _stamp(source, _REPLACEMENT_STAMP_NS)


def _fail_os(message: str) -> Callable[..., Any]:
    def fail(*_args: object, **_kwargs: object) -> Any:
        raise OSError(message)

    return fail


def _assert_archive_preserved(archived: Path, original: bytes, stamp: int) -> None:
    assert archived.read_bytes() == original
    assert archived.stat().st_mtime_ns == stamp
    assert list(archived.parent.glob(f".{archived.name}.*.tmp")) == []


def _assert_source_preserved(source: Path, source_bytes: bytes, source_mtime: int) -> None:
    assert source.read_bytes() == source_bytes
    assert source.stat().st_mtime_ns == source_mtime
