"""Ordinary-data regressions for committed-record coverage and filesystem delivery."""

from __future__ import annotations

import json
import multiprocessing
import shutil
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from finjuice.pipeline.backup.retention import RetentionPolicy
from finjuice.pipeline.cli.commands.recovery_expected import load_expected_recovery_graph
from finjuice.pipeline.cli.main import app
from finjuice.pipeline.storage.sqlite.backup_coverage import observe_source_commits
from finjuice.pipeline.storage.sqlite.backup_delivery import (
    DeliveryJob,
    delivery_status,
    report_committed_delivery,
    run_backup_delivery,
)
from finjuice.pipeline.storage.sqlite.errors import (
    AuthorityConflictError,
    BackupDeliveryError,
    BackupVerificationError,
)
from finjuice.pipeline.storage.sqlite.inactive_restore import InactiveRestoreSession
from finjuice.pipeline.storage.sqlite.mutations import MutationOutcome, MutationService
from finjuice.pipeline.storage.sqlite.recovery_store import (
    capture_into_store,
    initialize_recovery_store,
    list_recovery_store,
    prune_recovery_store,
    receive_graph_into_store,
    restore_store_copy,
    verify_store_copy,
)
from finjuice.pipeline.storage.sqlite.schema import inspect_repository
from tests.cli.commands.test_typed_json_payload_contracts import _validate_command_schema
from tests.cli.test_sqlite_recovery_bundle import _mutate_and_rebackup, _write_expected
from tests.pipeline.test_recovery_store import _capture, _prepare
from tests.pipeline.test_sqlite_mutations import _request

runner = CliRunner()


def _noop(_context: object) -> MutationOutcome:
    return MutationOutcome(result={"noop": True})


def _revision(paths: object, generation: str) -> int:
    info = inspect_repository(paths.generation(generation).database)
    assert info.dataset_revision is not None
    return info.dataset_revision


def _job(tmp_path: Path, source, expected, sender: Path, destination: Path) -> DeliveryJob:
    return DeliveryJob(
        source.data_dir,
        expected,
        source.evidence_provider,
        sender,
        destination,
        tmp_path / "delivery-control",
        source,
    )


def _stores(tmp_path: Path, expected):
    sender = tmp_path / "sender-store"
    destination = tmp_path / "destination-store"
    initialize_recovery_store(sender, expected)
    initialize_recovery_store(destination, expected)
    return sender, destination


def test_mutation_transfer_oserror_preserves_committed_receipt(tmp_path: Path) -> None:
    source, expected, _store, paths, generation, *_ = _prepare(tmp_path)
    sender, destination = _stores(tmp_path, expected)
    _capture(sender, source, expected)
    service = MutationService(paths, expected.activation_evidence)
    revision = _revision(paths, generation)
    receipt = service.execute(_request(generation, "deliver-mut", revision), _noop)
    job = replace(_job(tmp_path, source, expected, sender, destination), recording=receipt)
    with patch(
        "finjuice.pipeline.storage.sqlite.recovery_store.copy_regular_file",
        side_effect=OSError("Synthetic ENOSPC"),
    ):
        with pytest.raises(BackupDeliveryError) as raised:
            run_backup_delivery(job)
    payload = raised.value.report
    assert payload["recording"]["status"] == "committed"
    assert payload["recording"]["changeset_id"] == receipt.changeset_id
    assert payload["recording"]["replayed"] is False
    assert payload["backup"]["destination"] == "transfer_failed"
    replay = service.execute(
        _request(generation, "deliver-mut", revision),
        lambda context: pytest.fail("replay called handler"),
    )
    assert replay.replayed is True
    assert replay.changeset_id == receipt.changeset_id
    status = report_committed_delivery(job)
    assert status.recording is not None
    assert status.recording["status"] == "committed"
    expected_path = _write_expected(tmp_path / "enrolled.json", expected)
    cli = runner.invoke(
        app,
        [
            "--data-dir",
            str(tmp_path / "active"),
            "ssot",
            "backup",
            "deliver",
            "status",
            "--source-data-dir",
            str(source.data_dir),
            "--expected",
            str(expected_path),
            "--sender-store",
            str(sender),
            "--destination-store",
            str(destination),
            "--control-dir",
            str(job.control_dir),
            "--json",
        ],
    )
    assert cli.exit_code == 0, cli.output
    body = json_payload(cli.output)
    _validate_command_schema(
        body,
        command="ssot backup deliver status",
        schema_file="ssot_backup_deliver_status.schema.json",
    )
    assert "committed" in cli.output or body["backup"]["destination"] == "transfer_failed"


