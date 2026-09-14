"""Actual canonical asset decisions, declared-scope totals and recovery graph continuity."""

from __future__ import annotations

import io
import zipfile

import pytest
from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app
from finjuice.pipeline.storage.sqlite import (
    GenerationPaths,
    RepositoryBuilder,
    RepositoryReader,
    new_entity_id,
    upgrade_repository,
)
from finjuice.pipeline.storage.sqlite.asset_reports import AssetReportQuery
from finjuice.pipeline.storage.sqlite.backup import create_backup, restore_backup
from finjuice.pipeline.storage.sqlite.backup_coverage import _load_facts
from finjuice.pipeline.storage.sqlite.inactive_restore import (
    InactiveRestoreSession,
    restore_workspace,
)
from finjuice.pipeline.storage.sqlite.recovery_bundle import (
    capture_recovery_bundle,
    verify_recovery_bundle,
)
from finjuice.pipeline.storage.sqlite.schema import SQLITE_SCHEMA_VERSION
from tests.pipeline.test_account_decisions import _environment, _ownership, _payload
from tests.pipeline.test_sqlite_exact_import import _asset_book


def _invoke(env, args, *, json_output=True):
    return CliRunner().invoke(
        app,
        [
            "--data-dir",
            str(env.source.data_dir),
            "ssot",
            "assets",
            *args,
            *(["--json"] if json_output else []),
        ],
        obj={"activation_evidence_provider": env.source.evidence_provider},
    )


def _book(day, amount):
    buffer = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(_asset_book())) as original,
        zipfile.ZipFile(buffer, "w") as output,
    ):
        for name in original.namelist():
            content = original.read(name)
            if name.endswith(".xml"):
                content = content.replace(b"2026-06-15", day.encode()).replace(
                    b"150.25", amount.encode()
                )
            output.writestr(name, content)
    return buffer.getvalue()


def _source(env, day, amount, key):
    with RepositoryReader(env.database) as reader:
        before = {row["entity_id"] for row in reader.rows("asset_snapshots")}
    env.import_bytes(_book(day, amount), key)
    with RepositoryReader(env.database) as reader:
        return next(row for row in reader.rows("asset_snapshots") if row["entity_id"] not in before)


def _meaning(env, source, day, **changes):
    return {
        "source_entity_id": source["entity_id"],
        "value_id": source["market_value_id"],
        "account_id": env.account,
        "measure_kind": "valuation",
        "source_kind": "institution_export",
        "as_of": day,
        "scope_state": "complete",
        "original_currency": "USD",
        "evidence": {"reason": "synthetic operator interpreted existing source"},
        **changes,
    }


def _confirm(env, body, key, *, previous=None, relation=False, **options):
    human = options.pop("human", False)
    assert not options
    path = env.file(key + ".json", body)
    verb = "correct" if previous else "confirm"
    args = [
        ("relation-" if relation else "") + verb,
        *([previous] if previous else []),
        path,
        *env.options(key),
    ]
    result = _invoke(env, args, json_output=not human)
    if human:
        assert result.exit_code == 0 and "자산 결정 기록" in result.output
        result = _invoke(env, args)
        assert _payload(result)["replayed"]
    name = "ssot_assets_" + ("relation_" if relation else "") + verb + ".schema.json"
    return _payload(result, name)


def _report(env, sources, *, currency="USD", day="2026-07-02", human=False):
    args = ["report", "--as-of", day, "--currency", currency, "--party", env.parties[0]]
    for source in sources:
        args += ["--source", source["entity_id"]]
    result = _invoke(env, args, json_output=not human)
    if human:
        assert result.exit_code == 0 and "명시 범위 자산 보고" in result.output
        result = _invoke(env, args)
    return _payload(result, "ssot_assets_report.schema.json")


