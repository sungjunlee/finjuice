"""Close reproduction preserves exact money and authoritative interpretation decisions."""

from decimal import Decimal

from finjuice.pipeline.storage.sqlite import GenerationPaths, RepositoryReader
from finjuice.pipeline.storage.sqlite.backup import create_backup, restore_backup
from finjuice.pipeline.storage.sqlite.mutations import (
    MutationOutcome,
    MutationRequest,
    MutationService,
)
from tests.pipeline.test_account_decisions import _environment
from tests.pipeline.test_canonical_assets import _confirm, _meaning, _own, _source
from tests.pipeline.test_canonical_close import _close_args, _invoke, _payload, _seed


def test_exact_close_regenerates_after_later_transfer_decision_and_restore(tmp_path):
    env = _environment(tmp_path)
    lexical = "123456789012345678901234567890.00000000000000000001"
    _seed(env, [lexical], "exact")
    initial = _payload(_invoke(env, _close_args(env, "before-transfer")))
    assert initial["close"]["totals"]["transactions"]["KRW"]["net"] == lexical
    with RepositoryReader(env.database) as reader:
        transaction = reader.rows("transactions")[0]
    dispatch = env.facade.dispatch()
    request = MutationRequest(
        "synthetic.transfer", "transfer", {}, env.generation, env.revision(), "synthetic"
    )
    MutationService(dispatch.paths, dispatch.evidence).execute(
        request,
        lambda context: MutationOutcome(
            {
                "changed": context.update_transaction_derived_state(
                    transaction["entity_id"],
                    {"is_transfer": True},
                    before={"is_transfer": transaction["is_transfer"]},
                )
            }
        ),
    )
    # The old close regenerates from captured inputs even after live facts change.
    history = _payload(_invoke(env, ["history"]))
    assert history["revisions"][0]["report"] == initial["close"]
    from tests.pipeline.test_canonical_close import _reopen_args

    _payload(_invoke(env, _reopen_args(env, "reopen")))
    after = _payload(_invoke(env, _close_args(env, "after-transfer")))
    assert Decimal(after["close"]["totals"]["transactions"]["KRW"]["net"]) == 0
    assert after["close"]["totals"]["transactions"]["KRW"]["transfer"] == lexical
    backup, restored = tmp_path / "backup", GenerationPaths(tmp_path / "restored")
    create_backup(env.database, backup)
    restore_backup(backup, restored.root)
    with RepositoryReader(restored.database) as reader:
        assert reader.close_history()["revisions"][0]["report"] == initial["close"]


def test_asset_close_uses_confirmed_scope_and_preserves_frozen_meaning(tmp_path):
    env = _environment(tmp_path)
    _own(env)
    complete = _source(env, "2026-07-01", "200", "complete")
    partial = _source(env, "2026-07-02", "900", "partial")
    first = _confirm(env, _meaning(env, complete, "2026-07-01"), "meaning-complete")
    _confirm(env, _meaning(env, partial, "2026-07-02", scope_state="partial"), "meaning-partial")
    args = _close_args(
        env,
        "asset-close",
        **{"--period": "2026-07", "--asset-scope": "transactions_and_asset_snapshots"},
    )
    args.extend(["--valuation-currency", "USD"])
    for party in env.parties:
        args.extend(["--party-id", party])
    for source in (complete, partial):
        args.extend(["--source-id", source["entity_id"]])
    closed = _payload(_invoke(env, args))
    assets = closed["close"]["totals"]["asset_snapshots"]
    assert assets["known_net_worth_subtotal"] == {"coefficient": "2000", "scale": 1}
    assert all(line["source_entity_id"] != partial["entity_id"] for line in assets["lines"])
    _confirm(
        env,
        _meaning(env, complete, "2026-07-01", net_worth_sign=-1),
        "meaning-corrected",
        previous=first["assertion_id"],
    )
    history = _payload(_invoke(env, ["history"]))
    assert history["revisions"][0]["report"]["totals"]["asset_snapshots"] == assets


def test_purchase_evidence_unresolved_is_frozen_in_close(tmp_path):
    from tests.pipeline.test_canonical_reconcile import _item, _submit

    env = _environment(tmp_path)
    _submit(env, [_item("pending-order", "200")])
    closed = _payload(_invoke(env, _close_args(env, "unmatched-close")))
    assert closed["close"]["unresolved"]["reconcile_unmatched"] == 1
    assert closed["close"]["completeness"] == "incomplete"
    history = _payload(_invoke(env, ["history"]))
    assert history["revisions"][0]["report"] == closed["close"]
