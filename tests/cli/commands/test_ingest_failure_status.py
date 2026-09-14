"""Exact import failures preserve typed status and prior file receipts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from finjuice.pipeline.storage.mutation_facade import StorageMutationFacade
from finjuice.pipeline.storage.sqlite.errors import MutationConflictError, MutationValidationError
from tests.cli.commands.test_repository_bulk_commands import _invoke
from tests.cli.commands.test_repository_import_commands import _transaction_count, _write_xlsx
from tests.cli.commands.test_repository_mutation_fences import _ActiveRoot, _authority_state
from tests.cli.commands.test_repository_mutation_fences import active_root as _active_root_fixture

active_root = _active_root_fixture

_ROUTES = [
    ("ingest", False),
    ("import", False),
    ("refresh", False),
    ("ingest", True),
    ("import", True),
]


def _args(command: str, sources: list[Path], preview: bool, json_output: bool) -> list[str]:
    args = [str(source) for source in sources] if command == "import" else []
    if preview:
        args.append("--dry-run")
    if json_output:
        args.append("--json")
    return args


@pytest.mark.parametrize(("command", "preview"), _ROUTES)
@pytest.mark.parametrize("json_output", [False, True], ids=["human", "json"])
def test_single_file_stale_revision_preserves_conflict_status(
    active_root: _ActiveRoot, command: str, preview: bool, json_output: bool
) -> None:
    source = active_root.root / "imports" / "one.xlsx"
    _write_xlsx(source)
    first = _invoke(active_root, "ingest", "--json")
    assert first.exit_code == 0, first.output
    _write_xlsx(source, extra="new bytes")
    before = _authority_state(active_root)

    result = _invoke(
        active_root,
        command,
        *_args(command, [source], preview, json_output),
        "--expected-revision",
        "0",
    )

    assert result.exit_code == 3, result.output
    assert _authority_state(active_root) == before
    if json_output:
        payload = json.loads(result.output)
        assert payload["error"]["code"] == "VALIDATION_FAILED"
        pipeline = payload["_meta"]["pipeline"]
        assert pipeline["error_type"] == "MutationConflictError"
        assert pipeline["steps"]["ingest"]["receipts"] == []


@pytest.mark.parametrize("route", _ROUTES)
@pytest.mark.parametrize(
    "presentation",
    [(False, 1), (True, 1), (False, 2), (True, 2)],
    ids=["human-single", "json-single", "human-partial", "json-partial"],
)
@pytest.mark.parametrize(
    "failure",
    [(MutationValidationError, 2, "INVALID_ARGS"), (MutationConflictError, 3, "VALIDATION_FAILED")],
    ids=["validation", "conflict"],
)
def test_typed_file_failure_keeps_prior_receipts(
    active_root: _ActiveRoot,
    monkeypatch: pytest.MonkeyPatch,
    route: tuple[str, bool],
    presentation: tuple[bool, int],
    failure: tuple[type[Exception], int, str],
) -> None:
    command, preview = route
    json_output, count = presentation
    error_type, exit_code, error_code = failure
    sources = [active_root.root / "imports" / f"{index}.xlsx" for index in range(count)]
    for index, source in enumerate(sources):
        _write_xlsx(source, extra=str(index))
    original = StorageMutationFacade.import_exact_xlsx
    calls = 0

    def fail_last(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == count:
            raise error_type("private exception detail must stay internal")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(StorageMutationFacade, "import_exact_xlsx", fail_last)
    before = _authority_state(active_root)

    result = _invoke(active_root, command, *_args(command, sources, preview, json_output))

    assert result.exit_code == exit_code, result.output
    assert calls == count
    assert "private exception detail" not in result.output
    assert _transaction_count(active_root) == (0 if preview else count - 1)
    if preview or count == 1:
        assert _authority_state(active_root) == before
    if json_output:
        payload = json.loads(result.output)
        assert payload["error"]["code"] == error_code
        pipeline = payload["_meta"]["pipeline"]
        assert pipeline["failed_step"] == "ingest"
        assert pipeline["completed_steps"] == []
        assert pipeline["error_type"] == error_type.__name__
        step = pipeline["steps"]["ingest"]
        assert step["dry_run"] == preview
        assert len(step["receipts"]) == count - 1
        assert step["summary"]["failed"] == 1
        assert step["summary"]["failed_files"] == [[sources[-1].name, error_type.__name__]]
        if count == 2:
            receipt = step["receipts"][0]
            assert receipt["result"]["counts"]["transactions"]["inserted"] == 1
            if not preview:
                assert receipt["state_changed"] is True
                assert receipt["committed_revision"] == 1
