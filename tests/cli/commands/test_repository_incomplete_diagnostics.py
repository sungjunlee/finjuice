"""Receipt diagnostics remain available when canonical rows cannot all be projected."""

from __future__ import annotations

import hashlib
import json

import pytest

from finjuice.pipeline.storage.mutation_facade import ConfigDocument, StorageMutationFacade
from finjuice.pipeline.storage.read_facade import read_transaction_snapshot, snapshot_metadata
from tests.cli.commands.test_repository_analysis_incomplete import incomplete_root as _fixture
from tests.cli.commands.test_repository_export import _verify
from tests.cli.commands.test_repository_query import QueryRoot

incomplete_root = _fixture


@pytest.mark.parametrize("human", [False, True])
def test_incomplete_rows_do_not_block_saved_receipt_diagnostics(
    incomplete_root: QueryRoot, human: bool
) -> None:
    # Arrange: a synthetic saved receipt describes bytes, not a completeness proof.
    snapshot = read_transaction_snapshot(incomplete_root.root, incomplete_root.provider)
    assert snapshot is not None
    run = incomplete_root.root / "exports/runs/saved-receipt"
    run.mkdir(parents=True)
    artifact = run / "report.csv"
    content = b"saved derived bytes\n"
    artifact.write_bytes(content)
    manifest = run / "export-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "manifest_version": 1,
                "source": snapshot_metadata(snapshot),
                "files": [
                    {
                        "path": artifact.name,
                        "sha256": hashlib.sha256(content).hexdigest(),
                        "size_bytes": len(content),
                    }
                ],
            }
        )
    )
    before = manifest.read_bytes()

    # Act / Assert: receipt verification remains read-only and reports integrity.
    intact = _verify(incomplete_root, manifest, human=human)
    assert intact.exit_code == 0, intact.output
    assert "intact" in intact.output
    if not human:
        assert json.loads(intact.output)["stale"] is False
    assert read_transaction_snapshot(incomplete_root.root, incomplete_root.provider) == snapshot
    artifact.write_bytes(b"changed derived bytes\n")
    StorageMutationFacade(incomplete_root.root, incomplete_root.provider).replace_config(
        ConfigDocument.from_validated_yaml("rules", b"rules: []\n", parser_version="test")
    )
    changed = _verify(incomplete_root, manifest, human=human)
    assert changed.exit_code == 0, changed.output
    assert "mismatch" in changed.output
    if human:
        assert "stale" in changed.output
    else:
        assert json.loads(changed.output)["stale"] is True
    assert manifest.read_bytes() == before
    assert "PRIVATE_UNMATERIALIZED" not in intact.output + changed.output
