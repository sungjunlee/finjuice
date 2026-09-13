"""Independent preservation and replay checks for completed XLSX imports."""

from __future__ import annotations

import json
import sqlite3

import pytest

from finjuice.pipeline.ingest import exact_transactions
from finjuice.pipeline.storage.mutation_facade import BulkMutationPreview
from finjuice.pipeline.storage.sqlite import MutationAbortedError, MutationValidationError
from finjuice.pipeline.storage.sqlite.exact_import import constants
from finjuice.pipeline.storage.sqlite.ids import new_entity_id
from tests.pipeline.test_sqlite_exact_import import (
    ASSET_SHARED,
    _count,
    _import,
    _inline,
    _n,
    _overview_book,
    _package,
    _query,
    _Repo,
    _row,
    _s,
    _tx_book,
    _tx_row,
)
from tests.pipeline.test_sqlite_exact_import import repo as _repo_fixture

repo = _repo_fixture


def _manifest(repo: _Repo) -> tuple[str, dict]:
    row = _query(
        repo.database,
        "SELECT p.provenance_id, p.payload_json FROM legacy_payloads AS p "
        "JOIN record_provenance AS r ON r.provenance_id = p.provenance_id "
        "WHERE json_extract(r.source_coordinate_json, '$.kind') = ?",
        (constants.MANIFEST_COORDINATE_KIND,),
    )[0]
    return row[0], json.loads(row[1])


@pytest.mark.parametrize("damage", ["occurrence", "transaction", "negative_count", "count", "role"])
def test_malformed_completion_never_reports_successful_noop(repo: _Repo, damage: str) -> None:
    data = _tx_book(_tx_row(2))
    _import(repo, data, key="first", revision=0)
    provenance_id, payload = _manifest(repo)
    if damage == "occurrence":
        payload["ids"]["occurrence_id"] = new_entity_id()
    elif damage == "transaction":
        payload["ids"]["transaction_ids"] = [new_entity_id()]
    elif damage in {"count", "negative_count"}:
        payload["counts"]["transactions"]["inserted"] = -4 if damage == "negative_count" else 999
    with sqlite3.connect(repo.database) as connection:
        connection.execute("DROP TRIGGER IF EXISTS legacy_payloads_no_update")
        connection.execute("DROP TRIGGER IF EXISTS record_provenance_no_update")
        connection.execute(
            "UPDATE legacy_payloads SET payload_json = ? WHERE provenance_id = ?",
            (json.dumps(payload), provenance_id),
        )
        if damage == "role":
            connection.execute(
                "UPDATE record_provenance SET source_coordinate_json = ? WHERE provenance_id = ?",
                (
                    json.dumps({"kind": constants.MANIFEST_COORDINATE_KIND, "role": "not-root"}),
                    provenance_id,
                ),
            )

    with pytest.raises((MutationValidationError, MutationAbortedError)):
        _import(repo, data, key="after-damage", revision=1)

    assert repo.revision() == 1


@pytest.mark.parametrize("same_key", [False, True], ids=["fresh-noop", "original-replay"])
def test_parser_update_retains_completed_default_interpretation(
    repo: _Repo, monkeypatch: pytest.MonkeyPatch, same_key: bool
) -> None:
    data = _tx_book(_tx_row(2))
    first = _import(repo, data, key="first", revision=0)
    monkeypatch.setattr(exact_transactions, "PARSER_VERSION", "synthetic.new-parser.v2")
    assert constants.parser_versions()["transactions"] == "synthetic.new-parser.v2"

    result = _import(repo, data, key="first" if same_key else "next", revision=0 if same_key else 1)

    assert result.result["occurrence_id"] == first.result["occurrence_id"]
    assert repo.revision() == 1
    assert result.replayed if same_key else result.result["noop"]


