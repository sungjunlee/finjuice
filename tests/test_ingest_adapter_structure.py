"""Structure and M1 acceptance tests for the JSON statement ingest adapter.

The adapter contract lives in ``ingest.adapter``. Public pipeline entry
points stay in ``pipeline``; this module must not be folded back into
``pipeline.py``.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from finjuice.pipeline.ingest.adapter import (
    JSON_STATEMENT_PARSER_VERSION,
    JSON_STATEMENT_SCHEMA_VERSION,
    JSON_STATEMENT_SOURCE_IDENTITY,
    SourceAdapterContract,
    ingest_json_statement,
    parse_json_statement,
)
from finjuice.pipeline.ingest.deduplication import calculate_row_hash
from finjuice.pipeline.storage import csv_partition
from finjuice.pipeline.storage.authority import AuthorityEvidenceUnavailableError, AuthorityPaths
from finjuice.pipeline.storage.sqlite.errors import RepositoryPathError

INGEST_DIR = Path("src/finjuice/pipeline/ingest")
ADAPTER_MODULE = "finjuice.pipeline.ingest.adapter"
PIPELINE_MODULE = "finjuice.pipeline.ingest.pipeline"

CONTRACT_FIELDS = (
    "source_identity",
    "schema_version",
    "parser_version",
    "source_hash",
    "as_of_date",
    "collected_at",
    "coverage_start",
    "coverage_end",
    "coverage_kind",
    "currency",
    "idempotency_key",
)

SAMPLE_ROW = {
    "date": "2026-01-15",
    "time": "10:00",
    "type": "지출",
    "merchant": "스타벅스",
    "amount": -4500,
    "currency": "KRW",
    "account": "체크카드",
}


def test_adapter_is_the_unique_home_for_json_statement_ingest() -> None:
    """JSON statement ingest is defined once, in the adapter module."""
    adapter = importlib.import_module(ADAPTER_MODULE)
    pipeline = importlib.import_module(PIPELINE_MODULE)

    assert adapter.ingest_json_statement.__module__ == ADAPTER_MODULE
    assert adapter.parse_json_statement.__module__ == ADAPTER_MODULE
    assert not hasattr(pipeline, "ingest_json_statement")

    adapter_text = (INGEST_DIR / "adapter.py").read_text(encoding="utf-8")
    pipeline_text = (INGEST_DIR / "pipeline.py").read_text(encoding="utf-8")
    assert "def ingest_json_statement" in adapter_text
    assert "def parse_json_statement" in adapter_text
    assert "class SourceAdapterContract" in adapter_text
    assert "def ingest_json_statement" not in pipeline_text
    assert "class SourceAdapterContract" not in pipeline_text


def test_source_adapter_contract_exposes_required_identity_fields() -> None:
    """Adapter envelope carries identity, versions, hash, range, and idempotency."""
    for name in CONTRACT_FIELDS:
        assert name in SourceAdapterContract.__dataclass_fields__


def test_parse_json_statement_builds_contract_for_full_partial_and_historical(
    tmp_path: Path,
) -> None:
    """Full, partial, and historical JSON payloads share the same input contract."""
    full_path = _write_statement(
        tmp_path / "full.json",
        coverage={"start": "2026-01-01", "end": "2026-01-31", "kind": "full"},
        records=[SAMPLE_ROW, {**SAMPLE_ROW, "date": "2026-01-16", "merchant": "GS25"}],
    )
    partial_path = _write_statement(
        tmp_path / "partial.json",
        coverage={"start": "2026-01-15", "end": "2026-01-15", "kind": "partial"},
        records=[SAMPLE_ROW],
    )
    historical_path = _write_statement(
        tmp_path / "historical.json",
        as_of_date="2024-03-31",
        coverage={"start": "2024-03-01", "end": "2024-03-31", "kind": "historical"},
        records=[{**SAMPLE_ROW, "date": "2024-03-02"}],
    )

    for path, kind in (
        (full_path, "full"),
        (partial_path, "partial"),
        (historical_path, "historical"),
    ):
        contract, records = parse_json_statement(path)
        assert contract.source_identity == JSON_STATEMENT_SOURCE_IDENTITY
        assert contract.schema_version == JSON_STATEMENT_SCHEMA_VERSION
        assert contract.parser_version == JSON_STATEMENT_PARSER_VERSION
        assert contract.coverage_kind == kind
        assert contract.currency == "KRW"
        assert contract.source_hash
        assert contract.idempotency_key
        assert records
        for record in records:
            calculate_row_hash(record)


def test_json_statement_full_partial_historical_and_retry_use_existing_write_contract(
    tmp_path: Path,
) -> None:
    """Selected JSON path writes through existing hash/dedup partitions."""
    csv_base_dir = tmp_path / "data" / "transactions"
    source_dir = tmp_path / "imports"

    full_path = _write_statement(
        source_dir / "full.json",
        coverage={"start": "2026-01-01", "end": "2026-01-31", "kind": "full"},
        records=[SAMPLE_ROW, {**SAMPLE_ROW, "date": "2026-01-16", "merchant": "GS25"}],
    )
    first = ingest_json_statement(full_path, csv_base_dir)
    assert first["status"] == "ok"
    assert first["transactions"]["inserted"] == 2
    assert first["transactions"]["dedup_skips"] == 0

    retry = ingest_json_statement(full_path, csv_base_dir)
    assert retry["status"] == "ok"
    assert retry["transactions"]["inserted"] == 0
    assert retry["transactions"]["dedup_skips"] == 2
    assert retry["contract"]["idempotency_key"] == first["contract"]["idempotency_key"]

    partial_path = _write_statement(
        source_dir / "partial.json",
        coverage={"start": "2026-01-15", "end": "2026-01-15", "kind": "partial"},
        records=[SAMPLE_ROW],
    )
    partial = ingest_json_statement(partial_path, csv_base_dir)
    assert partial["status"] == "ok"
    assert partial["transactions"]["inserted"] == 0
    assert partial["transactions"]["dedup_skips"] == 1

    historical_path = _write_statement(
        source_dir / "historical.json",
        as_of_date="2024-03-31",
        coverage={"start": "2024-03-01", "end": "2024-03-31", "kind": "historical"},
        records=[{**SAMPLE_ROW, "date": "2024-03-02"}],
    )
    historical = ingest_json_statement(historical_path, csv_base_dir)
    assert historical["status"] == "ok"
    assert historical["transactions"]["inserted"] == 1

    all_rows = csv_partition.get_all_transactions(csv_base_dir)
    assert all_rows.height == 3
    march = csv_partition.read_month(csv_base_dir, 2024, 3)
    assert march.height == 1


def test_multi_source_observation_preserves_evidence_and_does_not_duplicate(
    tmp_path: Path,
) -> None:
    """A second source keeps evidence and leaves confirmed corrections in place."""
    csv_base_dir = tmp_path / "data" / "transactions"
    notes = "정정-보존"
    row_hash = _seed_confirmed_row(csv_base_dir, notes=notes)

    json_path = _write_statement(tmp_path / "imports" / "other-source.json", records=[SAMPLE_ROW])
    result = ingest_json_statement(json_path, csv_base_dir)

    assert result["status"] == "ok"
    assert result["transactions"]["inserted"] == 0
    assert result["transactions"]["dedup_skips"] == 1
    assert result["evidence_appended"] == 1

    rows = csv_partition.get_all_transactions(csv_base_dir)
    assert rows.height == 1
    confirmed = rows.row(0, named=True)
    assert confirmed["row_hash"] == row_hash
    assert confirmed["notes_manual"] == notes
    assert confirmed["file_id"] == "banksalad"

    evidence_path = tmp_path / "data" / "metadata" / "adapter_evidence.jsonl"
    evidence = [json.loads(line) for line in evidence_path.read_text(encoding="utf-8").splitlines()]
    assert len(evidence) == 1
    assert evidence[0]["row_hash"] == row_hash
    assert evidence[0]["source_identity"] == JSON_STATEMENT_SOURCE_IDENTITY
    assert "amount" not in evidence[0]
    assert "account" not in evidence[0]
    assert "merchant" not in evidence[0]


def test_collection_failure_does_not_damage_confirmed_state_and_is_retryable(
    tmp_path: Path,
) -> None:
    """Invalid collection leaves existing partitions untouched and can be retried."""
    csv_base_dir = tmp_path / "data" / "transactions"
    notes = "확정"
    _seed_confirmed_row(csv_base_dir, notes=notes)
    before = csv_partition.get_all_transactions(csv_base_dir).to_dicts()

    broken = tmp_path / "imports" / "broken.json"
    broken.parent.mkdir(parents=True)
    broken.write_text("{not-json", encoding="utf-8")

    failed = ingest_json_statement(broken, csv_base_dir)
    assert failed["status"] == "failed"
    assert failed["retryable"] is True
    assert failed["transactions"]["inserted"] == 0
    assert failed["contract"] is None

    after_fail = csv_partition.get_all_transactions(csv_base_dir).to_dicts()
    assert after_fail == before
    assert after_fail[0]["notes_manual"] == notes

    valid = _write_statement(tmp_path / "imports" / "retry.json", records=[SAMPLE_ROW])
    retried = ingest_json_statement(valid, csv_base_dir)
    assert retried["status"] == "ok"
    assert retried["transactions"]["inserted"] == 0
    assert retried["transactions"]["dedup_skips"] == 1
    after_retry = csv_partition.get_all_transactions(csv_base_dir)
    assert after_retry.height == 1
    assert after_retry.row(0, named=True)["notes_manual"] == notes


def test_credentials_and_originals_stay_private_and_verification_is_recorded(
    tmp_path: Path,
) -> None:
    """Secrets are rejected; originals stay at source; verification has no PII."""
    csv_base_dir = tmp_path / "data" / "transactions"
    secret_path = tmp_path / "imports" / "secret.json"
    payload = {
        "source_identity": JSON_STATEMENT_SOURCE_IDENTITY,
        "currency": "KRW",
        "api_key": "super-secret-token",
        "records": [SAMPLE_ROW],
    }
    secret_path.parent.mkdir(parents=True)
    secret_path.write_text(json.dumps(payload), encoding="utf-8")

    failed = ingest_json_statement(secret_path, csv_base_dir)
    assert failed["status"] == "failed"
    assert failed["retryable"] is True
    assert csv_partition.get_all_transactions(csv_base_dir).height == 0
    dumped = json.dumps(failed, ensure_ascii=False)
    assert "super-secret-token" not in dumped
    assert "api_key" not in dumped

    valid = _write_statement(tmp_path / "imports" / "safe.json", records=[SAMPLE_ROW])
    original_bytes = valid.read_bytes()
    ok = ingest_json_statement(valid, csv_base_dir)
    assert ok["status"] == "ok"
    assert valid.read_bytes() == original_bytes
    assert not (tmp_path / "data" / "metadata" / "archives").exists()

    verification = ok["verification"]
    assert verification["published"] is False
    assert verification["original_retained_at_source"] is True
    assert verification["credentials_present"] is False
    assert verification["usage_conditions"]["network"] is False
    assert verification["usage_conditions"]["synthetic_ok_for_ci"] is True
    assert verification["source_filename"] == "safe.json"
    assert "amount" not in verification
    assert "account" not in verification
    assert str(valid) not in json.dumps(verification)

    verification_path = tmp_path / "data" / "metadata" / "adapter_verification.jsonl"
    recorded = verification_path.read_text(encoding="utf-8")
    assert "super-secret-token" not in recorded
    assert "체크카드" not in recorded
    assert "스타벅스" not in recorded


def _write_statement(
    path: Path,
    *,
    records: list[dict[str, Any]],
    coverage: dict[str, str] | None = None,
    as_of_date: str | None = None,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    envelope: dict[str, Any] = {
        "source_identity": JSON_STATEMENT_SOURCE_IDENTITY,
        "schema_version": JSON_STATEMENT_SCHEMA_VERSION,
        "parser_version": JSON_STATEMENT_PARSER_VERSION,
        "collected_at": "2026-09-13T00:00:00+00:00",
        "currency": "KRW",
        "records": records,
    }
    if coverage is not None:
        envelope["coverage"] = coverage
    if as_of_date is not None:
        envelope["as_of_date"] = as_of_date
    elif records:
        envelope["as_of_date"] = str(records[-1]["date"])
    path.write_text(json.dumps(envelope, ensure_ascii=False), encoding="utf-8")
    return path


def _seed_confirmed_row(csv_base_dir: Path, *, notes: str) -> str:
    """Insert one confirmed partition row that later JSON observations must not replace."""
    row_hash = calculate_row_hash(SAMPLE_ROW)
    frame = pl.DataFrame(
        [
            {
                "row_hash": row_hash,
                "date": SAMPLE_ROW["date"],
                "time": SAMPLE_ROW["time"],
                "type_raw": SAMPLE_ROW["type"],
                "type_norm": "expense",
                "major_raw": "식비",
                "minor_raw": "카페",
                "merchant_raw": SAMPLE_ROW["merchant"],
                "memo_raw": "",
                "notes_manual": notes,
                "amount": float(SAMPLE_ROW["amount"]),
                "account": SAMPLE_ROW["account"],
                "currency": SAMPLE_ROW["currency"],
                "counterparty": None,
                "datetime": "2026-01-15T10:00:00",
                "category_rule": None,
                "category_final": "카페",
                "tags_rule": "[]",
                "tags_ai": "[]",
                "tags_manual": "[]",
                "tags_final": "[]",
                "confidence": None,
                "needs_review": None,
                "is_transfer": None,
                "transfer_group_id": None,
                "file_id": "banksalad",
                "source_row": 2,
            }
        ]
    )
    csv_partition.append_transactions(
        frame, deduplicate=True, authority_data_dir=csv_base_dir.parent
    )
    return row_hash


@pytest.mark.parametrize("malformed", [False, True])
def test_activated_authority_refuses_adapter_before_collection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, malformed: bool
) -> None:
    """Neither successful collection nor failure reporting may bypass activation."""
    csv_base_dir = tmp_path / "data" / "transactions"
    _seed_confirmed_row(csv_base_dir, notes="preserved")
    source = _write_statement(tmp_path / "imports" / "statement.json", records=[SAMPLE_ROW])
    if malformed:
        source.write_text("{", encoding="utf-8")
    activation = AuthorityPaths.for_data_dir(csv_base_dir.parent).activation
    activation.write_text("{}", encoding="utf-8")
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    adapter = importlib.import_module(ADAPTER_MODULE)

    def unexpected_parse(_path: Path) -> None:
        pytest.fail("An activated legacy adapter must reject before parsing its input.")

    monkeypatch.setattr(adapter, "parse_json_statement", unexpected_parse)
    with pytest.raises(AuthorityEvidenceUnavailableError):
        ingest_json_statement(source, csv_base_dir)

    after = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    assert after == before


@pytest.mark.parametrize("target_kind", ["other", "dotdot", "leaf_link", "parent_link"])
def test_adapter_refuses_redirected_or_nontransaction_roots(
    tmp_path: Path, target_kind: str
) -> None:
    """A target cannot redirect the CSV root away from its explicit authority."""
    data_dir = tmp_path / "data"
    transaction_root = data_dir / "transactions"
    transaction_root.mkdir(parents=True)
    source = _write_statement(tmp_path / "statement.json", records=[SAMPLE_ROW])
    if target_kind == "other":
        target = data_dir / "other"
    elif target_kind == "dotdot":
        target = data_dir / "other" / ".." / "transactions"
    elif target_kind == "leaf_link":
        alias = tmp_path / "alias"
        alias.mkdir()
        target = alias / "transactions"
        target.symlink_to(transaction_root, target_is_directory=True)
    else:
        alias = tmp_path / "alias"
        alias.symlink_to(data_dir, target_is_directory=True)
        target = alias / "transactions"
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}

    with pytest.raises((ValueError, RepositoryPathError)):
        ingest_json_statement(source, target)

    assert {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()} == before
    assert not (data_dir / ".finjuice").exists()
    assert not (data_dir / "metadata").exists()