def json_payload(text: str) -> dict:
    return json.loads(text)


def test_noop_same_revision_and_replay_do_not_inflate_pending(tmp_path: Path) -> None:
    source, expected, _store, paths, generation, *_ = _prepare(tmp_path)
    sender, destination = _stores(tmp_path, expected)
    _capture(sender, source, expected)
    before = observe_source_commits(source.data_dir, expected, source.evidence_provider)
    service = MutationService(paths, expected.activation_evidence)
    revision = _revision(paths, generation)
    first = service.execute(_request(generation, "noop-a", revision), _noop)
    after = observe_source_commits(source.data_dir, expected, source.evidence_provider)
    assert first.state_changed is False
    assert after.dataset_revision == before.dataset_revision
    assert after.receipt_count == before.receipt_count + 1
    replay = service.execute(
        _request(generation, "noop-a", revision),
        lambda context: pytest.fail("replay called handler"),
    )
    repeated = observe_source_commits(source.data_dir, expected, source.evidence_provider)
    assert replay.replayed is True
    assert repeated.receipt_count == after.receipt_count
    result = run_backup_delivery(_job(tmp_path, source, expected, sender, destination))
    assert result.local == "covered"
    assert result.destination == "covered"
    assert result.pending_commit_count == 0


def test_faults_resume_from_artifact_facts(tmp_path: Path) -> None:
    source, expected, _store, paths, generation, *_ = _prepare(tmp_path)
    sender, destination = _stores(tmp_path, expected)
    receipt = MutationService(paths, expected.activation_evidence).execute(
        _request(generation, "pre-journal", _revision(paths, generation)), _noop
    )
    job = replace(_job(tmp_path, source, expected, sender, destination), recording=receipt)
    status = report_committed_delivery(job)
    assert status.recording is not None and status.recording["status"] == "committed"
    assert status.local == "pending"
    with patch(
        "finjuice.pipeline.storage.sqlite.backup_delivery._before_journal_write",
        side_effect=RuntimeError("capture-before-journal"),
    ):
        with pytest.raises(BackupDeliveryError):
            run_backup_delivery(job)
    assert list_recovery_store(sender, expected).healthy_count >= 1
    with patch(
        "finjuice.pipeline.storage.sqlite.backup_delivery._after_destination_publish",
        side_effect=RuntimeError("published-before-ack"),
    ):
        with pytest.raises(BackupDeliveryError):
            run_backup_delivery(job)
    assert list_recovery_store(destination, expected).healthy_count == 1
    resumed = run_backup_delivery(job)
    assert resumed.destination == "covered"
    assert resumed.last_verified_at is not None


def test_commit_during_transfer_keeps_selected_success_and_new_pending(tmp_path: Path) -> None:
    source, expected, _store, paths, generation, *_ = _prepare(tmp_path)
    sender, destination = _stores(tmp_path, expected)
    _capture(sender, source, expected)
    job = _job(tmp_path, source, expected, sender, destination)
    from finjuice.pipeline.storage.sqlite import recovery_store as store_mod

    original = store_mod._after_graph_file_copied

    def mutate_once() -> None:
        store_mod._after_graph_file_copied = original
        MutationService(paths, expected.activation_evidence).execute(
            _request(generation, "during-copy", _revision(paths, generation)), _noop
        )

    with patch.object(store_mod, "_after_graph_file_copied", mutate_once):
        result = run_backup_delivery(job)
    assert result.last_verified_at is not None
    assert result.pending_commit_count >= 1


def test_destination_restore_mutate_rebackup(tmp_path: Path) -> None:
    source, expected, _store, _paths, _generation, transactions, _account = _prepare(tmp_path)
    sender, destination = _stores(tmp_path, expected)
    captured = _capture(sender, source, expected)
    result = run_backup_delivery(_job(tmp_path, source, expected, sender, destination))
    assert result.destination == "covered"
    dest_list = list_recovery_store(destination, expected)
    assert dest_list.latest_healthy_id is not None
    _verified, restored = restore_store_copy(
        destination, expected, dest_list.latest_healthy_id, tmp_path / "workspace"
    )
    _mutate_and_rebackup(restored, transactions, tmp_path / "rebackup")
    verify_store_copy(sender, expected, captured.copy_id)
    with InactiveRestoreSession(restored):
        pass


