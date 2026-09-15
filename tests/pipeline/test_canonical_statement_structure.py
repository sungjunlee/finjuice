"""Structure tests for the canonical statement parse/apply split (issue #525)."""

from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path
from typing import Any

import pytest

from finjuice.pipeline.storage.sqlite.errors import MutationValidationError

STATEMENTS_DIR = Path("src/finjuice/pipeline/statements")
CANONICAL_MODULE = "finjuice.pipeline.statements.canonical"
PARSE_MODULE = "finjuice.pipeline.statements.canonical_parse"

PARSE_PUBLIC_NAMES = ("parse_document", "plan_rows", "STATEMENT_SCHEMA_VERSION", "COVERAGE_KINDS")
PARSE_HELPER_DEFS = (
    "parse_document",
    "plan_rows",
    "_validate_envelope",
    "_envelope_payload",
    "_row",
    "_decision",
    "_amount",
)
APPLY_DEFS = (
    "import_statement",
    "_apply_row",
    "_publish_original",
    "statement_evidence",
    "resolve_account_binding_for",
)
ORIGINAL_HASH = "sha256:" + hashlib.sha256(b"synthetic original").hexdigest()


def _envelope(records: list[dict[str, Any]], **overrides: Any) -> dict[str, Any]:
    envelope = {
        "source_identity": "bank.synthetic.statement.v1",
        "schema_version": "finjuice.statement.v1",
        "parser_version": "synthetic-adapter.v1",
        "original_hash": ORIGINAL_HASH,
        "as_of": "2026-09-02T00:00:00Z",
        "collected_at": "2026-09-02T00:05:00Z",
        "coverage": "full",
        "currency": "KRW",
        "idempotency_key": "producer-batch-1",
        "records": records,
    }
    envelope.update(overrides)
    return envelope


def _record(external_id: str, **overrides: Any) -> dict[str, Any]:
    record = {
        "external_transaction_id": external_id,
        "source_account_key": "synthetic-checking-01",
        "amount": "-1200.50",
        "occurred_on": "2026-09-01",
        "occurred_at": "2026-09-01T12:30:00+09:00",
        "type": "expense",
        "description": "합성 가맹점",
    }
    record.update(overrides)
    return record


def test_canonical_reexports_parse_identity() -> None:
    """Public parse names stay identity-equal when imported from canonical."""
    canonical = importlib.import_module(CANONICAL_MODULE)
    parse = importlib.import_module(PARSE_MODULE)

    for name in PARSE_PUBLIC_NAMES:
        assert getattr(canonical, name) is getattr(parse, name)


def test_parse_helpers_live_in_canonical_parse() -> None:
    """Parse and row builders are defined once, in canonical_parse."""
    canonical = importlib.import_module(CANONICAL_MODULE)
    parse = importlib.import_module(PARSE_MODULE)

    for name in PARSE_PUBLIC_NAMES:
        if name in {"parse_document", "plan_rows"}:
            assert getattr(parse, name).__module__ == PARSE_MODULE
            assert getattr(canonical, name).__module__ == PARSE_MODULE

    for name in APPLY_DEFS:
        assert getattr(canonical, name).__module__ == CANONICAL_MODULE
    assert canonical.StatementImport.__module__ == CANONICAL_MODULE


def test_parse_and_apply_live_in_separate_modules() -> None:
    """Single-file parse helpers must not stay on the apply module."""
    canonical_text = (STATEMENTS_DIR / "canonical.py").read_text(encoding="utf-8")
    parse_text = (STATEMENTS_DIR / "canonical_parse.py").read_text(encoding="utf-8")

    for name in PARSE_HELPER_DEFS:
        assert f"def {name}" in parse_text
        assert f"def {name}" not in canonical_text

    assert "class _Row" in parse_text
    assert "class _Row" not in canonical_text
    assert "class StatementImport" in canonical_text
    assert "class StatementImport" not in parse_text

    for name in APPLY_DEFS:
        assert f"def {name}" in canonical_text
        assert f"def {name}" not in parse_text


def test_parse_document_accepts_synthetic_envelope() -> None:
    """A synthetic full envelope canonicalizes without touching sqlite apply."""
    parse = importlib.import_module(PARSE_MODULE)
    content = json.dumps(_envelope([_record("txn-1")]), ensure_ascii=False).encode("utf-8")

    envelope = parse.parse_document(content)
    rows = parse.plan_rows(envelope)

    assert envelope["source_identity"] == "bank.synthetic.statement.v1"
    assert envelope["coverage"] == "full"
    assert envelope["currency"] == "KRW"
    assert len(rows) == 1
    assert rows[0].external_id == "txn-1"
    assert rows[0].action == "pending"
    assert rows[0].amount.lexical == "-1200.50"


def test_plan_rows_rejects_duplicate_external_ids() -> None:
    parse = importlib.import_module(PARSE_MODULE)
    content = json.dumps(
        _envelope([_record("txn-1"), _record("txn-1", amount="-1.00")]),
        ensure_ascii=False,
    ).encode("utf-8")
    envelope = parse.parse_document(content)

    with pytest.raises(MutationValidationError, match="repeats one external transaction id"):
        parse.plan_rows(envelope)


def test_parse_document_rejects_credential_like_fields() -> None:
    parse = importlib.import_module(PARSE_MODULE)
    content = json.dumps(
        _envelope([_record("txn-1", api_key="not-a-secret-in-tests")]),
        ensure_ascii=False,
    ).encode("utf-8")

    with pytest.raises(MutationValidationError, match="credential-like field"):
        parse.parse_document(content)