def _own(env, account=None):
    body = _ownership(env)
    body["account_id"] = account or env.account
    body["completeness"] = "complete"
    body["shares"] = [
        {"party_id": env.parties[0], "coefficient": "5", "scale": 1},
        {"party_id": env.parties[1], "coefficient": "5", "scale": 1},
    ]
    return _payload(
        env.invoke(
            [
                "ownership-confirm",
                env.file("own.json", body),
                *env.options("own-" + body["account_id"]),
            ]
        )
    )


@pytest.mark.parametrize("human", [False, True])
def test_canonical_assets_scope_relations_flow_correction_and_capture_restore(tmp_path, human):
    env = _environment(tmp_path)
    _own(env)
    _own(env, env.other)
    summary = _source(env, "2026-07-01", "200", "summary")
    partial = _source(env, "2026-07-02", "900", "partial")
    old = _source(env, "2026-06-01", "800", "old")
    holding = _source(env, "2026-07-01", "70", "holding")
    manual = _source(env, "2026-07-01", "201", "manual")
    cash = _source(env, "2026-07-01", "20", "cash")
    liability = _source(env, "2026-07-01", "40", "liability")
    for source, changes in [
        (summary, {}),
        (partial, {"scope_state": "partial"}),
        (old, {"source_kind": "screenshot"}),
        (holding, {"source_kind": "workbook_holdings", "resource_id": holding["resource_id"]}),
        (manual, {"source_kind": "manual"}),
        (cash, {"measure_kind": "cash_movement"}),
        (
            liability,
            {
                "measure_kind": "right_obligation",
                "resource_id": liability["resource_id"],
                "net_worth_sign": -1,
                "account_id": env.other,
            },
        ),
    ]:
        _confirm(
            env,
            _meaning(env, source, source["snapshot_date"], **changes),
            source["entity_id"],
            human=human,
        )
    scope = [summary, partial, old, holding, manual, cash, liability]
    unresolved = _report(env, scope, human=human)
    assert unresolved["net_worth_total"] is None
    assert any(issue["kind"] == "unresolved_overlap" for issue in unresolved["issues"])
    summary_relation = _confirm(
        env,
        {
            "container_id": summary["entity_id"],
            "member_id": holding["entity_id"],
            "relation_kind": "includes",
            "evidence": {"reason": "summary contains this holding"},
        },
        "include",
        relation=True,
        human=human,
    )
    _confirm(
        env,
        {
            "container_id": summary["entity_id"],
            "member_id": manual["entity_id"],
            "relation_kind": "overlaps",
            "evidence": {"reason": "same institutional money"},
        },
        "manual-overlap",
        relation=True,
    )
    with RepositoryReader(env.database) as reader:
        head = next(
            row
            for row in reader.rows("asset_meaning_assertions")
            if row["source_entity_id"] == summary["entity_id"]
        )
    corrected = _meaning(env, summary, "2026-07-01", source_kind="workbook_summary")
    first = _confirm(env, corrected, "summary-correct", previous=head["assertion_id"], human=human)
    report = _report(env, scope, human=human)
    assert report["completeness"] == "complete_for_declared_scope"
    assert report["net_worth_total"] == {"coefficient": "800", "scale": 1}
    assert report["cash_flow_subtotal"] == {"coefficient": "100", "scale": 1}
    assert not report["valuation_is_cash_flow"]
    assert {issue["kind"] for issue in report["issues"]} >= {
        "historical_evidence",
        "partial_does_not_replace_complete",
    }
    assert any(
        line.get("exclusion", {}).get("assertion_id") == summary_relation["assertion_id"]
        for line in report["lines"]
    )
    stale = _invoke(
        env,
        [
            "correct",
            first["assertion_id"],
            env.file("stale.json", corrected),
            *env.options("stale", first["base_revision"]),
        ],
    )
    assert stale.exit_code != 0
    listing = _payload(_invoke(env, ["list"]), "ssot_assets_list.schema.json")
    assert listing["pending"] or listing["legacy_pending"]
    expected = _EXPECTED.pop(str(tmp_path))
    receipt = capture_recovery_bundle(env.source, expected)
    assert verify_recovery_bundle(env.source.destination, expected) == receipt
    restored = restore_workspace(env.source.destination / "snapshot", tmp_path / "restored")
    query = AssetReportQuery(
        "2026-07-02", "USD", (env.parties[0],), tuple(row["entity_id"] for row in scope)
    )
    with InactiveRestoreSession(restored) as session:
        again = session.read_snapshot(lambda reader: reader.canonical_assets(query))
        assert again["net_worth_total"] == report["net_worth_total"]
        history = session.read_snapshot(lambda reader: reader.rows("asset_meaning_assertions"))
        assert len([row for row in history if row["source_entity_id"] == summary["entity_id"]]) == 2
    import sqlite3

    with sqlite3.connect(env.database) as connection:
        assert any(fact.kind == "asset_meaning" for fact in _load_facts(connection))


