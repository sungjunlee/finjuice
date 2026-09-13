"""JSON statement source adapter for the ingest contract (#448).

Defines the M5 source adapter fields (identity, schema/parser version,
original hash, as-of/collected time, coverage, currency, idempotency key)
and connects one additional local JSON path to the existing row-hash
dedup write path. Browser sessions and bank APIs are out of scope.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Final, Iterable, Literal, Mapping

import polars as pl

from ..constants import HASH_LENGTH_CHARS
from ..storage import csv_partition
from ._transaction_processor import _build_transaction_dataframe
from .pipeline_cluster import _record_ingest_import

logger = logging.getLogger(__name__)

JSON_STATEMENT_SOURCE_IDENTITY: Final = "json.statement.v1"
JSON_STATEMENT_SCHEMA_VERSION: Final = "1"
JSON_STATEMENT_PARSER_VERSION: Final = "1"

CoverageKind = Literal["full", "partial", "historical"]

_MAPPED_FIELDS: Final = ("date", "time", "type", "merchant", "amount", "currency", "account")
_COVERAGE_KINDS: Final = frozenset({"full", "partial", "historical"})
_CREDENTIAL_KEYS: Final = frozenset(
    {
        "access_token",
        "api_key",
        "apikey",
        "authorization",
        "client_secret",
        "cookie",
        "passwd",
        "password",
        "private_key",
        "refresh_token",
        "secret",
        "token",
    }
)
_USAGE_CONDITIONS: Final[dict[str, Any]] = {
    "input_kind": "local_json",
    "network": False,
    "browser_session": False,
    "originals_copied_into_repo": False,
    "private_originals_remain_at_source": True,
    "synthetic_ok_for_ci": True,
}


class AdapterCollectionError(ValueError):
    """Collection failed before any confirmed-state write."""


@dataclass(frozen=True)
class SourceAdapterContract:
    """Stable adapter envelope required before mapped rows are written."""

    source_identity: str
    schema_version: str
    parser_version: str
    source_hash: str
    as_of_date: str
    collected_at: str
    coverage_start: str | None
    coverage_end: str | None
    coverage_kind: CoverageKind
    currency: str
    idempotency_key: str


def compute_source_hash(payload: bytes) -> str:
    """Return the SHA-256 digest of immutable source bytes."""
    return hashlib.sha256(payload).hexdigest()


def build_idempotency_key(parts: Sequence[str]) -> str:
    """Build a retry-stable key for one adapter collection window."""
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return digest[:HASH_LENGTH_CHARS]


def resolve_json_statement_path(file_path: Path) -> Path:
    """Resolve a local JSON statement path and reject non-files."""
    resolved = file_path.expanduser().resolve()
    if resolved.suffix.lower() != ".json":
        raise AdapterCollectionError("JSON statement path must be a .json file")
    if not resolved.is_file():
        raise AdapterCollectionError("JSON statement file is not readable")
    return resolved


def parse_json_statement(file_path: Path) -> tuple[SourceAdapterContract, list[dict[str, Any]]]:
    """Parse one JSON statement into the adapter contract plus mapped records.

    Args:
        file_path: Local JSON file. Credentials are rejected; originals stay
            at this path and are not copied into the program repository.

    Returns:
        Tuple of (contract, mapped record dicts).

    Raises:
        AdapterCollectionError: If the file cannot be collected or validated.
    """
    resolved = resolve_json_statement_path(file_path)
    try:
        payload = resolved.read_bytes()
    except OSError as exc:
        raise AdapterCollectionError("JSON statement file is not readable") from exc

    source_hash = compute_source_hash(payload)
    collected_fallback = datetime.fromtimestamp(resolved.stat().st_mtime).isoformat()

    try:
        decoded: Any = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AdapterCollectionError("JSON statement is not valid JSON") from exc

    if not isinstance(decoded, dict):
        raise AdapterCollectionError("JSON statement root must be an object")
    if _contains_credential_keys(decoded):
        raise AdapterCollectionError("JSON statement must not include credentials")

    records = decoded.get("records")
    if not isinstance(records, list):
        raise AdapterCollectionError("JSON statement records must be a list")

    identity = str(decoded.get("source_identity") or JSON_STATEMENT_SOURCE_IDENTITY)
    if identity != JSON_STATEMENT_SOURCE_IDENTITY:
        raise AdapterCollectionError("JSON statement source_identity is not supported")

    schema_version = str(decoded.get("schema_version") or JSON_STATEMENT_SCHEMA_VERSION)
    parser_version = str(decoded.get("parser_version") or JSON_STATEMENT_PARSER_VERSION)
    currency = str(decoded.get("currency") or "KRW")
    mapped_records = [_normalize_record(record, currency) for record in records]
    coverage_start, coverage_end, coverage_kind = _resolve_coverage(decoded, mapped_records)
    as_of_date = str(decoded.get("as_of_date") or coverage_end or collected_fallback[:10])
    collected_at = str(decoded.get("collected_at") or collected_fallback)

    contract = SourceAdapterContract(
        source_identity=identity,
        schema_version=schema_version,
        parser_version=parser_version,
        source_hash=source_hash,
        as_of_date=as_of_date,
        collected_at=collected_at,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
        coverage_kind=coverage_kind,
        currency=currency,
        idempotency_key=build_idempotency_key(
            (
                identity,
                source_hash,
                coverage_start or "",
                coverage_end or "",
                schema_version,
                parser_version,
            )
        ),
    )
    return contract, mapped_records


def ingest_json_statement(file_path: Path, csv_base_dir: Path) -> dict[str, Any]:
    """Ingest one JSON statement through the existing CSV partition contract.

    Full, partial, historical, and retry payloads use the same mapped-row
    hash and ``append_transactions`` dedup path. Collection failures return a
    retryable result without writing confirmed partitions. Duplicate row hashes
    keep the existing row (including manual corrections) and append evidence.

    Args:
        file_path: Local JSON statement. Originals stay at the source path.
        csv_base_dir: Transaction CSV partition root.

    Returns:
        Summary with status, contract, transaction counts, evidence, and a
        privacy-safe verification record.
    """
    try:
        contract, records = parse_json_statement(file_path)
    except AdapterCollectionError as exc:
        logger.error("JSON statement collection failed (%s)", type(exc).__name__)
        verification = _write_verification(
            csv_base_dir,
            {
                "contract": None,
                "status": "failed",
                "source_filename": file_path.name,
                "error_kind": type(exc).__name__,
                "inserted": 0,
                "dedup_skips": 0,
                "validation_skips": 0,
                "evidence_appended": 0,
            },
        )
        return _failed_result(retryable=True, verification=verification)

    mapped_df = _records_to_mapped_frame(records)
    file_id = _record_ingest_import(
        file_path,
        csv_base_dir,
        archive=False,
        source_rows=len(records),
        file_mtime=contract.collected_at,
    )
    transactions_df, skipped_rows = _build_transaction_dataframe(file_path, mapped_df, file_id)
    write_result = csv_partition.append_transactions(
        csv_base_dir,
        transactions_df,
        deduplicate=True,
    )
    evidence_appended = _append_evidence(csv_base_dir, contract, transactions_df, file_id)
    inserted = int(write_result["rows_inserted"])
    dedup_skips = int(write_result["rows_skipped"])
    verification = _write_verification(
        csv_base_dir,
        {
            "contract": contract,
            "status": "ok",
            "source_filename": file_path.name,
            "error_kind": None,
            "inserted": inserted,
            "dedup_skips": dedup_skips,
            "validation_skips": len(skipped_rows),
            "evidence_appended": evidence_appended,
        },
    )
    logger.info(
        "JSON statement ingest complete: %s inserted, %s duplicates skipped",
        inserted,
        dedup_skips,
    )
    return {
        "status": "ok",
        "retryable": False,
        "contract": asdict(contract),
        "transactions": {
            "inserted": inserted,
            "dedup_skips": dedup_skips,
            "validation_skips": len(skipped_rows),
            "skipped_rows": skipped_rows,
        },
        "evidence_appended": evidence_appended,
        "verification": verification,
    }


def _contains_credential_keys(value: Any) -> bool:
    """Return True when a payload tree includes credential-like keys."""
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized = str(key).strip().lower().replace("-", "_")
            if normalized in _CREDENTIAL_KEYS:
                return True
            if _contains_credential_keys(nested):
                return True
        return False
    if isinstance(value, list):
        return any(_contains_credential_keys(item) for item in value)
    return False


def _normalize_record(record: Any, default_currency: str) -> dict[str, Any]:
    """Project one JSON record onto the mapped ingest columns."""
    if not isinstance(record, Mapping):
        return {field: None for field in _MAPPED_FIELDS}
    row = {field: record.get(field) for field in _MAPPED_FIELDS}
    if not row.get("currency"):
        row["currency"] = default_currency
    return row


def _resolve_coverage(
    payload: Mapping[str, Any],
    records: list[dict[str, Any]],
) -> tuple[str | None, str | None, CoverageKind]:
    """Read coverage from the envelope, falling back to record dates."""
    raw_coverage = payload.get("coverage")
    coverage: Mapping[str, Any] = raw_coverage if isinstance(raw_coverage, Mapping) else {}
    kind_raw = str(coverage.get("kind") or "full")
    if kind_raw not in _COVERAGE_KINDS:
        raise AdapterCollectionError("JSON statement coverage.kind is not supported")
    kind: CoverageKind
    if kind_raw == "partial":
        kind = "partial"
    elif kind_raw == "historical":
        kind = "historical"
    else:
        kind = "full"
    dates = [str(row["date"]) for row in records if row.get("date")]
    start = _optional_text(coverage.get("start")) or (min(dates) if dates else None)
    end = _optional_text(coverage.get("end")) or (max(dates) if dates else None)
    return start, end, kind


def _optional_text(value: Any) -> str | None:
    """Return a stripped string or None."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _records_to_mapped_frame(records: Iterable[dict[str, Any]]) -> pl.DataFrame:
    """Build a mapped-column DataFrame for ``_build_transaction_dataframe``."""
    rows = list(records)
    if not rows:
        return pl.DataFrame({field: [] for field in _MAPPED_FIELDS})
    return pl.DataFrame(rows)


