"""Synthetic acceptance for lossless frozen legacy adapters."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path

import pytest

from finjuice.pipeline.migration.adapters import FileContext, analyze_file, preserve_file
from finjuice.pipeline.storage.sqlite.paths import GenerationPaths
from finjuice.pipeline.storage.sqlite.repository import RepositoryBuilder, RepositoryReader

GENERATION = "00000000-0000-4000-8000-000000000001"


def transaction_bytes(amounts: tuple[str, ...] = ("10.10", "0.0037")) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(
        [
            "row_hash",
            "date",
            "time",
            "datetime",
            "type_norm",
            "account",
            "amount",
            "currency",
            "category_final",
            "tags_rule",
            "tags_ai",
            "tags_manual",
            "tags_final",
            "notes_manual",
            "needs_review",
        ]
    )
    manual = [
        "second",
        "__finjuice_category_override__:old",
        "same",
        "same",
        "__finjuice_category_override__:new",
        "__finjuice_category_override__:",
    ]
    for amount in amounts:
        writer.writerow(
            [
                "duplicate",
                "2026-01-01",
                "12:30",
                "2026-01-01T12:30",
                "expense",
                "synthetic",
                amount,
                "USD",
                "persisted",
                "[]",
                "[]",
                json.dumps(manual),
                '["persisted-tag"]',
                "keep note",
                "1",
            ]
        )
    return output.getvalue().encode()


def build(
    tmp_path: Path,
    data: bytes,
    logical: str = "transactions/2026/01/data.csv",
    generation_dir: str = "candidate",
) -> tuple[GenerationPaths, dict]:
    source = tmp_path / f"{generation_dir}-source"
    source.write_bytes(data)
    context = FileContext("a" * 64, "synthetic", logical, "4")
    planned = analyze_file(source, context)
    paths = GenerationPaths(tmp_path / generation_dir)
    with RepositoryBuilder(paths, GENERATION) as builder:
        actual = preserve_file(builder, source, context)
        builder.finalize()
    assert actual == planned
    assert source.read_bytes() == data
    return paths, actual.to_dict()


def test_duplicate_sentinel_persisted_category_and_exact_values(tmp_path: Path) -> None:
    data = transaction_bytes(("10.10", "0.0037", "12345678901234567890.01"))
    paths, analysis = build(tmp_path, data)
    with RepositoryReader(paths.database) as reader:
        transactions = reader.rows("transactions")
        assert len({row["entity_id"] for row in transactions}) == 3
        assert all(row["category_final"] == "persisted" for row in transactions)
        assert all(row["category_manual"] == "new" for row in transactions)
        assert all(
            json.loads(row["tags_manual_json"]) == ["second", "same", "same"]
            for row in transactions
        )
        assert all(row["notes_manual"] == "keep note" for row in transactions)
        assert all(row["ownership_state"] == "unknown" for row in reader.rows("accounts"))
        assert {
            (row["coefficient"], row["scale"], row["lexical"])
            for row in reader.rows("exact_values")
        } == {
            ("1010", 2, "10.10"),
            ("37", 4, "0.0037"),
            ("1234567890123456789001", 2, "12345678901234567890.01"),
        }
        assert all(row["currency_code"] == "USD" for row in reader.rows("money_values"))
        mappings = reader.rows("legacy_identifiers")
        assert len([row for row in mappings if row["identifier_kind"] == "row_hash"]) == 3
    assert analysis["record_counts"]["transaction"] == 3


def test_csv_null_blank_missing_unknown_and_duplicate_columns(tmp_path: Path) -> None:
    paths, analysis = build(tmp_path, b'a,b,c,d\r\n,"",NULL\r\n', "overlay.csv")
    with RepositoryReader(paths.database) as reader:
        payloads = [json.loads(row["payload_json"]) for row in reader.rows("legacy_payloads")]
        payload = next(row for row in payloads if "cells" in row)
        assert [cell["state"] for cell in payload["cells"]] == ["null", "blank", "value", "missing"]
        assert payload["raw_record"] == ',"",NULL\r\n'
        assert reader.rows("migration_dispositions")
    assert analysis["issue_counts"]["unsupported_csv_role"] == 1
    _, duplicate = build(tmp_path, b"a,a\n1,2\n", "overlay.csv", "duplicate")
    assert duplicate["issue_counts"]["ambiguous_csv_structure"] == 1


def test_repeat_build_and_shared_artifact_distinct_occurrences(tmp_path: Path) -> None:
    data = transaction_bytes()
    first, _ = build(tmp_path, data, generation_dir="first")
    second, _ = build(tmp_path, data, generation_dir="second")
    with RepositoryReader(first.database) as a, RepositoryReader(second.database) as b:
        for table in (
            "transactions",
            "migration_identities",
            "legacy_identifiers",
            "record_provenance",
            "preservation_issues",
            "legacy_payloads",
        ):
            assert a.rows(table) == b.rows(table)
    source = tmp_path / "original"
    source.write_bytes(data)
    paths = GenerationPaths(tmp_path / "both")
    with RepositoryBuilder(paths, GENERATION) as builder:
        for path in ("transactions/a.csv", "transactions/b.csv"):
            preserve_file(builder, source, FileContext("a" * 64, "synthetic", path))
        builder.finalize()
    with RepositoryReader(paths.database) as reader:
        assert len(reader.rows("source_artifacts")) == 1
        assert len(reader.rows("source_occurrences")) == 2
        assert len(reader.rows("transactions")) == 4
    assert paths.object_path(hashlib.sha256(data).hexdigest()).read_bytes() == data


@pytest.mark.parametrize("suffix", ["xlsx", "zip", "jsonl", "bin"])
def test_opaque_artifacts_are_not_reimported(tmp_path: Path, suffix: str) -> None:
    data = b"PK\x03\x04synthetic opaque evidence\x00\xff"
    paths, analysis = build(tmp_path, data, f"imports/evidence.{suffix}")
    assert analysis["disposition_counts"] == {"preserved_opaque": 1}
    assert paths.object_path(hashlib.sha256(data).hexdigest()).read_bytes() == data


@pytest.mark.parametrize(
    ("filename", "data", "status"),
    [
        ("rules.yaml", b"rules: []\n", "parsed"),
        ("goals.json", b'{"budget": "10.10", "optional": null}', "parsed"),
        ("assets.yaml", b"[invalid", "invalid"),
    ],
)
def test_config_revisions_keep_bytes_and_parse_status(
    tmp_path: Path,
    filename: str,
    data: bytes,
    status: str,
) -> None:
    paths, _ = build(tmp_path, data, filename)
    with RepositoryReader(paths.database) as reader:
        assert reader.rows("config_revisions")[0]["parsed_status"] == status
        assert reader.rows("config_heads") == []
    assert paths.object_path(hashlib.sha256(data).hexdigest()).read_bytes() == data


@pytest.mark.parametrize("data", [b"", b"\n1,2\n", b'a,b\n1,2\n"unterminated', b"\xff"])
def test_malformed_csv_file_disposition_is_opaque(tmp_path: Path, data: bytes) -> None:
    paths, analysis = build(tmp_path, data, "overlay.csv")
    assert analysis["issue_counts"]["invalid_csv"] == 1
    with RepositoryReader(paths.database) as reader:
        file_provenance = next(
            row["provenance_id"]
            for row in reader.rows("record_provenance")
            if json.loads(row["source_coordinate_json"])["row"] is None
        )
        disposition = next(
            row
            for row in reader.rows("migration_dispositions")
            if row["provenance_id"] == file_provenance
        )
        assert disposition["disposition"] == "preserved_opaque"


@pytest.mark.parametrize("filename", ["goals.json", "goals.yaml"])
def test_config_numeric_representation_is_explicit(tmp_path: Path, filename: str) -> None:
    data = b'{"amount": 10.10}' if filename.endswith("json") else b"amount: 10.10\n"
    paths, analysis = build(tmp_path, data, filename)
    assert analysis["issue_counts"]["config_decimal_lexical_representation"] == 1
    with RepositoryReader(paths.database) as reader:
        assert (
            json.loads(reader.rows("config_revisions")[0]["canonical_payload_json"])["amount"]
            == "10.10"
        )


def test_duplicate_json_config_keys_are_not_silently_collapsed(tmp_path: Path) -> None:
    paths, analysis = build(tmp_path, b'{"key": 1, "key": 2}', "rules.json")
    assert analysis["issue_counts"]["unsupported_config_parse"] == 1
    with RepositoryReader(paths.database) as reader:
        assert reader.rows("config_revisions")[0]["parsed_status"] == "invalid"


def test_multiline_and_unicode_line_separator_remain_exact(tmp_path: Path) -> None:
    data = 'a,b\r\n"one\ntwo\u0085three",quoted"literal\r\n'.encode()
    paths, _ = build(tmp_path, data, "overlay.csv")
    with RepositoryReader(paths.database) as reader:
        payloads = [json.loads(row["payload_json"]) for row in reader.rows("legacy_payloads")]
        row = next(payload for payload in payloads if "raw_record" in payload)
        assert row["raw_record"].encode() == data.split(b"\r\n", 1)[1]
        assert row["values"] == ["one\ntwo\u0085three", 'quoted"literal']


def test_asset_and_fact_rows_remain_distinct_domains(tmp_path: Path) -> None:
    data = (
        b"snapshot_date,account_id,instrument_id,quantity,market_value,currency\n"
        b"2026-01-01,account,asset,0.0037,10.10,EUR\n"
    )
    paths, analysis = build(tmp_path, data, "assets/snapshots.csv")
    assert analysis["record_counts"]["asset_snapshot"] == 1
    with RepositoryReader(paths.database) as reader:
        assert reader.rows("transactions") == []
        assert reader.rows("money_values")[0]["currency_code"] == "EUR"
    fact_data = (
        b"fact_id,snapshot_date,sheet_name,block_id,block_title,fact_kind,value_type,value_numeric\n"
        b"fact,2026-01-01,sheet,block,title,total,number,10.10\n"
    )
    fact_paths, fact_analysis = build(tmp_path, fact_data, "overview/facts.csv", "fact")
    assert fact_analysis["record_counts"]["overview_fact"] == 1
    with RepositoryReader(fact_paths.database) as reader:
        assert reader.rows("transactions") == []
        assert reader.rows("exact_values")[0]["lexical"] == "10.10"


def test_missing_cross_file_fact_stays_explicitly_opaque(tmp_path: Path) -> None:
    paths, analysis = build(tmp_path, b"source_fact_id,amount\nfact,10.10\n", "balance.csv")
    assert analysis["issue_counts"]["unresolved_source_fact"] == 1
    with RepositoryReader(paths.database) as reader:
        assert reader.rows("overview_balances") == []
        assert reader.rows("overview_facts") == []


@pytest.mark.parametrize("amount", ["NaN", "Infinity", "1e-256", ""])
def test_unsupported_amount_retains_row_without_typed_success(tmp_path: Path, amount: str) -> None:
    paths, analysis = build(tmp_path, transaction_bytes((amount,)))
    assert analysis["disposition_counts"]["preserved_opaque"] == 1
    assert analysis["issue_counts"]
    with RepositoryReader(paths.database) as reader:
        assert reader.rows("transactions") == []
        payloads = [json.loads(row["payload_json"]) for row in reader.rows("legacy_payloads")]
        payload = next(row for row in payloads if "columns" in row)
        assert payload["values"][payload["columns"].index("amount")] == amount


def test_unknown_fields_and_invalid_flags_are_not_silently_dropped(tmp_path: Path) -> None:
    output = io.StringIO(newline="")
    reader = csv.reader(io.StringIO(transaction_bytes(("10.10",)).decode()))
    writer = csv.writer(output)
    header, row = list(reader)
    writer.writerow([*header, "unknown_field"])
    row[header.index("needs_review")] = "undecidable"
    writer.writerow([*row, "opaque-value"])
    paths, analysis = build(tmp_path, output.getvalue().encode())
    assert analysis["issue_counts"]["unknown_field"] == 1
    assert analysis["issue_counts"]["invalid_optional_flag"] == 1
    assert analysis["disposition_counts"]["preserved_opaque"] == 1
    with RepositoryReader(paths.database) as repository:
        assert repository.rows("transactions")[0]["needs_review"] is None


def _csv_dicts(rows: list[dict[str, str | None]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode()


@pytest.mark.parametrize("type_norm", ["unsupported", "Expense", " expense", "", None])
def test_transaction_type_constraint_preserves_bad_row_and_continues(
    tmp_path: Path,
    type_norm: str | None,
) -> None:
    original = list(csv.DictReader(io.StringIO(transaction_bytes(("10.10",)).decode())))[0]
    bad = {**original, "type_norm": type_norm}
    data = _csv_dicts([bad, original])

    paths, analysis = build(tmp_path, data)

    assert analysis["issue_counts"]["unsupported_transaction_type"] == 1
    assert analysis["record_counts"]["transaction"] == 1
    assert analysis["record_counts"]["exact_value"] == 1
    assert analysis["disposition_counts"]["preserved_opaque"] == 1
    with RepositoryReader(paths.database) as reader:
        assert reader.rows("transactions")[0]["type_norm"] == "expense"
        assert len(reader.rows("accounts")) == 1
        assert len(reader.rows("exact_values")) == 1
        assert len(reader.rows("legacy_payloads")) == 3
        row_provenance = reader.rows("transactions")[0]["provenance_id"]
        provenance = next(
            row
            for row in reader.rows("record_provenance")
            if row["provenance_id"] == row_provenance
        )
        assert json.loads(provenance["source_coordinate_json"])["row"] == 2
    assert paths.object_path(hashlib.sha256(data).hexdigest()).read_bytes() == data


@pytest.mark.parametrize("type_norm", ["expense", "income", "transfer", "other"])
def test_supported_transaction_types_are_not_reclassified(tmp_path: Path, type_norm: str) -> None:
    original = list(csv.DictReader(io.StringIO(transaction_bytes(("10.10",)).decode())))[0]
    paths, analysis = build(tmp_path, _csv_dicts([{**original, "type_norm": type_norm}]))
    assert analysis["issue_counts"] == {}
    with RepositoryReader(paths.database) as reader:
        assert reader.rows("transactions")[0]["type_norm"] == type_norm


@pytest.mark.parametrize(
    ("quantity", "market_value"),
    [
        (None, None),
        ("", ""),
        ("NaN", "invalid"),
        (None, "1e-256"),
    ],
)
def test_asset_requires_one_typed_value_before_creating_entities(
    tmp_path: Path,
    quantity: str | None,
    market_value: str | None,
) -> None:
    row = {
        "snapshot_date": "2026-01-01",
        "account_id": "synthetic-account",
        "instrument_id": "synthetic-resource",
        "quantity": quantity,
        "market_value": market_value,
        "currency": "USD",
    }
    data = _csv_dicts([row, {**row, "quantity": "0.0037", "market_value": "10.10"}])

    paths, analysis = build(tmp_path, data, "assets/snapshots.csv")

    assert analysis["issue_counts"]["asset_snapshot_without_value"] == 1
    assert analysis["disposition_counts"]["preserved_opaque"] == 1
    assert analysis["record_counts"]["asset_snapshot"] == 1
    assert analysis["record_counts"]["exact_value"] == 2
    with RepositoryReader(paths.database) as reader:
        assert len(reader.rows("asset_snapshots")) == 1
        assert len(reader.rows("accounts")) == len(reader.rows("resources")) == 1
        assert len(reader.rows("exact_values")) == 2
        assert len(reader.rows("legacy_payloads")) == 3


@pytest.mark.parametrize(("quantity", "market_value"), [("0", None), (None, "0")])
def test_asset_one_zero_value_satisfies_existing_constraint(
    tmp_path: Path,
    quantity: str | None,
    market_value: str | None,
) -> None:
    data = _csv_dicts(
        [
            {
                "snapshot_date": "2026-01-01",
                "account_id": "account",
                "instrument_id": "resource",
                "quantity": quantity,
                "market_value": market_value,
                "currency": "USD",
            }
        ]
    )
    paths, analysis = build(tmp_path, data, "assets/snapshots.csv")
    assert analysis["issue_counts"] == {}
    assert analysis["record_counts"]["asset_snapshot"] == 1
    with RepositoryReader(paths.database) as reader:
        assert reader.rows("exact_values")[0]["coefficient"] == "0"


@pytest.mark.parametrize(
    ("value_type", "numeric", "text", "issue"),
    [
        ("unknown", "10.10", "retained", "incomplete_overview_fact"),
        ("number", None, None, "overview_fact_numeric_type_mismatch"),
        ("number", "NaN", "retained", "overview_fact_numeric_type_mismatch"),
        ("text", "10.10", "retained", "overview_fact_numeric_type_mismatch"),
        ("date", "10.10", "2026-01-01", "overview_fact_numeric_type_mismatch"),
        ("empty", "0", None, "overview_fact_numeric_type_mismatch"),
        ("unsupported", "10.10", "retained", "overview_fact_numeric_type_mismatch"),
        ("text", None, None, "overview_fact_missing_text"),
        ("date", None, None, "overview_fact_missing_text"),
        ("unsupported", None, None, "overview_fact_missing_text"),
    ],
)
def test_fact_constraint_rejection_leaves_no_partial_numeric_insert(
    tmp_path: Path,
    value_type: str,
    numeric: str | None,
    text: str | None,
    issue: str,
) -> None:
    row = {
        "fact_id": "synthetic-fact",
        "snapshot_date": "2026-01-01",
        "sheet_name": "sheet",
        "block_id": "block",
        "block_title": "title",
        "fact_kind": "total",
        "value_type": value_type,
        "value_numeric": numeric,
        "value_text": text,
    }
    data = _csv_dicts([row, {**row, "value_type": "number", "value_numeric": "10.10"}])

    paths, analysis = build(tmp_path, data, "overview/facts.csv")

    assert analysis["issue_counts"][issue] == 1
    assert analysis["disposition_counts"]["preserved_opaque"] == 1
    assert analysis["record_counts"]["overview_fact"] == 1
    assert analysis["record_counts"]["exact_value"] == 1
    with RepositoryReader(paths.database) as reader:
        assert len(reader.rows("overview_facts")) == 1
        assert len(reader.rows("exact_values")) == 1
        assert len(reader.rows("legacy_payloads")) == 3
        facts = reader.rows("overview_facts")
        assert facts[0]["value_type"] == "number"
        assert reader.rows("exact_values")[0]["provenance_id"] == facts[0]["provenance_id"]
    assert paths.object_path(hashlib.sha256(data).hexdigest()).read_bytes() == data


@pytest.mark.parametrize(
    ("value_type", "numeric", "text"),
    [
        ("number", "0", None),
        ("number", "10.10", "retained"),
        ("empty", None, None),
        ("empty", None, "retained"),
        ("text", None, "text"),
        ("date", None, "2026-01-01"),
        ("unsupported", None, "retained"),
    ],
)
def test_fact_supported_combinations_keep_original_type(
    tmp_path: Path,
    value_type: str,
    numeric: str | None,
    text: str | None,
) -> None:
    data = _csv_dicts(
        [
            {
                "fact_id": "fact",
                "snapshot_date": "2026-01-01",
                "sheet_name": "sheet",
                "block_id": "block",
                "block_title": "title",
                "fact_kind": "total",
                "value_type": value_type,
                "value_numeric": numeric,
                "value_text": text,
            }
        ]
    )
    paths, analysis = build(tmp_path, data, "overview/facts.csv")
    assert analysis["issue_counts"] == {}
    with RepositoryReader(paths.database) as reader:
        fact = reader.rows("overview_facts")[0]
        assert fact["value_type"] == value_type
        assert fact["value_text"] == text


def test_fact_quoted_empty_text_remains_valid_blank(tmp_path: Path) -> None:
    data = (
        b"fact_id,snapshot_date,sheet_name,block_id,block_title,fact_kind,value_type,value_text\n"
        b'fact,2026-01-01,sheet,block,title,total,text,""\n'
    )
    paths, analysis = build(tmp_path, data, "overview/facts.csv")
    assert analysis["issue_counts"] == {}
    with RepositoryReader(paths.database) as reader:
        assert reader.rows("overview_facts")[0]["value_text"] == ""