def test_known_distinct_currencies_are_not_overlapping_money(repo: _Repo) -> None:
    _import(repo, _tx_book(_tx_row(2)), key="krw", revision=0)
    dollar_row = _tx_row(2).replace(">KRW<", ">USD<")

    result = _import(repo, _tx_book(dollar_row), key="usd", revision=1)

    assert result.result["counts"]["transactions"]["inserted"] == 1
    assert result.result["counts"]["transactions"]["quarantined"] == 0


def test_equivalent_known_instants_remain_unproven_overlap(repo: _Repo) -> None:
    _import(repo, _tx_book(_tx_row(2, time_text="13:04:05Z")), key="utc", revision=0)

    result = _import(
        repo, _tx_book(_tx_row(2, time_text="22:04:05+09:00")), key="offset", revision=1
    )

    assert result.result["counts"]["transactions"]["inserted"] == 0
    assert result.result["counts"]["transactions"]["quarantined"] == 1


@pytest.mark.parametrize("coarse_time", ["13:04", ""])
@pytest.mark.parametrize("coarse_first", [True, False])
def test_lossy_time_precision_quarantines_overlap(
    repo: _Repo, coarse_time: str, coarse_first: bool
) -> None:
    times = (coarse_time, "13:04:05") if coarse_first else ("13:04:05", coarse_time)
    _import(repo, _tx_book(_tx_row(2, time_text=times[0])), key="first", revision=0)

    result = _import(repo, _tx_book(_tx_row(2, time_text=times[1])), key="second", revision=1)

    assert result.result["counts"]["transactions"]["inserted"] == 0
    assert result.result["counts"]["transactions"]["quarantined"] == 1


def test_overview_receipt_uncovered_count_matches_persisted_dispositions(repo: _Repo) -> None:
    result = _import(repo, _overview_book(), key="overview", revision=0)
    _, manifest = _manifest(repo)

    assert result.result["counts"]["uncovered_rows"] == manifest["ids"]["uncovered_rows"] == 0
    assert result.result["counts"]["assets"]["unsupported"] == 0
    assert result.result["counts"]["transactions"]["unsupported"] == 0
    assert result.result["counts"]["mapper_status"]["assets"] == "no_asset_sheet"
    assert result.result["counts"]["mapper_status"]["transactions"] == "no_transaction_sheet"


def test_partial_quantity_only_asset_is_persisted(repo: _Repo) -> None:
    result = _import(repo, _quantity_only_asset_book(), key="qty-only", revision=0)
    stored = _query(
        repo.database,
        "SELECT quantity_value_id, market_value_id FROM asset_snapshots",
    )[0]

    assert result.result["counts"]["assets"]["inserted"] == 1
    assert stored[0] is not None
    assert stored[1] is None
    assert _count(repo.database, "asset_snapshots") == 1


def test_completed_preview_is_noop_without_writes(repo: _Repo) -> None:
    data = _tx_book(_tx_row(2))
    first = _import(repo, data, key="first", revision=0)
    artifacts = _count(repo.database, "source_artifacts")
    preview = _import(repo, data, key="preview-noop", revision=repo.revision(), preview=True)

    assert isinstance(preview, BulkMutationPreview)
    assert preview.result["noop"] is True
    assert preview.result["completed"] is False
    assert preview.result["occurrence_id"] == first.result["occurrence_id"]
    assert preview.result["counts"]["transactions"]["inserted"] == 0
    assert preview.result["counts"]["transactions"]["reused"] == 1
    assert _count(repo.database, "transactions") == 1
    assert _count(repo.database, "source_artifacts") == artifacts
    assert repo.revision() == 1


def _quantity_only_asset_book() -> bytes:
    header = _row(1, *[_s(f"{col}1", idx) for idx, col in enumerate("ABCDEFGH")])
    body = _row(
        2,
        _inline("A2", "2026-06-15"),
        _inline("B2", "acct-1"),
        _inline("C2", "계좌A"),
        _inline("D2", "inst-1"),
        _inline("E2", "종목A"),
        _n("F2", "1.5"),
        _inline("H2", "USD"),
    )
    return _package({"holdings": header + body}, shared=ASSET_SHARED)
