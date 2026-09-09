"""Synthetic tests for exact values, stable IDs, and derived path validation."""

from __future__ import annotations

from decimal import Decimal, localcontext
from pathlib import Path

import pytest

from finjuice.pipeline.storage.sqlite import ExactValue, GenerationPaths, migration_entity_id
from finjuice.pipeline.storage.sqlite.errors import (
    ExactValueError,
    IdentifierError,
    RepositoryPathError,
)


def test_exact_value_preserves_large_lexical_value_outside_decimal_context() -> None:
    with localcontext() as context:
        context.prec = 2
        value = ExactValue.from_lexical(
            "12345678901234567890.00100",
            value_kind="money",
            currency="KRW",
        )

        assert value.coefficient == "1234567890123456789000100"
        assert value.scale == 5
        assert value.lexical == "12345678901234567890.00100"
        assert value.to_decimal() == Decimal("12345678901234567890.00100")


def test_exact_value_rejects_float_and_inconsistent_direct_lexical_evidence() -> None:
    with pytest.raises(ExactValueError, match="parsed from text"):
        ExactValue.from_lexical(1.2, value_kind="money", currency="KRW")  # type: ignore[arg-type]

    with pytest.raises(ExactValueError, match="disagrees"):
        ExactValue(
            coefficient="100",
            scale=0,
            lexical="1.2",
            value_kind="money",
            origin_kind="migration",
            currency="KRW",
        )


def test_exact_value_requires_explicit_currency_or_versioned_unit() -> None:
    with pytest.raises(ExactValueError, match="known currency"):
        ExactValue.from_lexical("1", value_kind="money")

    with pytest.raises(ExactValueError, match="versioned domain unit"):
        ExactValue.from_lexical("1", value_kind="quantity", unit="share")

    unknown_money = ExactValue.from_lexical(
        "-0.00",
        value_kind="money",
        currency_unknown=True,
    )
    assert (unknown_money.coefficient, unknown_money.scale) == ("0", 2)


def test_migration_ids_distinguish_duplicate_row_hash_occurrences() -> None:
    digest = "a" * 64
    first = migration_entity_id(
        digest,
        "transaction",
        {"locator_version": 1, "sheet": "거래", "row": 7, "row_hash": "same"},
    )
    repeated = migration_entity_id(
        digest,
        "transaction",
        {"locator_version": 1, "sheet": "거래", "row": 8, "row_hash": "same"},
    )

    assert first != repeated
    assert first == migration_entity_id(
        f"sha256:{digest}",
        "transaction",
        {"row_hash": "same", "row": 7, "sheet": "거래", "locator_version": 1},
    )
    with pytest.raises(IdentifierError, match="row_hash alone"):
        migration_entity_id(digest, "transaction", {"row_hash": "same"})


def test_generation_paths_reject_path_components_from_unvalidated_values(tmp_path: Path) -> None:
    paths = GenerationPaths(tmp_path / "generation")

    with pytest.raises(RepositoryPathError, match="digest"):
        paths.object_path("../escape")
    with pytest.raises(RepositoryPathError, match="generation"):
        paths.derived_revision("../escape", 1)
    with pytest.raises(RepositoryPathError, match="revision"):
        paths.derived_revision("12345678-1234-4234-9234-123456789abc", True)