def _metadata_dir(csv_base_dir: Path) -> Path:
    """Return the metadata directory beside transaction partitions."""
    path = csv_base_dir.parent / "metadata"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _append_unique_jsonl(
    path: Path,
    rows: list[dict[str, Any]],
    key_fields: tuple[str, ...],
) -> int:
    """Append JSONL rows, skipping keys already stored."""
    existing: set[tuple[Any, ...]] = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            existing.add(tuple(item.get(field) for field in key_fields))

    appended = 0
    if not rows:
        return 0
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            key = tuple(row.get(field) for field in key_fields)
            if key in existing:
                continue
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
            existing.add(key)
            appended += 1
    return appended


def _append_evidence(
    csv_base_dir: Path,
    contract: SourceAdapterContract,
    transactions_df: pl.DataFrame,
    file_id: str,
) -> int:
    """Preserve source observations without duplicating confirmed rows."""
    evidence_rows: list[dict[str, Any]] = []
    if transactions_df.height > 0:
        for row in transactions_df.iter_rows(named=True):
            evidence_rows.append(
                {
                    "row_hash": row["row_hash"],
                    "source_identity": contract.source_identity,
                    "source_hash": contract.source_hash,
                    "idempotency_key": contract.idempotency_key,
                    "collected_at": contract.collected_at,
                    "as_of_date": contract.as_of_date,
                    "coverage_kind": contract.coverage_kind,
                    "currency": contract.currency,
                    "file_id": file_id,
                    "source_row": row["source_row"],
                }
            )
    return _append_unique_jsonl(
        _metadata_dir(csv_base_dir) / "adapter_evidence.jsonl",
        evidence_rows,
        ("row_hash", "source_identity", "source_hash"),
    )