_EXPECTED = {}


@pytest.fixture(autouse=True)
def retain_expected_graph(monkeypatch):
    import tests.pipeline.test_account_decisions as helpers

    original = helpers._live

    def live(path):
        result = original(path)
        _EXPECTED[str(path)] = result[1]
        return result

    monkeypatch.setattr(helpers, "_live", live)


def test_asset_unknown_ownership_fx_pending_and_immutable_relation_correction(tmp_path):
    env = _environment(tmp_path)
    first = _source(env, "2026-07-01", "12", "first")
    second = _source(env, "2026-07-01", "13", "second")
    meaning = _meaning(env, first, "2026-07-01")
    original = _confirm(env, meaning, "meaning")
    unknown = _report(env, [first], currency="KRW")
    assert unknown["net_worth_total"] is None
    assert {issue["kind"] for issue in unknown["issues"]} >= {
        "ownership_unconfirmed",
        "fx_basis_missing",
    }
    _own(env)
    meaning["fx"] = {
        "coefficient": "1300",
        "scale": 0,
        "quote_currency": "KRW",
        "as_of": "2026-07-01",
        "evidence": {"policy_id": "synthetic operator FX quotation"},
    }
    _confirm(env, meaning, "fx", previous=original["assertion_id"])
    converted = _report(env, [first], currency="KRW")
    assert converted["net_worth_total"] == {"coefficient": "78000", "scale": 1}
    assert converted["lines"][0]["original_currency"] == "USD"
    assert converted["lines"][0]["account_id"] == env.account
    assert converted["lines"][0]["fx_basis"]["rate"] == {"coefficient": "1300", "scale": 0}
    assert converted["lines"][0]["fx_basis"]["fx_evidence_json"]
    body = {
        "container_id": first["entity_id"],
        "member_id": second["entity_id"],
        "relation_kind": "overlaps",
        "confirmation_state": "unconfirmed",
        "evidence": {"reason": "pending matching evidence"},
    }
    relation = _confirm(env, body, "relation", relation=True)
    body["confirmation_state"] = "confirmed"
    corrected = _confirm(
        env, body, "relation-correct", relation=True, previous=relation["assertion_id"]
    )
    assert corrected["supersedes_assertion_id"] == relation["assertion_id"]
    with RepositoryReader(env.database) as reader:
        assert (
            len(
                [
                    row
                    for row in reader.rows("entity_relation_assertions")
                    if row["subject_entity_id"] == first["entity_id"]
                ]
            )
            == 2
        )
    stale = _report(env, [first], currency="KRW", day="2026-09-01")
    assert stale["net_worth_total"] is None and any(
        issue["kind"] == "stale" for issue in stale["issues"]
    )


