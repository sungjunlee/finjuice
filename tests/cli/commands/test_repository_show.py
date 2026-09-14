"""Show preserves partition scope and pinned canonical filters after migration."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from finjuice.pipeline.cli.commands import show_cmd
from finjuice.pipeline.cli.main import app
from finjuice.pipeline.storage.mutation_facade import ConfigDocument, StorageMutationFacade
from tests.cli.commands import test_repository_query as query_fixture
from tests.cli.commands.test_repository_query import QueryRoot


@pytest.fixture
def show_root(tmp_path: Path, monkeypatch) -> QueryRoot:
    create = query_fixture.create_backup

    def with_empty_partition(request):
        path = request.source / "transactions/2026/09/transactions.csv"
        text = path.read_text().replace("2026-09-01", "2026-08-01")
        path.write_text(text)
        empty = request.source / "transactions/2026/10/transactions.csv"
        empty.parent.mkdir(parents=True)
        empty.write_text(text.splitlines()[0] + "\n")
        return create(request)

    monkeypatch.setattr(query_fixture, "create_backup", with_empty_partition)
    return query_fixture.query_root.__wrapped__(tmp_path)


def _show(root: QueryRoot, *args: str, legacy=False, no_filter=False, human=False):
    argv = ["--data-dir", str(root.legacy if legacy else root.root)]
    if no_filter:
        argv.append("--no-filter")
    argv.extend(["show", *args])
    if not human:
        argv.append("--json")
    return CliRunner().invoke(
        app, argv, obj={} if legacy else {"activation_evidence_provider": root.provider}
    )


def test_latest_empty_partition_is_not_replaced_by_latest_transaction(show_root: QueryRoot):
    result = _show(show_root)
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["rows"] == [] and payload["total_matches"] == 0
    assert payload["_meta"]["scope_policy"] == "legacy_partition_scope.v1"
    assert payload["_meta"]["dataset_revision"] == 0
    baseline = _show(show_root, legacy=True)
    assert baseline.exit_code == 0, baseline.output
    assert json.loads(baseline.output)["rows"] == []


@pytest.mark.parametrize(
    "args", [("--month", "2026-09"), ("--tag", "persisted"), ("--merchant", "shop")]
)
def test_scope_and_tag_filters_match_baseline_despite_date_mismatch(show_root: QueryRoot, args):
    baseline = _show(show_root, *args, legacy=True)
    result = _show(show_root, *args)
    assert baseline.exit_code == result.exit_code == 0, result.output
    old = json.loads(baseline.output)
    new = json.loads(result.output)
    assert new["total_matches"] == old["total_matches"] == 1
    for original, current in zip(old["rows"], new["rows"], strict=True):
        assert {key: current[key] for key in original} == original
        assert current["date"] == "2026-08-01"
        assert current["tags_final"] == ["persisted"]
        assert current["transaction_id"] != current["row_hash"]
    assert new["_meta"]["filters_applied"] == 1
    missing = _show(show_root, "--month", "2026-08")
    assert missing.exit_code != 0
    assert "No data for 2026-08" in json.loads(missing.output)["error"]["message"]


def test_live_csv_rules_cannot_change_repository_and_human_show(show_root: QueryRoot):
    (show_root.root / "rules.yaml").write_text("rules: [invalid")
    path = show_root.root / "transactions/2099/12/transactions.csv"
    path.parent.mkdir(parents=True)
    path.write_text("amount\n123\n")
    result = _show(show_root, "--tag", "persisted", human=True)
    assert result.exit_code == 0, result.output
    assert "shop-0" in result.output and "shop-1" not in result.output
    untagged = _show(show_root, "--untagged")
    assert untagged.exit_code == 0, untagged.output
    assert json.loads(untagged.output)["rows"] == []
    bypass = _show(show_root, "--tag", "persisted", no_filter=True)
    assert json.loads(bypass.output)["total_matches"] == 2


@pytest.mark.parametrize("status", ["invalid", "opaque"])
def test_show_rejects_unparsed_canonical_rules(show_root: QueryRoot, status):
    StorageMutationFacade(show_root.root, show_root.provider).replace_config(
        ConfigDocument("rules", b"rules: []\n", status, None, "test")
    )
    result = _show(show_root, "--tag", "persisted")
    assert result.exit_code != 0
    assert "Canonical rules head" in json.loads(result.output)["error"]["message"]
    bypass = _show(show_root, "--tag", "persisted", no_filter=True)
    assert bypass.exit_code == 0, bypass.output
    assert json.loads(bypass.output)["total_matches"] == 2


def test_show_pins_rules_and_metadata_across_concurrent_write(show_root: QueryRoot, monkeypatch):
    read = show_cmd.read_transaction_snapshot

    def mutate_after_capture(*args, **kwargs):
        snapshot = read(*args, **kwargs)
        StorageMutationFacade(show_root.root, show_root.provider).replace_config(
            ConfigDocument.from_validated_yaml("rules", b"rules: []\n", parser_version="test")
        )
        return snapshot

    with monkeypatch.context() as context:
        context.setattr(show_cmd, "read_transaction_snapshot", mutate_after_capture)
        pinned = _show(show_root, "--tag", "persisted")
    assert pinned.exit_code == 0, pinned.output
    old = json.loads(pinned.output)
    assert old["total_matches"] == 1 and old["_meta"]["dataset_revision"] == 0
    latest = json.loads(_show(show_root, "--tag", "persisted").output)
    assert latest["total_matches"] == 2 and latest["_meta"]["dataset_revision"] == 1


def test_show_does_not_fall_back_without_activation_evidence(show_root: QueryRoot):
    result = CliRunner().invoke(app, ["--data-dir", str(show_root.root), "show", "--json"])
    assert result.exit_code != 0
    assert "evidence provider" in json.loads(result.output)["error"]["message"]


def test_native_unknown_month_remains_in_all_scope_search(tmp_path: Path):
    import shutil

    from finjuice.pipeline.storage.authority import AuthorityPaths, StaticActivationEvidenceProvider
    from finjuice.pipeline.storage.sqlite import RepositoryReader
    from tests.pipeline.test_sqlite_bulk_mutations import _evidence, _write_activation
    from tests.pipeline.test_sqlite_transaction_scopes import _native

    candidate = _native(tmp_path, ["2026-01-01", None])
    with RepositoryReader(candidate.database) as reader:
        generation = reader.info.dataset_generation
    root = tmp_path / "active"
    paths = AuthorityPaths.for_data_dir(root)
    shutil.copytree(candidate.root, paths.generation(generation).root)
    _write_activation(paths, generation)
    case = QueryRoot(
        root, tmp_path / "unused", StaticActivationEvidenceProvider(_evidence()), generation
    )
    latest = _show(case)
    assert latest.exit_code == 0, latest.output
    assert json.loads(latest.output)["total_matches"] == 1
    all_rows = _show(case, "--untagged")
    assert all_rows.exit_code == 0, all_rows.output
    payload = json.loads(all_rows.output)
    assert payload["total_matches"] == 2
    assert all(row["row_hash"] is None for row in payload["rows"])


def test_show_does_not_rewrite_preserved_tag_arrays(show_root: QueryRoot):
    from finjuice.pipeline.storage.read_facade import read_transaction_snapshot

    before = read_transaction_snapshot(show_root.root, show_root.provider)
    result = _show(show_root, "--tag", "persisted")
    assert result.exit_code == 0, result.output
    after = read_transaction_snapshot(show_root.root, show_root.provider)
    assert before == after
    assert all(row["tags_final"] == '["persisted","persisted"]' for row in after.rows)


@pytest.mark.parametrize("args", [("--month", "2026-09"), ("--tag", "persisted")])
def test_equal_datetime_page_order_matches_original_reader(show_root: QueryRoot, args):
    baseline = _show(show_root, *args, legacy=True, no_filter=True)
    active = _show(show_root, *args, no_filter=True)
    assert baseline.exit_code == active.exit_code == 0, active.output
    expected = [row["row_hash"] for row in json.loads(baseline.output)["rows"]]
    assert [row["row_hash"] for row in json.loads(active.output)["rows"]] == expected
    pages = []
    for cursor in ("0", "1"):
        page = _show(show_root, *args, "--limit", "1", "--cursor", cursor, no_filter=True)
        assert page.exit_code == 0, page.output
        pages.extend(row["row_hash"] for row in json.loads(page.output)["rows"])
    assert pages == expected
