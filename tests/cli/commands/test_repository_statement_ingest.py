"""JSON statement files use the common ingest path on an active repository."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from finjuice.pipeline.cli.output import ExitCode
from finjuice.pipeline.statements.canonical import STATEMENT_ACCOUNT_NAMESPACE
from finjuice.pipeline.storage.mutation_facade import MutationIdentity
from finjuice.pipeline.storage.sqlite import AccountRecord, RepositoryReader, new_entity_id
from finjuice.pipeline.storage.sqlite.account_bindings import AccountBindingConfirmation
from finjuice.pipeline.storage.sqlite.mutations import MutationOutcome, MutationService
from finjuice.pipeline.storage.sqlite.schema import inspect_repository
from tests.cli.commands.test_repository_bulk_commands import _invoke
from tests.cli.commands.test_repository_mutation_fences import _ActiveRoot, _authority_state
from tests.cli.commands.test_repository_mutation_fences import active_root as _active_root_fixture
from tests.pipeline.test_canonical_statement_json import ACCOUNT_KEY, _envelope, _record
from tests.pipeline.test_sqlite_mutations import _request

active_root = _active_root_fixture


def _payload(result: Any) -> dict[str, Any]:
    assert result.exit_code == ExitCode.SUCCESS, result.output
    body: dict[str, Any] = json.loads(result.output[result.output.index("{") :])
    return body


def _stage(active: _ActiveRoot, name: str, envelope: dict[str, Any]) -> Path:
    path = active.root / "imports" / name
    path.write_text(json.dumps(envelope, ensure_ascii=False), encoding="utf-8")
    return path


def _revision(active: _ActiveRoot) -> int:
    revision = inspect_repository(active.database).dataset_revision
    assert revision is not None
    return revision


def _bind(active: _ActiveRoot) -> str:
    account_id = new_entity_id()

    def seed(context: Any) -> MutationOutcome:
        context.add_account(AccountRecord(account_id, account_kind="bank.v1"))
        return MutationOutcome(result={"account": account_id})

    MutationService(active.paths, active.evidence).execute(
        _request(active.generation, "statement-account", _revision(active)), seed
    )
    active.facade.confirm_account_binding(
        AccountBindingConfirmation(
            source_namespace=STATEMENT_ACCOUNT_NAMESPACE,
            external_key=ACCOUNT_KEY,
            account_id=account_id,
            evidence={"reason": "operator confirmed synthetic statement account"},
        ),
        identity=MutationIdentity("bind-account", active.generation, _revision(active)),
    )
    return account_id


def _transactions(active: _ActiveRoot) -> list[dict[str, Any]]:
    with RepositoryReader(active.database) as reader:
        return list(reader.rows("transactions"))


@pytest.mark.parametrize("coverage", ["full", "partial", "historical"])
def test_ingest_json_statement_full_partial_historical_and_retry(
    active_root: _ActiveRoot, coverage: str
) -> None:
    _bind(active_root)
    staged = _stage(
        active_root,
        f"{coverage}.json",
        _envelope([_record("txn-1", decision={"action": "create"})], coverage=coverage),
    )
    original = staged.read_bytes()

    first = _payload(_invoke(active_root, "ingest", "--json"))
    receipt = first["receipts"][0]
    assert receipt["filename"] == staged.name
    assert receipt["result"]["counts"]["created"] == 1
    assert receipt["result"]["counts"]["transactions"]["inserted"] == 1
    assert first["summary"]["new_transactions"] == 1
    assert receipt["result"]["noop"] is False
    created = _transactions(active_root)
    assert len(created) == 1

    revision = _revision(active_root)
    retry = _payload(_invoke(active_root, "ingest", "--json"))
    assert retry["receipts"][0]["result"]["counts"]["created"] == 0
    assert retry["receipts"][0]["result"]["counts"]["reused"] == 1
    assert retry["summary"]["new_transactions"] == 0
    assert retry["summary"]["updated"] == 1
    assert _revision(active_root) == revision
    assert retry["receipts"][0]["state_changed"] is False
    assert retry["receipts"][0]["result"]["occurrence_id"] == receipt["result"]["occurrence_id"]
    assert staged.read_bytes() == original
    assert len(_transactions(active_root)) == 1
    dumped = json.dumps(retry)
    assert "-1200.50" not in dumped
    assert ACCOUNT_KEY not in dumped
    assert str(staged) not in dumped


def test_second_source_preserves_evidence_without_duplicating(
    active_root: _ActiveRoot,
) -> None:
    _bind(active_root)
    _stage(
        active_root,
        "first.json",
        _envelope([_record("txn-1", decision={"action": "create"})]),
    )
    created = _payload(_invoke(active_root, "ingest", "--json"))
    assert created["summary"]["new_transactions"] == 1
    transaction_id = _transactions(active_root)[0]["entity_id"]

    (active_root.root / "imports" / "first.json").unlink()
    _stage(
        active_root,
        "card.json",
        _envelope(
            [_record("card-9", decision={"action": "link", "transaction_id": transaction_id})],
            source_identity="card.synthetic.statement.v1",
            idempotency_key="producer-batch-2",
        ),
    )
    linked = _payload(_invoke(active_root, "ingest", "--json"))
    assert linked["receipts"][0]["result"]["counts"]["linked"] == 1
    assert linked["receipts"][0]["result"]["counts"]["created"] == 0
    assert linked["summary"]["new_transactions"] == 0
    assert len(_transactions(active_root)) == 1
    with RepositoryReader(active_root.database) as reader:
        evidence = reader.statement_evidence(source_identity="card.synthetic.statement.v1")
    assert evidence["records"][0]["transaction_id"] == transaction_id


def test_collection_failure_is_retryable_and_preserves_manual_correction(
    active_root: _ActiveRoot,
) -> None:
    _bind(active_root)
    _stage(
        active_root,
        "ok.json",
        _envelope([_record("txn-1", decision={"action": "create"})]),
    )
    first = _payload(_invoke(active_root, "ingest", "--json"))
    assert first["summary"]["new_transactions"] == 1
    transaction_id = _transactions(active_root)[0]["entity_id"]
    active_root.facade.edit_manual_transaction(
        _manual_edit(transaction_id),
        identity=MutationIdentity("manual-1", active_root.generation, _revision(active_root)),
    )
    (active_root.root / "imports" / "ok.json").unlink()
    broken = _stage(
        active_root,
        "broken.json",
        _envelope(
            [
                _record("txn-1", decision={"action": "create"}),
                _record("txn-2", amount=-500.25, decision={"action": "create"}),
            ]
        ),
    )
    revision = _revision(active_root)
    tags = _manual_tags(active_root, transaction_id)

    failed = _invoke(active_root, "ingest", "--json")
    assert failed.exit_code != ExitCode.SUCCESS
    assert "must-never-be-stored" not in failed.output
    assert _revision(active_root) == revision
    assert _manual_tags(active_root, transaction_id) == tags

    broken.write_text(
        json.dumps(
            _envelope(
                [
                    _record("txn-1", decision={"action": "create"}),
                    _record("txn-2", decision={"action": "create"}),
                ]
            ),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    repaired = _payload(_invoke(active_root, "ingest", "--json"))
    assert repaired["summary"]["new_transactions"] == 1
    assert repaired["receipts"][0]["result"]["counts"]["reused"] == 1
    assert _manual_tags(active_root, transaction_id) == ["검토완료"]
    assert len(_transactions(active_root)) == 2


def test_credentials_and_unrelated_json_stay_out_of_the_ingest_path(
    active_root: _ActiveRoot,
) -> None:
    _bind(active_root)
    secret = _stage(
        active_root,
        "secret.json",
        _envelope([_record("txn-1", api_key="must-never-be-stored")]),
    )
    noise = active_root.root / "imports" / "notes.json"
    noise.write_text('{"hello": "world"}', encoding="utf-8")
    revision = _revision(active_root)

    failed = _invoke(active_root, "ingest", "--json")
    assert failed.exit_code != ExitCode.SUCCESS
    assert "must-never-be-stored" not in failed.output
    assert "api_key" not in failed.output
    assert _revision(active_root) == revision
    assert _transactions(active_root) == []
    assert secret.exists()

    secret.unlink()
    skipped = _payload(_invoke(active_root, "ingest", "--json"))
    assert skipped["receipts"] == []
    assert skipped["summary"]["files_processed"] == 0
    assert _transactions(active_root) == []
    assert noise.exists()


def test_ingest_processes_xlsx_and_json_together(active_root: _ActiveRoot) -> None:
    from tests.cli.commands.test_repository_import_commands import _write_xlsx

    _bind(active_root)
    _write_xlsx(active_root.root / "imports" / "book.xlsx")
    _stage(
        active_root,
        "statement.json",
        _envelope([_record("txn-1", decision={"action": "create"})]),
    )

    result = _payload(_invoke(active_root, "ingest", "--json"))
    names = [item["filename"] for item in result["receipts"]]
    assert names == ["statement.json", "book.xlsx"]
    assert result["summary"]["files_processed"] == 2
    assert result["summary"]["new_transactions"] >= 2
    assert len(_transactions(active_root)) >= 2


def test_dry_run_validates_without_writing(active_root: _ActiveRoot) -> None:
    _bind(active_root)
    _stage(
        active_root,
        "preview.json",
        _envelope([_record("txn-1", decision={"action": "create"})]),
    )
    before = _authority_state(active_root)

    preview = _payload(_invoke(active_root, "ingest", "--dry-run", "--json"))
    assert preview["dry_run"] is True
    assert preview["history_skipped"] == 0
    assert preview["would_parse"] == 1
    assert preview["receipts"][0]["state_changed"] is False
    assert preview["receipts"][0]["result"]["noop"] is False
    assert preview["receipts"][0]["result"]["completed"] is False
    assert preview["receipts"][0]["result"]["counts"]["created"] == 1
    assert preview["receipts"][0]["result"]["counts"]["pending"] == 0
    assert preview["receipts"][0]["result"]["counts"]["transactions"]["inserted"] == 1
    assert preview["summary"]["new_transactions"] == 1
    assert _authority_state(active_root) == before
    assert _transactions(active_root) == []


def test_dry_run_new_pending_file_is_not_history_skipped(active_root: _ActiveRoot) -> None:
    _stage(
        active_root,
        "pending.json",
        _envelope([_record("txn-1", decision={"action": "create"})]),
    )
    before = _authority_state(active_root)

    preview = _payload(_invoke(active_root, "ingest", "--dry-run", "--json"))
    assert preview["history_skipped"] == 0
    assert preview["would_parse"] == 1
    assert preview["receipts"][0]["result"]["noop"] is False
    assert preview["receipts"][0]["result"]["counts"]["pending"] == 1
    assert preview["receipts"][0]["result"]["counts"]["transactions"]["inserted"] == 0
    assert _authority_state(active_root) == before
    assert _transactions(active_root) == []


def test_dry_run_already_ingested_identical_json_is_history_skipped(
    active_root: _ActiveRoot,
) -> None:
    _bind(active_root)
    _stage(
        active_root,
        "applied.json",
        _envelope([_record("txn-1", decision={"action": "create"})]),
    )
    applied = _payload(_invoke(active_root, "ingest", "--json"))
    occurrence_id = applied["receipts"][0]["result"]["occurrence_id"]
    before = _authority_state(active_root)

    preview = _payload(_invoke(active_root, "ingest", "--dry-run", "--json"))

    assert preview["dry_run"] is True
    assert preview["history_skipped"] == 1
    assert preview["would_parse"] == 0
    assert preview["receipts"][0]["state_changed"] is False
    assert preview["receipts"][0]["result"]["noop"] is True
    assert preview["receipts"][0]["result"]["completed"] is False
    assert preview["receipts"][0]["result"]["occurrence_id"] == occurrence_id
    assert preview["receipts"][0]["result"]["counts"]["created"] == 0
    assert preview["receipts"][0]["result"]["counts"]["transactions"]["inserted"] == 0
    assert preview["summary"]["new_transactions"] == 0
    assert _authority_state(active_root) == before


def test_dry_run_already_ingested_pending_json_is_history_skipped(
    active_root: _ActiveRoot,
) -> None:
    _stage(
        active_root,
        "pending.json",
        _envelope([_record("txn-1", decision={"action": "create"})]),
    )
    _payload(_invoke(active_root, "ingest", "--json"))
    before = _authority_state(active_root)

    preview = _payload(_invoke(active_root, "ingest", "--dry-run", "--json"))

    assert preview["history_skipped"] == 1
    assert preview["would_parse"] == 0
    assert preview["receipts"][0]["result"]["counts"]["pending"] == 1
    assert preview["receipts"][0]["result"]["counts"]["reused"] == 0
    assert preview["summary"]["updated"] == 0
    assert preview["receipts"][0]["result"]["noop"] is True
    assert preview["receipts"][0]["result"]["completed"] is False
    assert _authority_state(active_root) == before


def test_dry_run_rejects_missing_link_target_without_writing(active_root: _ActiveRoot) -> None:
    _bind(active_root)
    _stage(
        active_root,
        "broken-link.json",
        _envelope(
            [_record("txn-1", decision={"action": "link", "transaction_id": new_entity_id()})]
        ),
    )
    before = _authority_state(active_root)

    preview = _invoke(active_root, "ingest", "--dry-run", "--json")
    assert preview.exit_code == ExitCode.USAGE_ERROR, preview.output
    assert "must-never-be-stored" not in preview.output
    assert _authority_state(active_root) == before
    assert _transactions(active_root) == []

    write = _invoke(active_root, "ingest", "--json")
    assert write.exit_code == ExitCode.USAGE_ERROR, write.output
    assert _authority_state(active_root) == before
    assert _transactions(active_root) == []


def test_dry_run_rejects_stale_revision_without_writing(active_root: _ActiveRoot) -> None:
    _bind(active_root)
    _stage(
        active_root,
        "stale.json",
        _envelope([_record("txn-1", decision={"action": "create"})]),
    )
    before = _authority_state(active_root)

    result = _invoke(active_root, "ingest", "--dry-run", "--json", "--expected-revision", "0")

    assert result.exit_code == ExitCode.VALIDATION_ERROR, result.output
    payload = json.loads(result.output)
    assert payload["error"]["code"] == "VALIDATION_FAILED"
    assert payload["_meta"]["pipeline"]["error_type"] == "MutationConflictError"
    assert payload["_meta"]["pipeline"]["steps"]["ingest"]["receipts"] == []
    assert _authority_state(active_root) == before
    assert _transactions(active_root) == []


def _manual_edit(transaction_id: str) -> Any:
    from finjuice.pipeline.storage.sqlite.mutations import ManualTransactionEdit

    return ManualTransactionEdit(identifier=transaction_id, add_tags=("검토완료",))


def _manual_tags(active: _ActiveRoot, transaction_id: str) -> list[str]:
    with RepositoryReader(active.database) as reader:
        row = next(
            item for item in reader.rows("transactions") if item["entity_id"] == transaction_id
        )
    return json.loads(row["tags_manual_json"])


@pytest.mark.parametrize(
    ("second_amount", "second_coverage"),
    [("-1200.50", "full"), ("-1200.50", "partial"), ("-999.00", "partial")],
)
def test_batch_preview_matches_overlapping_statement_writes(
    active_root: _ActiveRoot, second_amount: str, second_coverage: str
) -> None:
    _bind(active_root)
    for name, amount in [("a.json", "-1200.50"), ("b.json", second_amount)]:
        _stage(
            active_root,
            name,
            _envelope(
                [_record("shared-id", amount=amount, decision={"action": "create"})],
                coverage="full" if name == "a.json" else second_coverage,
            ),
        )
    before = _authority_state(active_root)

    preview = _invoke(active_root, "ingest", "--dry-run", "--json")
    assert _authority_state(active_root) == before
    assert _transactions(active_root) == []
    write = _invoke(active_root, "ingest", "--json")

    assert preview.exit_code == write.exit_code
    if second_amount == "-1200.50":
        planned = _payload(preview)
        applied = _payload(write)
        assert planned["summary"] == applied["summary"]
        assert planned["summary"]["new_transactions"] == 1
        assert planned["summary"]["updated"] == 1
        assert planned["receipts"][1]["result"]["counts"]["reused"] == 1
        assert len(_transactions(active_root)) == 1
    else:
        assert preview.exit_code != ExitCode.SUCCESS
        planned = json.loads(preview.output)["_meta"]["pipeline"]["steps"]["ingest"]
        applied = json.loads(write.output)["_meta"]["pipeline"]["steps"]["ingest"]
        assert planned["summary"] == applied["summary"]
        assert planned["summary"]["failed_files"] == [["b.json", "MutationConflictError"]]
        assert len(_transactions(active_root)) == 1


def test_ingest_uses_current_import_time_and_preserves_collected_time(
    active_root: _ActiveRoot,
) -> None:
    _bind(active_root)
    collected_at = "2001-01-01T00:00:00Z"
    _stage(
        active_root,
        "historical.json",
        _envelope(
            [_record("txn-1", decision={"action": "create"})],
            coverage="historical",
            collected_at=collected_at,
        ),
    )
    started = datetime.now(timezone.utc)
    revision = _revision(active_root)
    identity_args = (
        "--idempotency-key",
        "import-historical",
        "--expected-generation",
        active_root.generation,
        "--expected-revision",
        str(revision),
    )
    first = _payload(_invoke(active_root, "ingest", "--json", *identity_args))
    with sqlite3.connect(active_root.database) as connection:
        imported_at = connection.execute(
            "SELECT imported_at FROM source_occurrences WHERE occurrence_kind = ?",
            ("canonical_json_statement",),
        ).fetchone()[0]
        observed_collection = connection.execute(
            "SELECT collected_at FROM observations"
        ).fetchone()[0]
    assert started <= datetime.fromisoformat(imported_at) <= datetime.now(timezone.utc)
    assert observed_collection == collected_at
    revision = _revision(active_root)

    replay = _payload(_invoke(active_root, "ingest", "--json", *identity_args))
    replay_result = replay["receipts"][0]["result"]
    assert replay_result["noop"] is True
    assert replay_result["counts"]["created"] == 0
    assert replay_result["counts"]["linked"] == 0
    assert replay_result["counts"]["reused"] == 1
    assert replay_result["counts"]["pending"] == 0
    assert replay["summary"]["new_transactions"] == 0
    assert replay["summary"]["updated"] == 1
    assert replay_result["occurrence_id"] == first["receipts"][0]["result"]["occurrence_id"]
    assert _revision(active_root) == revision
    with sqlite3.connect(active_root.database) as connection:
        stored = json.loads(
            connection.execute(
                "SELECT result_json FROM idempotency_requests WHERE idempotency_key = ?",
                ("import-historical",),
            ).fetchone()[0]
        )
    assert stored["result"]["counts"]["created"] == 1
    assert stored["result"]["counts"]["reused"] == 0
    assert stored["result"]["noop"] is False


def test_pending_staged_statement_becomes_actionable_after_binding(
    active_root: _ActiveRoot,
) -> None:
    _stage(
        active_root,
        "pending.json",
        _envelope(
            [_record("txn-1", decision={"action": "create"})],
        ),
    )
    first = _payload(_invoke(active_root, "ingest", "--json"))
    assert first["receipts"][0]["result"]["counts"]["pending"] == 1
    _bind(active_root)
    before = _authority_state(active_root)

    preview = _payload(_invoke(active_root, "ingest", "--dry-run", "--json"))
    assert preview["history_skipped"] == 0
    assert preview["summary"]["new_transactions"] == 1
    assert _authority_state(active_root) == before
    applied = _payload(_invoke(active_root, "ingest", "--json"))
    assert applied["summary"]["new_transactions"] == 1
    assert len(_transactions(active_root)) == 1


@pytest.mark.parametrize("confirmed", [False, True])
@pytest.mark.parametrize("second_coverage", ["full", "partial"])
def test_history_counts_match_new_pending_and_duplicate_evidence(
    active_root: _ActiveRoot, confirmed: bool, second_coverage: str
) -> None:
    if confirmed:
        _bind(active_root)
    for name, coverage in [("a.json", "full"), ("b.json", second_coverage)]:
        _stage(
            active_root,
            name,
            _envelope(
                [_record("same-id", decision={"action": "create"})],
                coverage=coverage,
            ),
        )
    before = _authority_state(active_root)
    preview = _payload(_invoke(active_root, "ingest", "--dry-run", "--json"))
    assert _authority_state(active_root) == before
    written = _payload(_invoke(active_root, "ingest", "--only-unprocessed", "--json"))

    expected_skipped = 1 if second_coverage == "full" else 0
    for result in (preview, written):
        assert result["history_skipped"] == expected_skipped
        assert result["would_parse"] == 2 - expected_skipped
        assert result["summary"]["pending"] == (0 if confirmed else 2)
        assert result["receipts"][0]["result"]["noop"] is False
    with sqlite3.connect(active_root.database) as connection:
        count = connection.execute(
            "SELECT count(*) FROM source_occurrences WHERE occurrence_kind = ?",
            ("canonical_json_statement",),
        ).fetchone()[0]
    assert count == 2 - expected_skipped


@pytest.mark.parametrize("preview", [False, True])
def test_pending_statement_is_visible_in_human_and_json_summary(
    active_root: _ActiveRoot, preview: bool
) -> None:
    _stage(active_root, "pending.json", _envelope([_record("txn-1")]))
    args = ("--dry-run",) if preview else ()
    human = _invoke(active_root, "ingest", *args)
    assert human.exit_code == ExitCode.SUCCESS, human.output
    assert "Pending statement records: 1 (awaiting confirmation)" in human.output
    assert ACCOUNT_KEY not in human.output
    assert "-1200.50" not in human.output
    result = _payload(_invoke(active_root, "ingest", "--json", *args))
    assert result["summary"]["pending"] == 1
    assert result["summary"]["new_transactions"] == 0


def test_replay_presentation_reuses_all_mapped_rows_without_changing_stored_counts() -> None:
    from finjuice.pipeline.cli.repository_import import _present_statement_receipt
    from finjuice.pipeline.storage.sqlite.mutations import MutationReceipt

    original_counts = {"created": 1, "linked": 2, "reused": 3, "pending": 4}
    receipt = MutationReceipt(
        changeset_id="synthetic-changeset",
        base_revision=0,
        committed_revision=1,
        state_changed=True,
        result={"counts": dict(original_counts), "noop": False},
        retained_artifacts=(),
        replayed=True,
    )

    presented = _present_statement_receipt("statement.json", MutationIdentity(), receipt)

    counts = presented["result"]["counts"]
    assert (counts["created"], counts["linked"], counts["reused"], counts["pending"]) == (
        0,
        0,
        6,
        4,
    )
    assert counts["transactions"]["inserted"] == 0
    assert counts["transactions"]["reused"] == 6
    assert receipt.result == {"counts": original_counts, "noop": False}


def test_ingest_uses_the_same_bytes_for_schema_selection_and_apply(
    active_root: _ActiveRoot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from finjuice.pipeline.statements import staged

    _bind(active_root)
    _stage(
        active_root,
        "statement.json",
        _envelope(
            [_record("captured-once", decision={"action": "create"})],
        ),
    )
    reads = []
    original_read = staged.read_regular_bytes

    def capture_once(path: Path, *, max_bytes: int | None = None) -> bytes:
        reads.append(path.name)
        content = original_read(path, max_bytes=max_bytes)
        path.write_bytes(b"now malformed")
        return content

    monkeypatch.setattr(staged, "read_regular_bytes", capture_once)
    result = _payload(_invoke(active_root, "ingest", "--json"))
    assert reads == ["statement.json"]
    assert result["summary"]["new_transactions"] == 1
    assert len(_transactions(active_root)) == 1


def test_active_brief_status_counts_only_claimed_statement_inputs(active_root: _ActiveRoot) -> None:
    from typer.testing import CliRunner

    from finjuice.pipeline.cli.main import app

    _stage(active_root, "statement.json", _envelope([_record("pending")]))
    _stage(active_root, "notes.json", {"kind": "unrelated"})
    before = _authority_state(active_root)
    result = CliRunner().invoke(
        app,
        ["--data-dir", str(active_root.root)],
        obj={"activation_evidence_provider": active_root.provider},
    )
    assert result.exit_code == ExitCode.SUCCESS, result.output
    assert "미처리 파일: 1개" in result.output
    assert _authority_state(active_root) == before


def test_active_brief_status_without_evidence_warns_without_fallback_counts(
    active_root: _ActiveRoot,
) -> None:
    from typer.testing import CliRunner

    from finjuice.pipeline.cli.main import app

    _stage(active_root, "statement.json", _envelope([_record("pending")]))
    before = _authority_state(active_root)
    result = CliRunner().invoke(app, ["--data-dir", str(active_root.root)])
    assert result.exit_code == ExitCode.SUCCESS, result.output
    assert "Repository authority could not be verified; run finjuice doctor" in result.output
    assert "미처리 파일" not in result.output
    assert "CSV" not in result.output
    assert "Traceback" not in result.output
    assert _authority_state(active_root) == before