@pytest.mark.parametrize("version", [4, 5, 6])
def test_prior_asset_schema_raw_restore_and_explicit_upgrade(tmp_path, version):
    source = GenerationPaths(tmp_path / "source")
    with RepositoryBuilder(source, new_entity_id(), expected_schema_version=version) as builder:
        builder.finalize()
    backup = tmp_path / "backup"
    create_backup(source.database, backup)
    restored = GenerationPaths(tmp_path / "raw")
    restore_backup(backup, restored.root)
    with RepositoryReader(restored.database, expected_schema_version=version) as reader:
        assert reader.info.schema_version == version
    current = GenerationPaths(tmp_path / "current")
    upgrade_repository(restored.database, current)
    with RepositoryReader(current.database) as reader:
        assert reader.info.schema_version == SQLITE_SCHEMA_VERSION
        assert reader.rows("asset_meaning_assertions") == []


def _catalog_asset_result(tmp_path, command):
    env = _environment(tmp_path)
    if command == "list":
        return _invoke(env, ["list"])
    source = _source(env, "2026-07-01", "10", "source")
    body = _meaning(env, source, "2026-07-01")
    if command == "report":
        _own(env)
        _confirm(env, body, "meaning")
        return _invoke(
            env,
            [
                "report",
                "--as-of",
                "2026-07-02",
                "--currency",
                "USD",
                "--party",
                env.parties[0],
                "--source",
                source["entity_id"],
            ],
        )
    previous = None
    relation = command.startswith("relation-")
    if relation:
        member = _source(env, "2026-07-01", "11", "member")
        body = {
            "container_id": source["entity_id"],
            "member_id": member["entity_id"],
            "relation_kind": "includes",
            "evidence": {"reason": "synthetic inclusion"},
        }
    if command.endswith("correct"):
        previous = _confirm(env, body, "first", relation=relation)["assertion_id"]
    return _invoke(
        env,
        [
            command,
            *([previous] if previous else []),
            env.file("command.json", body),
            *env.options("catalog"),
        ],
    )


@pytest.mark.parametrize("pending_state", ["unconfirmed", "rejected"])
def test_pending_asset_corrections_keep_confirmed_meaning_and_inclusion(tmp_path, pending_state):
    env = _environment(tmp_path)
    _own(env)
    first = _source(env, "2026-07-01", "10", "first")
    second = _source(env, "2026-07-01", "11", "second")
    body = _meaning(env, first, "2026-07-01")
    original = _confirm(env, body, "first-meaning")
    _confirm(env, _meaning(env, second, "2026-07-01"), "second-meaning")
    relation_body = {
        "container_id": first["entity_id"],
        "member_id": second["entity_id"],
        "relation_kind": "includes",
        "evidence": {"reason": "synthetic inclusion"},
    }
    relation = _confirm(env, relation_body, "relation", relation=True)
    body["confirmation_state"] = pending_state
    body["net_worth_sign"] = -1
    pending = _confirm(env, body, "pending-meaning", previous=original["assertion_id"])
    relation_body["confirmation_state"] = pending_state
    pending_relation = _confirm(
        env, relation_body, "pending-relation", previous=relation["assertion_id"], relation=True
    )
    report = _report(env, [first, second])
    assert report["net_worth_total"] is None
    assert report["known_net_worth_subtotal"] == {"coefficient": "50", "scale": 1}
    assert (
        next(
            line["assertion_id"]
            for line in report["lines"]
            if line["source_entity_id"] == first["entity_id"]
        )
        == original["assertion_id"]
    )
    assert any(
        line.get("exclusion", {}).get("assertion_id") == relation["assertion_id"]
        for line in report["lines"]
    )
    body["confirmation_state"] = "confirmed"
    _confirm(env, body, "final-meaning", previous=pending["assertion_id"])
    relation_body["confirmation_state"] = "confirmed"
    _confirm(
        env,
        relation_body,
        "final-relation",
        previous=pending_relation["assertion_id"],
        relation=True,
    )
    confirmed = _report(env, [first, second])
    assert confirmed["net_worth_total"] == {"coefficient": "-50", "scale": 1}