def test_conflict_and_registration_failure_preserve_source(tmp_path: Path) -> None:
    source, expected, _store, paths, generation, *_ = _prepare(tmp_path)
    sender, destination = _stores(tmp_path, expected)
    first = _capture(sender, source, expected)
    verified = verify_store_copy(sender, expected, first.copy_id)
    receive_graph_into_store(
        destination, sender / "bundles" / first.copy_id, expected, expected_graph=verified
    )
    healthy_before = list_recovery_store(destination, expected).healthy_count
    wrong = replace(verified, graph_digest="0" * 64)
    with pytest.raises(BackupVerificationError):
        receive_graph_into_store(
            destination, sender / "bundles" / first.copy_id, expected, expected_graph=wrong
        )
    assert list_recovery_store(destination, expected).healthy_count == healthy_before
    broken = tmp_path / "broken-dest"
    initialize_recovery_store(broken, expected)
    (broken / ".finjuice-recovery-store" / "capture-started").write_bytes(b"1\n")
    with pytest.raises(BackupVerificationError):
        receive_graph_into_store(
            broken, sender / "bundles" / first.copy_id, expected, expected_graph=verified
        )
    MutationService(paths, expected.activation_evidence).execute(
        _request(generation, "after-conflict", _revision(paths, generation)), _noop
    )
    staging = destination / "bundles" / ".recv-notadopted"
    staging.mkdir()
    (staging / "junk").write_text("no", encoding="utf-8")
    inventory = list_recovery_store(destination, expected)
    assert all(item.copy_id != ".recv-notadopted" for item in inventory.copies)


def _transfer_pause(packed: str, ready: object, release: object) -> None:
    from finjuice.pipeline.storage.sqlite import recovery_store as store_mod
    from finjuice.pipeline.storage.sqlite.backup_delivery import DeliveryJob, run_backup_delivery
    from tests.cli.test_sqlite_recovery_bundle import _write_expected
    from tests.pipeline.test_recovery_bundle import _live

    root = Path(packed)
    source, expected, *_ = _live(root / "live")
    _write_expected(root / "enrolled.json", expected)
    sender = root / "sender"
    destination = root / "destination"
    initialize_recovery_store(sender, expected)
    initialize_recovery_store(destination, expected)
    capture_into_store(sender, source, expected)
    original = store_mod._after_graph_file_copied

    def paused() -> None:
        ready.set()  # type: ignore[attr-defined]
        assert release.wait(30)  # type: ignore[attr-defined]
        original()

    job = DeliveryJob(
        source.data_dir,
        expected,
        source.evidence_provider,
        sender,
        destination,
        root / "control",
        source,
    )
    with patch.object(store_mod, "_after_graph_file_copied", paused):
        run_backup_delivery(job)


def test_transfer_shared_lease_blocks_prune(tmp_path: Path) -> None:
    root = tmp_path / "pause-root"
    root.mkdir()
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    release = context.Event()
    process = context.Process(target=_transfer_pause, args=(str(root), ready, release))
    process.start()
    if not ready.wait(60):
        process.kill()
        process.join(5)
        pytest.fail("Child did not reach the transfer pause")
    try:
        expected = load_expected_recovery_graph(root / "enrolled.json")
        with pytest.raises(AuthorityConflictError, match="timed out"):
            prune_recovery_store(root / "sender", expected, timeout_ms=80)
    finally:
        release.set()
        process.join(30)
        if process.is_alive():
            process.kill()
            process.join(5)
    assert process.exitcode == 0
    expected = load_expected_recovery_graph(root / "enrolled.json")
    prune_recovery_store(root / "sender", expected, timeout_ms=2_000)


