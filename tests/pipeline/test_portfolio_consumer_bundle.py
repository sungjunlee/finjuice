"""Native display bundles preserve revision identity and explicit limitations."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import polars as pl
import pytest

from finjuice.pipeline.backup import SourceRoot
from finjuice.pipeline.consumer_bundle import ConsumerBundleError
from finjuice.pipeline.portfolio_consumer_bundle import materialize_portfolio_consumer_bundle
from finjuice.pipeline.storage.sqlite import RepositoryReader
from tests.pipeline.test_consumer_bundle import _prepare
from tests.pipeline.test_sqlite_exact_import import _import, _inline, _overview_book, _Repo, _row
from tests.pipeline.test_sqlite_exact_import import repo as _repo_fixture

repo = _repo_fixture


def test_primary_projection_overlay_empty_latest_and_idempotency(tmp_path: Path) -> None:
    overlay = tmp_path / "overlay.yaml"
    overlay.write_bytes(b"cash_like: []\n")
    source, _, database = _prepare(
        tmp_path,
        overlay=SourceRoot("overlay", "required", overlay),
        extra_root=True,
        empty_month=True,
    )
    dest = tmp_path / "projection"
    with RepositoryReader(database, expected_schema_version=5) as reader:
        first = materialize_portfolio_consumer_bundle(reader, dest, data_dir=source)
        second = materialize_portfolio_consumer_bundle(reader, dest, data_dir=source)
    assert first.manifest == second.manifest
    assert first.overlay_path is not None
    assert first.overlay_path.read_bytes() == b"cash_like: []\n"
    for directory in ("balance", "investments", "loans"):
        frame = pl.read_csv(dest / f"banksalad/{directory}/2026/01/{directory}.csv")
        assert frame.height == 1  # auxiliary root does not enter the projection
    assert first.manifest["domains"]["investment"]["selected_row_count"] == 0
    assert first.manifest["domains"]["investment"]["as_of"] is None
    assert first.manifest["readiness"]["complete_report_usable"] is False
    assert first.manifest["readiness"]["overlay"]["freshness"] == "unverified"
    sidecar = json.loads(
        (dest / "banksalad/investments/2026/01/investments.csv.exact.json").read_bytes()
    )
    assert "valuation_amount_coefficient" in sidecar["rows"][0]
    assert "return_rate_unit" in sidecar["rows"][0]
    (dest / "manifest.json").write_text("{}")
    with RepositoryReader(database, expected_schema_version=5) as reader:
        with pytest.raises(ConsumerBundleError, match="Previous output"):
            materialize_portfolio_consumer_bundle(reader, dest, data_dir=source)


def _updated_overview() -> bytes:
    result = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(_overview_book())) as source:
        with zipfile.ZipFile(result, "w") as output:
            for name in source.namelist():
                content = (
                    source.read(name)
                    .replace(b"1250000", b"2500000")
                    .replace(b"2026-06-15", b"2026-07-15")
                )
                output.writestr(name, content)
    return result.getvalue()


def test_actual_native_import_changes_projection_and_rejects_stale_output(repo: _Repo) -> None:
    _import(repo, _overview_book(), key="first-overview", revision=0)
    dest = repo.data_dir.parent / "projection"
    with RepositoryReader(repo.database) as reader:
        first = materialize_portfolio_consumer_bundle(reader, dest, data_dir=repo.data_dir)
    _import(repo, _updated_overview(), key="next-overview", revision=repo.revision())
    with RepositoryReader(repo.database) as reader:
        with pytest.raises(ConsumerBundleError, match="Previous output"):
            materialize_portfolio_consumer_bundle(reader, dest, data_dir=repo.data_dir)
        second = materialize_portfolio_consumer_bundle(
            reader, dest.with_name("next-projection"), data_dir=repo.data_dir
        )
    assert second.manifest["dataset_revision"] > first.manifest["dataset_revision"]
    assert second.manifest["domains"]["balance"]["as_of"] == "2026-07-15"
    frame = pl.read_csv(second.directory / "banksalad/balance/2026/07/balance.csv")
    assert frame["amount"].to_list() == [2500000.0]
    assert frame["source_basis"].to_list() == ["native"]
    assert first.manifest["domains"]["balance"]["as_of"] == "2026-06-15"


@pytest.mark.parametrize(
    "patch,reason",
    [
        ({"amount": None}, "missing_amount"),
        ({"currency_unknown": 1}, "unknown_currency"),
        ({"currency": "USD"}, "non_krw_or_missing_currency"),
        ({"side": "unclassified"}, "unsupported_balance_side"),
    ],
)
def test_readiness_rejects_values_the_legacy_consumer_would_silently_sum(
    patch: dict[str, object], reason: str
) -> None:
    from finjuice.pipeline.portfolio_consumer_bundle import _readiness

    row = {"amount": 12.0, "currency": "KRW", "currency_unknown": 0, "side": "asset"}
    assert _readiness("balance", [row], ("amount",)) == set()
    assert reason in _readiness("balance", [{**row, **patch}], ("amount",))


def test_unprojected_native_row_blocks_readiness_but_complete_projection_passes(
    repo: _Repo,
) -> None:
    _import(repo, _overview_book(), key="supported", revision=0)
    with RepositoryReader(repo.database) as reader:
        good = materialize_portfolio_consumer_bundle(reader, repo.data_dir.parent / "supported")
    assert good.manifest["domains"]["balance"]["coverage"]["unrepresented_projection_count"] == 0
    assert "unrepresented_native_projection" not in good.manifest["domains"]["balance"]["reasons"]
    buffer = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(_updated_overview())) as source:
        with zipfile.ZipFile(buffer, "w") as output:
            for name in source.namelist():
                content = source.read(name)
                if name.startswith("xl/worksheets/"):
                    bad = _row(
                        17,
                        _inline("B17", "예금"),
                        _inline("C17", "Unsupported"),
                        _inline("D17", "not-money"),
                    )
                    content = content.replace(b"</sheetData>", bad.encode() + b"</sheetData>")
                output.writestr(name, content)
    _import(repo, buffer.getvalue(), key="partially-supported", revision=repo.revision())
    with RepositoryReader(repo.database) as reader:
        result = materialize_portfolio_consumer_bundle(reader, repo.data_dir.parent / "partial")
    balance = result.manifest["domains"]["balance"]
    assert balance["selected_row_count"] == 1
    assert balance["coverage"]["unrepresented_projection_count"] == 1
    assert "unrepresented_native_projection" in balance["reasons"]
    assert balance["readiness"] == "incomplete"
    assert result.manifest["readiness"]["complete_report_usable"] is False


def test_bundle_empty_and_nonempty_months_have_identical_columns(tmp_path: Path) -> None:
    source, _, database = _prepare(tmp_path, empty_month=True)
    with RepositoryReader(database, expected_schema_version=5) as reader:
        bundle = materialize_portfolio_consumer_bundle(reader, tmp_path / "out", data_dir=source)
    january = bundle.directory / "banksalad/investments/2026/01/investments.csv"
    february = bundle.directory / "banksalad/investments/2026/02/investments.csv"
    assert january.read_bytes().splitlines()[0] == february.read_bytes().splitlines()[0]
    assert pl.read_csv(f"{bundle.directory}/banksalad/investments/*/*/investments.csv").height == 1


def test_overview_coverage_ignores_unrelated_unknown_and_later_observations(repo: _Repo) -> None:
    from dataclasses import replace

    from finjuice.pipeline.portfolio_consumer_bundle import _native_coverage

    _import(repo, _overview_book(), key="overview", revision=0)
    with RepositoryReader(repo.database) as reader:
        snapshot = reader.portfolio_snapshot()
    projection = snapshot.native_overview_reports["overview_balances"][0]
    provenance = next(
        row
        for row in snapshot.evidence["record_provenance"]
        if row["provenance_id"] == projection["provenance_id"]
    )
    extra = {**provenance, "provenance_id": "unrepresented"}
    unrelated = tuple(
        {
            "entity_id": f"unrelated-{i}",
            "source_occurrence_id": provenance["source_occurrence_id"],
            "effective_at": effective,
        }
        for i, effective in enumerate((None, "2030-01-01"))
    )
    changed = replace(
        snapshot,
        evidence={
            **snapshot.evidence,
            "record_provenance": (*snapshot.evidence["record_provenance"], extra),
            "observations": (*snapshot.evidence["observations"], *unrelated),
        },
    )
    assert _native_coverage(changed, "balance", "2026-07-15")["unrepresented_projection_count"] == 0
    assert _native_coverage(changed, "balance", "2026-06-15")["unrepresented_projection_count"] == 1


def test_portfolio_snapshot_does_not_pull_transactions_from_overview_workbook(repo: _Repo) -> None:
    import re

    from tests.pipeline.test_sqlite_exact_import import _tx_book, _tx_row

    with zipfile.ZipFile(io.BytesIO(_overview_book())) as book:
        content = book.read("xl/worksheets/sheet1.xml").decode()
    rows = re.search(r"<sheetData>(.*?)</sheetData>", content).group(1)
    data = _tx_book(*(_tx_row(index) for index in range(2, 12)), extra_sheets={"뱅샐현황": rows})
    _import(repo, data, key="combined", revision=0)
    with RepositoryReader(repo.database) as reader:
        snapshot = reader.portfolio_snapshot()
        transactions = reader.transaction_snapshot()
    assert len(transactions.rows) > 0
    overview_ids = {row["observation_id"] for row in snapshot.overview_facts}
    assert {row["entity_id"] for row in snapshot.evidence["observations"]} == overview_ids


def test_multiple_report_sources_are_not_assumed_disjoint(repo: _Repo) -> None:
    from finjuice.pipeline.portfolio_consumer_bundle import _selected_source_count
    from finjuice.pipeline.portfolio_display import PortfolioDisplay

    _import(repo, _overview_book(), key="first", revision=0)
    buffer = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(_overview_book())) as source:
        with zipfile.ZipFile(buffer, "w") as output:
            for name in source.namelist():
                output.writestr(name, source.read(name).replace(b"1250000", b"2500000"))
    _import(repo, buffer.getvalue(), key="independent", revision=repo.revision())
    with RepositoryReader(repo.database) as reader:
        snapshot = reader.portfolio_snapshot()
        bundle = materialize_portfolio_consumer_bundle(reader, repo.data_dir.parent / "mixed")
    balance = bundle.manifest["domains"]["balance"]
    assert balance["selected_row_count"] == 2
    assert "multiple_selected_report_sources" in balance["reasons"]
    rows = PortfolioDisplay(snapshot).balance_partition("2026-06").to_dicts()
    assert _selected_source_count(snapshot, [rows[0], rows[0]]) == 1
    assert _selected_source_count(snapshot, [rows[0], {**rows[0], "source_basis": "reported"}]) == 2


@pytest.mark.parametrize("encoded", ["[]", "42"])
@pytest.mark.parametrize("field", ["coordinate", "payload"])
def test_nonobject_json_evidence_is_static_bundle_error(
    repo: _Repo, monkeypatch, encoded, field
) -> None:
    from dataclasses import replace

    _import(repo, _overview_book(), key="overview", revision=0)
    with RepositoryReader(repo.database) as reader:
        snapshot = reader.portfolio_snapshot()
        fact = snapshot.overview_facts[0]
        table, column = (
            ("record_provenance", "source_coordinate_json")
            if field == "coordinate"
            else ("legacy_payloads", "payload_json")
        )
        changed = replace(
            snapshot,
            evidence={
                **snapshot.evidence,
                table: tuple(
                    {**row, column: encoded}
                    if row["provenance_id"] == fact["provenance_id"]
                    else row
                    for row in snapshot.evidence[table]
                ),
            },
        )
        monkeypatch.setattr(reader, "portfolio_snapshot", lambda: changed)
        with pytest.raises(ConsumerBundleError, match="Portfolio"):
            materialize_portfolio_consumer_bundle(reader, repo.data_dir.parent / "bad-json")
