"""Synthetic tests for the bounded exact XLSX importer domain slice."""

from __future__ import annotations

import io
import json
import sqlite3
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from finjuice.pipeline.storage.authority import (
    ActivationEvidence,
    AuthorityDispatch,
    AuthorityPaths,
    require_repository_authority,
)
from finjuice.pipeline.storage.mutation_facade import (
    BulkMutationPreview,
    ExactImportIntent,
    MutationIdentity,
    StorageMutationFacade,
)
from finjuice.pipeline.storage.sqlite import (
    MutationAbortedError,
    MutationConflictError,
    RepositoryBuilder,
    new_entity_id,
)
from finjuice.pipeline.storage.sqlite import schema as schema_module
from finjuice.pipeline.storage.sqlite.exact_import import ExactImportCommand, capture_exact_xlsx
from finjuice.pipeline.storage.sqlite.mutations import MutationReceipt

_NOW = "2026-09-10T00:00:00Z"
MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
DOC_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
TX_SHARED = [
    "날짜",
    "시간",
    "타입",
    "내용",
    "금액",
    "결제수단",
    "화폐",
    "비고",
    "지출",
    "수입",
    "이체",
    "카드A",
]
ASSET_SHARED = ["기준일", "계좌ID", "계좌명", "종목ID", "종목명", "수량", "평가금액", "화폐"]


@dataclass
class _Repo:
    paths: AuthorityPaths
    evidence: ActivationEvidence
    generation: str
    database: Path
    facade: StorageMutationFacade
    data_dir: Path

    def identity(self, key: str, revision: int) -> MutationIdentity:
        return MutationIdentity(key, self.generation, revision)

    def revision(self) -> int:
        return int(_query(self.database, "SELECT dataset_revision FROM repository_meta")[0][0])


def _evidence() -> ActivationEvidence:
    return ActivationEvidence("0.7.3", "a" * 64, "b" * 64, "c" * 64)


def _write_activation(paths: AuthorityPaths, generation: str) -> None:
    paths.control_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    payload = {
        "activation_schema_version": 1,
        "release_version": "0.7.3",
        "release_artifact_sha256": "a" * 64,
        "dataset_generation": generation,
        "sqlite_schema_version": schema_module.SQLITE_SCHEMA_VERSION,
        "dataset_revision": 0,
        "migration_manifest_sha256": "b" * 64,
        "pre_cutover_backup_manifest_sha256": "c" * 64,
        "activated_at": _NOW,
    }
    paths.activation.write_text(json.dumps(payload), encoding="utf-8")


@pytest.fixture
def repo(tmp_path: Path) -> _Repo:
    paths = AuthorityPaths(tmp_path / "control", tmp_path / "generations")
    generation = new_entity_id()
    with RepositoryBuilder(paths.generation(generation), generation) as builder:
        builder.finalize()
    _write_activation(paths, generation)
    evidence = _evidence()
    authority = require_repository_authority(paths, evidence)

    class _Facade(StorageMutationFacade):
        def dispatch(self) -> AuthorityDispatch:
            return AuthorityDispatch(paths=paths, authority=authority, evidence=evidence)

    data_dir = tmp_path / "data"
    database = paths.generation(generation).database
    return _Repo(paths, evidence, generation, database, _Facade(data_dir), data_dir)


def _query(database: Path, sql: str, parameters: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    connection = sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)
    try:
        return connection.execute(sql, parameters).fetchall()
    finally:
        connection.close()


def _count(database: Path, table: str) -> int:
    return int(_query(database, f"SELECT count(*) FROM {table}")[0][0])  # nosec B608