def test_prior_success_newest_failure_and_lost_journal(tmp_path: Path) -> None:
    source, expected, _store, paths, generation, *_ = _prepare(tmp_path)
    sender, destination = _stores(tmp_path, expected)
    _capture(sender, source, expected)
    job = _job(tmp_path, source, expected, sender, destination)
    first = run_backup_delivery(job)
    assert first.destination == "covered"
    MutationService(paths, expected.activation_evidence).execute(
        _request(generation, "newest-fail", _revision(paths, generation)), _noop
    )
    with patch(
        "finjuice.pipeline.storage.sqlite.recovery_store.copy_regular_file",
        side_effect=OSError("newest failure"),
    ):
        with pytest.raises(BackupDeliveryError) as raised:
            run_backup_delivery(job)
    payload = raised.value.report
    assert payload["last_verified_at"] == first.last_verified_at
    assert payload["last_attempt_error_code"] == "copy_failed"
    shutil.rmtree(job.control_dir)
    lost = delivery_status(job)
    assert lost.history_unknown is True
    assert lost.last_verified_at is None


def test_same_revision_noop_same_second_retention(tmp_path: Path) -> None:
    source, expected, _store, paths, generation, *_ = _prepare(tmp_path)
    store = tmp_path / "retention-store"
    initialize_recovery_store(store, expected)
    identities = [f"{number:08x}-bbbb-4ccc-8ddd-eeeeeeeeeeee" for number in (9, 1)]
    with (
        patch("finjuice.pipeline.storage.sqlite.backup.datetime") as clock,
        patch(
            "finjuice.pipeline.storage.sqlite.recovery_store._fresh_copy_id",
            side_effect=identities,
        ),
    ):
        clock.now.return_value = datetime(2026, 9, 14, tzinfo=timezone.utc)
        first = capture_into_store(store, source, expected)
        MutationService(paths, expected.activation_evidence).execute(
            _request(generation, "same-rev-noop", _revision(paths, generation)), _noop
        )
        second = capture_into_store(store, source, expected)
    inventory = list_recovery_store(store, expected)
    assert inventory.latest_healthy_id == second.copy_id
    assert first.copy_id != second.copy_id
    pruned = prune_recovery_store(store, expected, RetentionPolicy(0, 0, 0))
    assert second.copy_id not in pruned.deleted_ids
    remaining = {item.copy_id for item in list_recovery_store(store, expected).copies}
    assert second.copy_id in remaining


def test_pending_counts_commits_across_keyset_pages(tmp_path: Path) -> None:
    source, expected, _store, paths, generation, *_ = _prepare(tmp_path)
    sender, destination = _stores(tmp_path, expected)
    job = _job(tmp_path, source, expected, sender, destination)
    run_backup_delivery(job)
    before = observe_source_commits(source.data_dir, expected, source.evidence_provider)
    service = MutationService(paths, expected.activation_evidence)
    for index in range(257):
        service.execute(_request(generation, f"page-{index}", before.dataset_revision), _noop)
    after = observe_source_commits(source.data_dir, expected, source.evidence_provider)
    assert after.receipt_count == before.receipt_count + 257
    assert delivery_status(job).pending_commit_count == 257
    _capture(sender, source, expected)
    assert delivery_status(job).pending_commit_count == 257
    assert run_backup_delivery(job).pending_commit_count == 0


def test_pending_union_and_unknown_are_distinct() -> None:
    from finjuice.pipeline.storage.sqlite.backup_coverage import CoverageComparison
    from finjuice.pipeline.storage.sqlite.backup_delivery import _pending_count

    left = CoverageComparison("pending", 1, 1, 1, None, None, None, "now", frozenset({"a"}))
    right = replace(left, missing_commits=frozenset({"b"}))
    assert _pending_count(left, right) == 2
    assert _pending_count(left, replace(right, status="unknown", missing_commits=None)) is None