def _write_verification(csv_base_dir: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Record synthetic-safe usage conditions without originals or secrets."""
    contract = payload.get("contract")
    verification: dict[str, Any] = {
        "status": payload["status"],
        "source_filename": payload["source_filename"],
        "source_identity": None if contract is None else contract.source_identity,
        "schema_version": None if contract is None else contract.schema_version,
        "parser_version": None if contract is None else contract.parser_version,
        "source_hash": None if contract is None else contract.source_hash,
        "idempotency_key": None if contract is None else contract.idempotency_key,
        "error_kind": payload["error_kind"],
        "inserted": payload["inserted"],
        "dedup_skips": payload["dedup_skips"],
        "validation_skips": payload["validation_skips"],
        "evidence_appended": payload["evidence_appended"],
        "credentials_present": False,
        "original_retained_at_source": True,
        "published": False,
        "usage_conditions": dict(_USAGE_CONDITIONS),
    }
    path = _metadata_dir(csv_base_dir) / "adapter_verification.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(verification, ensure_ascii=False, separators=(",", ":")) + "\n")
    return verification


def _failed_result(*, retryable: bool, verification: dict[str, Any]) -> dict[str, Any]:
    """Return a retryable collection failure that did not write partitions."""
    return {
        "status": "failed",
        "retryable": retryable,
        "contract": None,
        "transactions": {
            "inserted": 0,
            "dedup_skips": 0,
            "validation_skips": 0,
            "skipped_rows": [],
        },
        "evidence_appended": 0,
        "verification": verification,
    }
