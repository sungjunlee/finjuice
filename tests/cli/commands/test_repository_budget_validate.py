"""Budget validation reads selected canonical goals, never the live YAML path."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from finjuice.pipeline.budget_validation_repository import compute_repository_budget_validate
from finjuice.pipeline.cli.main import app
from finjuice.pipeline.cli.output import ExitCode
from finjuice.pipeline.storage.mutation_facade import ConfigDocument, StorageMutationFacade
from finjuice.pipeline.storage.sqlite import RepositoryReader
from tests.cli.commands.test_repository_assets import _activate
from tests.cli.commands.test_repository_query import QueryRoot

VALID = b"version: 1\nmonthly_budget:\n  total: 250000\n  categories:\n    food: 100000\n"


def _root(tmp_path: Path, state: str) -> QueryRoot:
    source = tmp_path / "source"
    source.mkdir()
    (source / "rules.yaml").write_text("version: 1\nrules: []\n")
    if state != "absent":
        path = source / ("nested/goals.yaml" if state == "unselected" else "goals.yaml")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"PRIVATE_SENTINEL: [" if state == "invalid" else VALID)
    return _activate(source, tmp_path)


def _cli(root: QueryRoot, *, human: bool = False, evidence: bool = True):
    return CliRunner().invoke(
        app,
        ["--data-dir", str(root.root), "budget", "validate", *([] if human else ["--json"])],
        obj={"activation_evidence_provider": root.provider} if evidence else {},
    )


@pytest.mark.parametrize("state", ["valid", "invalid", "absent", "unselected"])
def test_helper_canonical_selection_and_live_goals_ignored(tmp_path: Path, state: str) -> None:
    root = _root(tmp_path, state)
    initial = compute_repository_budget_validate(root.root, root.provider)
    assert initial is not None
    assert initial["status"] == ("valid" if state == "valid" else "invalid")
    assert initial["selection_state"] == ("selected" if state in {"valid", "invalid"} else state)
    assert initial["path"] is None
    assert initial["_repository_meta"]["dataset_revision"] == 0
    assert initial["_repository_meta"]["dataset_generation"] == root.generation
    assert "PRIVATE_SENTINEL" not in str(initial)
    (root.root / "goals.yaml").write_bytes(VALID if state != "valid" else b"PRIVATE_SENTINEL: [")
    assert compute_repository_budget_validate(root.root, root.provider) == initial


@pytest.mark.parametrize("state", ["valid", "invalid"])
def test_cli_json_null_path_repository_meta_human_and_exit(tmp_path: Path, state: str) -> None:
    root = _root(tmp_path, state)
    result = _cli(root)
    assert result.exit_code == (0 if state == "valid" else ExitCode.VALIDATION_ERROR), result.output
    payload = json.loads(result.output)
    assert payload["path"] is None
    assert payload["authority"] == "repository"
    assert payload["_meta"]["dataset_revision"] == 0
    assert payload["_meta"]["calculation_policy"] == "canonical_goals_validation.v1"
    human = _cli(root, human=True)
    assert human.exit_code == result.exit_code
    assert "Canonical goals" in human.output
    assert "PRIVATE_SENTINEL" not in result.output + human.output


def test_cli_missing_authority_is_static_failure(tmp_path: Path) -> None:
    root = _root(tmp_path, "valid")
    (root.root / "goals.yaml").write_bytes(VALID)
    result = _cli(root, evidence=False)
    assert result.exit_code != 0
    assert "Canonical analysis evidence could not be read" in result.output
    assert str(root.root) not in result.output


def test_same_reader_writer_between_domains_keeps_old_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _root(tmp_path, "valid")
    initial = compute_repository_budget_validate(root.root, root.provider)
    original = RepositoryReader.transaction_snapshot

    def mutate_after_transactions(reader: RepositoryReader):
        transactions = original(reader)
        StorageMutationFacade(root.root, root.provider).replace_config(
            ConfigDocument("goals", b"PRIVATE_SENTINEL: [", "invalid", None, "test.v1")
        )
        return transactions

    monkeypatch.setattr(RepositoryReader, "transaction_snapshot", mutate_after_transactions)
    assert compute_repository_budget_validate(root.root, root.provider) == initial
    monkeypatch.setattr(RepositoryReader, "transaction_snapshot", original)
    fresh = compute_repository_budget_validate(root.root, root.provider)
    assert fresh is not None and fresh["status"] == "invalid"
    assert fresh["_repository_meta"]["dataset_revision"] == 1