@pytest.mark.parametrize("json_output", [False, True])
def test_actual_tag_commit_keeps_success_on_transfer_failure(
    tmp_path: Path, json_output: bool
) -> None:
    source, expected, _store, paths, generation, *_ = _prepare(tmp_path)
    from finjuice.pipeline.storage.sqlite import ExactValue, TransactionRecord, new_entity_id
    from finjuice.pipeline.storage.sqlite.repository import RepositoryReader

    with RepositoryReader(paths.generation(generation).database) as reader:
        observation = reader.rows("observations")[0]
        provenance = next(
            row
            for row in reader.rows("record_provenance")
            if row["source_occurrence_id"] == observation["source_occurrence_id"]
        )
        account = reader.rows("accounts")[0]["entity_id"]
    transaction_id, amount_id = new_entity_id(), new_entity_id()

    def seed(context):
        context.add_exact_value(
            amount_id,
            ExactValue.from_lexical("10", value_kind="money", currency="KRW"),
            provenance_id=provenance["provenance_id"],
        )
        context.add_transaction(
            TransactionRecord(
                transaction_id,
                observation["entity_id"],
                provenance["provenance_id"],
                account,
                amount_id,
                "2026-09-14",
                "12:00:00",
                "2026-09-14T12:00:00",
                "expense",
                "expense",
                "synthetic",
            )
        )
        return MutationOutcome(result={"seeded": True})

    MutationService(paths, expected.activation_evidence).execute(
        _request(generation, "cli-transaction-seed", _revision(paths, generation)), seed
    )
    sender, destination = _stores(tmp_path, expected)
    expected_path = _write_expected(tmp_path / "expected.json", expected)
    config_path = tmp_path / "delivery.json"
    config_path.write_text(
        json.dumps(
            {
                "expected": str(expected_path),
                "sender_store": str(sender),
                "destination_store": str(destination),
                "control_dir": str(tmp_path / "control"),
                "wheel": str(source.release_paths.wheel),
                "dependency_lock": str(source.release_paths.dependency_lock),
                "binding": str(source.release_paths.binding),
                "migration_candidate": str(source.migration_candidate),
            }
        )
    )
    arguments = [
        "--data-dir",
        str(source.data_dir),
        "tag",
        "--edit",
        transaction_id,
        "--add-tag",
        "delivery-test",
        "--idempotency-key",
        "cli-delivery",
        "--expected-generation",
        generation,
        "--expected-revision",
        str(_revision(paths, generation)),
        "--delivery-config",
        str(config_path),
    ]
    if json_output:
        arguments.append("--json")
    with patch(
        "finjuice.pipeline.storage.sqlite.recovery_store.copy_regular_file",
        side_effect=OSError("Synthetic transfer failure"),
    ) as failed_copy:
        result = runner.invoke(
            app, arguments, obj={"activation_evidence_provider": source.evidence_provider}
        )
    assert result.exit_code == 0, result.output
    failed_copy.assert_called()
    if json_output:
        payload = json.loads(result.output)
        assert payload["backup_delivery"]["recording"]["status"] == "committed"
        assert payload["backup_delivery"]["backup"]["destination"] == "transfer_failed"
        _validate_command_schema(payload, command="tag", schema_file="tag.schema.json")
    else:
        assert "기록은 저장되었습니다" in result.output
        assert "전송은 대기 중" in result.output
    before = observe_source_commits(source.data_dir, expected, source.evidence_provider)
    retried = runner.invoke(
        app, arguments, obj={"activation_evidence_provider": source.evidence_provider}
    )
    assert retried.exit_code == 0, retried.output
    after = observe_source_commits(source.data_dir, expected, source.evidence_provider)
    assert after.receipt_count == before.receipt_count
    if json_output:
        payload = json.loads(retried.output)
        assert payload["replayed"] is True
        assert payload["backup_delivery"]["backup"]["destination"] == "covered"


def test_actual_tag_commit_preserved_when_observation_fails(tmp_path: Path) -> None:
    from finjuice.pipeline.cli.post_commit_delivery import execute_after_commit

    source, expected, _store, paths, generation, *_ = _prepare(tmp_path)
    sender, destination = _stores(tmp_path, expected)
    receipt = MutationService(paths, expected.activation_evidence).execute(
        _request(generation, "observed-failure", _revision(paths, generation)), _noop
    )
    with patch(
        "finjuice.pipeline.storage.sqlite.backup_delivery.observe_source_commits",
        side_effect=BackupVerificationError("Synthetic unavailable observation"),
    ):
        report = execute_after_commit(
            _job(tmp_path, source, expected, sender, destination), receipt
        )
    assert report["recording"]["status"] == "committed"
    assert report["pending_commit_count"] is None
    assert report["source_observed_revision"] is None
    assert report["backup"] == {"local": "unknown", "destination": "unknown"}