def _zip_bytes(members: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, text in members.items():
            archive.writestr(name, text)
    return buffer.getvalue()


def _sst(texts: list[str]) -> str:
    items = "".join(f"<si><t>{text}</t></si>" for text in texts)
    return f'<?xml version="1.0" encoding="UTF-8"?><sst xmlns="{MAIN_NS}">{items}</sst>'


def _sheet_xml(rows: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<worksheet xmlns="{MAIN_NS}"><sheetData>{rows}</sheetData></worksheet>'
    )


def _rels(entries: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<Relationships xmlns="{PKG_REL_NS}">{entries}</Relationships>'
    )


def _s(ref: str, index: int) -> str:
    return f'<c r="{ref}" t="s"><v>{index}</v></c>'


def _n(ref: str, lexical: str) -> str:
    return f'<c r="{ref}"><v>{lexical}</v></c>'


def _inline(ref: str, text: str) -> str:
    return f'<c r="{ref}" t="inlineStr"><is><t>{text}</t></is></c>'


def _row(number: int, *cells: str) -> str:
    return f'<row r="{number}">{"".join(cells)}</row>'


def _package(sheets: dict[str, str], *, shared: list[str] | None = None) -> bytes:
    names = list(sheets)
    sheet_tags = "".join(
        f'<sheet name="{name}" sheetId="{index}" r:id="rId{index}"/>'
        for index, name in enumerate(names, start=1)
    )
    rels = "".join(
        f'<Relationship Id="rId{index}" Type="{DOC_REL_NS}/worksheet" '
        f'Target="worksheets/sheet{index}.xml"/>'
        for index, _name in enumerate(names, start=1)
    )
    shared_rel = ""
    members: dict[str, str] = {
        "_rels/.rels": _rels(
            f'<Relationship Id="rId1" Type="{DOC_REL_NS}/officeDocument" Target="xl/workbook.xml"/>'
        ),
        "xl/workbook.xml": (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f'<workbook xmlns="{MAIN_NS}" xmlns:r="{DOC_REL_NS}">'
            f"<sheets>{sheet_tags}</sheets></workbook>"
        ),
    }
    if shared is not None:
        shared_rel = (
            f'<Relationship Id="rIdS" Type="{DOC_REL_NS}/sharedStrings" '
            'Target="sharedStrings.xml"/>'
        )
        members["xl/sharedStrings.xml"] = _sst(shared)
    members["xl/_rels/workbook.xml.rels"] = _rels(rels + shared_rel)
    for index, rows in enumerate(sheets.values(), start=1):
        members[f"xl/worksheets/sheet{index}.xml"] = _sheet_xml(rows)
    return _zip_bytes(members)


def _tx_header() -> str:
    return _row(1, *[_s(f"{col}1", idx) for idx, col in enumerate("ABCDEFGH")])


def _tx_row(
    number: int,
    *,
    amount: str = "-1000.00",
    income: bool = False,
    time_text: str | None = "13:04:05",
    extra: str | None = None,
) -> str:
    type_idx = 9 if income else 8
    cells = [
        _inline(f"A{number}", "2024-03-15"),
        _inline(f"B{number}", time_text) if time_text is not None else "",
        _s(f"C{number}", type_idx),
        _inline(f"D{number}", "카페"),
        _n(f"E{number}", amount),
        _s(f"F{number}", 11),
        _inline(f"G{number}", "KRW"),
    ]
    cells = [cell for cell in cells if cell]
    if extra:
        cells.append(extra)
    return _row(number, *cells)


def _tx_book(*rows: str, extra_sheets: dict[str, str] | None = None) -> bytes:
    sheets = {"가계부": _tx_header() + "".join(rows)}
    if extra_sheets:
        sheets.update(extra_sheets)
    return _package(sheets, shared=TX_SHARED)


def _asset_book() -> bytes:
    header = _row(1, *[_s(f"{col}1", idx) for idx, col in enumerate("ABCDEFGH")])
    body = _row(
        2,
        _inline("A2", "2026-06-15"),
        _inline("B2", "acct-1"),
        _inline("C2", "계좌A"),
        _inline("D2", "inst-1"),
        _inline("E2", "종목A"),
        _n("F2", "1.5"),
        _n("G2", "150.25"),
        _inline("H2", "USD"),
    )
    return _package({"holdings": header + body}, shared=ASSET_SHARED)


def _overview_book() -> bytes:
    rows = "".join(
        [
            _row(1, _inline("A1", "기준일"), _inline("B1", "2026-06-15")),
            _row(3, _inline("A3", "1.고객정보")),
            _row(4, _inline("A4", "이름"), _inline("B4", "Synthetic User")),
            _row(13, _inline("A13", "3.재무현황")),
            _row(14, _inline("B14", "자산"), _inline("E14", "부채")),
            _row(
                15,
                _inline("B15", "분류"),
                _inline("C15", "항목"),
                _inline("D15", "금액"),
                _inline("E15", "분류"),
                _inline("F15", "항목"),
                _inline("G15", "금액"),
            ),
            _row(
                16,
                _inline("B16", "예금"),
                _inline("C16", "Synthetic Deposit"),
                _n("D16", "1250000"),
            ),
        ]
    )
    return _package({"뱅샐현황": rows})


def _capture(data: bytes, *, filename: str = "synthetic.xlsx"):
    return capture_exact_xlsx(data, filename=filename)


def _import(
    repo: _Repo,
    data: bytes,
    *,
    key: str,
    revision: int,
    preview: bool = False,
):
    command = ExactImportCommand(_capture(data), preview=preview)
    return repo.facade.import_exact_xlsx(command, identity=repo.identity(key, revision))


def _reject_float(value: Any) -> None:
    if isinstance(value, float):
        raise AssertionError("float leaked into exact import result")
    if isinstance(value, dict):
        for item in value.values():
            _reject_float(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_float(item)


def test_capture_binds_path_bytes_to_the_same_digest(tmp_path: Path) -> None:
    data = _tx_book(_tx_row(2))
    path = tmp_path / "one.xlsx"
    path.write_bytes(data)
    captured = capture_exact_xlsx(path)
    again = capture_exact_xlsx(data, filename="one.xlsx")
    assert captured.digest_hex == again.digest_hex == captured.evidence.source_sha256
    assert captured.source_bytes == data
    assert captured.filename == "one.xlsx"


def test_first_import_persists_supported_transaction_and_source_cells(repo: _Repo) -> None:
    receipt = _import(repo, _tx_book(_tx_row(2)), key="imp-1", revision=0)
    assert isinstance(receipt, MutationReceipt)
    assert receipt.state_changed is True
    result = receipt.result
    _reject_float(result)
    assert result["noop"] is False
    assert result["counts"]["transactions"]["inserted"] == 1
    assert result["counts"]["mapper_status"]["transactions"] == "mapped"
    assert _count(repo.database, "transactions") == 1
    assert _count(repo.database, "accounts") == 1
    assert _count(repo.database, "transaction_source_links") == 1
    payload = _query(repo.database, "SELECT payload_json FROM legacy_payloads")[0][0]
    assert "cells" in payload
    row = _query(
        repo.database,
        "SELECT date_raw, time_raw, datetime_raw, timezone_state, account_text FROM transactions",
    )[0]
    assert row[0] == "2024-03-15"
    assert row[1] == "13:04:05"
    assert row[4] == "카드A"
    ownership = _query(repo.database, "SELECT ownership_state, owner_party_id FROM accounts")[0]
    assert ownership == ("unknown", None)


def test_byte_identical_import_is_noop_and_keeps_revision(repo: _Repo) -> None:
    data = _tx_book(_tx_row(2))
    first = _import(repo, data, key="imp-a", revision=0)
    assert isinstance(first, MutationReceipt)
    revision = repo.revision()
    second = _import(repo, data, key="imp-b", revision=revision)
    assert isinstance(second, MutationReceipt)
    assert second.state_changed is False
    assert second.result["noop"] is True
    assert second.result["occurrence_id"] == first.result["occurrence_id"]
    assert second.result["counts"]["transactions"]["inserted"] == 0
    assert second.result["counts"]["transactions"]["reused"] == 1
    assert _count(repo.database, "transactions") == 1
    assert repo.revision() == revision


def test_explicit_idempotency_replay_returns_original_receipt(repo: _Repo) -> None:
    data = _tx_book(_tx_row(2))
    first = _import(repo, data, key="same-key", revision=0)
    replay = _import(repo, data, key="same-key", revision=0)
    assert isinstance(first, MutationReceipt)
    assert isinstance(replay, MutationReceipt)
    assert replay.replayed is True
    assert replay.changeset_id == first.changeset_id
    assert replay.result == first.result
    assert _count(repo.database, "transactions") == 1


def test_dry_run_matches_insert_counts_without_publication(repo: _Repo) -> None:
    data = _tx_book(_tx_row(2))
    preview = _import(repo, data, key="dry", revision=0, preview=True)
    assert isinstance(preview, BulkMutationPreview)
    _reject_float(preview.result)
    assert preview.result["completed"] is False
    assert preview.result["occurrence_id"] is None
    assert preview.result["counts"]["transactions"]["inserted"] == 1
    assert _count(repo.database, "transactions") == 0
    assert _count(repo.database, "source_artifacts") == 0
    assert repo.revision() == 0
    objects = repo.paths.generation(repo.generation).sha256_objects
    assert not objects.exists() or not any(objects.rglob("*"))
    receipt = _import(repo, data, key="real", revision=0)
    assert isinstance(receipt, MutationReceipt)
    assert receipt.result["counts"]["transactions"]["inserted"] == 1


def test_changed_intent_requires_explicit_correction(repo: _Repo) -> None:
    data = _tx_book(_tx_row(2))
    first = _import(repo, data, key="base", revision=0)
    assert isinstance(first, MutationReceipt)
    with pytest.raises(MutationConflictError, match="explicit correction"):
        repo.facade.import_exact_xlsx(
            ExactImportCommand(
                _capture(data),
                intent=ExactImportIntent(snapshot_date="2026-01-01"),
            ),
            identity=repo.identity("changed", repo.revision()),
        )


def test_literal_duplicate_rows_are_preserved(repo: _Repo) -> None:
    data = _tx_book(_tx_row(2), _tx_row(3))
    receipt = _import(repo, data, key="dups", revision=0)
    assert isinstance(receipt, MutationReceipt)
    assert receipt.result["counts"]["transactions"]["inserted"] == 2
    assert _count(repo.database, "transactions") == 2
    assert _count(repo.database, "accounts") == 2


def test_unknown_account_display_names_are_not_merged(repo: _Repo) -> None:
    data = _tx_book(_tx_row(2), _tx_row(3, amount="-2000.00"))
    _import(repo, data, key="names", revision=0)
    names = _query(repo.database, "SELECT display_name FROM accounts ORDER BY entity_id")
    assert [row[0] for row in names] == ["카드A", "카드A"]
    assert len({row[0] for row in _query(repo.database, "SELECT entity_id FROM accounts")}) == 2


def test_unknown_sheet_is_counted_and_preserved(repo: _Repo) -> None:
    extra = {"notes": _row(1, _inline("A1", "keep-me"))}
    data = _tx_book(_tx_row(2), extra_sheets=extra)
    receipt = _import(repo, data, key="unknown", revision=0)
    assert isinstance(receipt, MutationReceipt)
    assert receipt.result["counts"]["unknown_sheets"] == 1
    kinds = {row[0] for row in _query(repo.database, "SELECT issue_kind FROM preservation_issues")}
    assert "UNKNOWN_SHEET" in kinds


def test_negative_income_keeps_source_and_calculated_amounts(repo: _Repo) -> None:
    data = _tx_book(_tx_row(2, amount="-500.00", income=True))
    _import(repo, data, key="income", revision=0)
    values = _query(
        repo.database,
        "SELECT origin_kind, coefficient, lexical, scale FROM exact_values ORDER BY origin_kind",
    )
    calculated = [row for row in values if row[0] == "calculated"]
    source = [row for row in values if row[0] == "source"]
    assert source[0][1].startswith("-")
    assert source[0][2] == "-500.00"
    assert (calculated[0][1], calculated[0][3]) == (source[0][1].removeprefix("-"), source[0][3])
    assert calculated[0][2] is None
    linked = _query(
        repo.database,
        "SELECT amount.origin_kind FROM transactions AS txn "
        "JOIN exact_values AS amount ON amount.value_id = txn.amount_value_id",
    )
    assert linked[0][0] == "calculated"


def test_missing_time_is_empty_text_not_midnight(repo: _Repo) -> None:
    data = _tx_book(_tx_row(2, time_text=None))
    _import(repo, data, key="notime", revision=0)
    row = _query(repo.database, "SELECT time_raw, datetime_raw FROM transactions")[0]
    assert row[0] == ""
    assert row[1] == ""
    effective = _query(repo.database, "SELECT effective_at, observed_at FROM observations")[0]
    assert effective[0] == "2024-03-15"
    assert effective[1] is None
    assert "T00:00" not in (effective[0] or "")


def test_assets_and_overview_facts_are_source_linked(repo: _Repo) -> None:
    asset_receipt = _import(repo, _asset_book(), key="assets", revision=0)
    assert isinstance(asset_receipt, MutationReceipt)
    assert asset_receipt.result["counts"]["assets"]["inserted"] == 1
    assert _count(repo.database, "asset_snapshots") == 1
    overview = _import(repo, _overview_book(), key="overview", revision=repo.revision())
    assert isinstance(overview, MutationReceipt)
    assert overview.result["counts"]["overview"]["inserted"] >= 1
    assert _count(repo.database, "overview_facts") >= 1
    assert _count(repo.database, "overview_balances") == 1


def test_cross_artifact_unproven_overlap_is_quarantined(repo: _Repo) -> None:
    first = _tx_book(_tx_row(2))
    second = _tx_book(_tx_row(2), extra_sheets={"notes": _row(1, _inline("A1", "other"))})
    _import(repo, first, key="orig", revision=0)
    receipt = _import(repo, second, key="later", revision=repo.revision())
    assert isinstance(receipt, MutationReceipt)
    assert receipt.result["counts"]["transactions"]["inserted"] == 0
    assert receipt.result["counts"]["transactions"]["quarantined"] == 1
    assert _count(repo.database, "transactions") == 1
    kinds = {row[0] for row in _query(repo.database, "SELECT issue_kind FROM preservation_issues")}
    assert "UNRESOLVED_IDENTITY" in kinds
    payload = _query(repo.database, "SELECT payload_json FROM legacy_payloads")
    assert any('"action":"quarantine"' in row[0] for row in payload)


def test_failure_after_publish_rolls_back_and_reports_retained_artifact(
    repo: _Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_args: object, **_kwargs: object) -> list[str]:
        raise RuntimeError("synthetic persist failure")

    monkeypatch.setattr(
        "finjuice.pipeline.storage.sqlite.exact_import.persist.persist_transactions",
        boom,
    )
    data = _tx_book(_tx_row(2))
    captured = _capture(data)
    with pytest.raises(MutationAbortedError) as aborted:
        repo.facade.import_exact_xlsx(
            ExactImportCommand(captured),
            identity=repo.identity("fail", 0),
        )
    assert aborted.value.retained_artifacts == (captured.artifact_id,)
    assert _count(repo.database, "transactions") == 0
    assert _count(repo.database, "source_occurrences") == 0
    assert repo.revision() == 0
    relative = f"objects/sha256/{captured.digest_hex[:2]}/{captured.digest_hex}"
    assert (repo.paths.generation(repo.generation).root / relative).is_file()


def test_payload_excludes_transient_collection_clock(repo: _Repo) -> None:
    from finjuice.pipeline.storage.sqlite.exact_import.models import ExactImportCommand

    command = ExactImportCommand(_capture(_tx_book(_tx_row(2))))
    payload = json.dumps(command.payload())
    assert "imported_at" not in payload
    assert "collected_at" in payload
    assert command.payload()["intent"]["collected_at"] is None
