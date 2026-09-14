"""Ownership projection against real canonical mutation and repository storage."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Literal

import pytest

from finjuice.pipeline.storage.sqlite import (
    ExactValue,
    OwnershipAssertionRecord,
    OwnershipShareRecord,
    new_entity_id,
)
from finjuice.pipeline.storage.sqlite.mutations import (
    MutationContext,
    MutationOutcome,
    MutationService,
)
from finjuice.pipeline.storage.sqlite.ownership_projection import ownership_projection
from tests.pipeline.test_sqlite_mutations import _active_repository, _request


def _claim(  # noqa: PLR0913 -- Named evidence fields keep temporal cases explicit.
    context: MutationContext,
    account: str,
    shares: list[tuple[str, str, int]],
    *,
    start: str | None = None,
    end: str | None = None,
    completeness: Literal["complete", "partial", "unknown"] = "complete",
    confirmation: Literal["confirmed", "unconfirmed", "rejected"] = "confirmed",
    previous: str | None = None,
) -> str:
    assertion = new_entity_id()
    records = []
    for party, coefficient, scale in shares:
        value = new_entity_id()
        context.add_exact_value(
            value,
            ExactValue(
                coefficient=coefficient,
                scale=scale,
                value_kind="rate",
                origin_kind="calculated",
                lexical=None,
                unit="ownership_share.v1",
            ),
        )
        records.append(OwnershipShareRecord(assertion, party, value))
    context.add_ownership_assertion(
        OwnershipAssertionRecord(
            assertion,
            account,
            completeness,
            confirmation,
            {"kind": "synthetic"},
            effective_from=start,
            effective_to=end,
            unknown_remainder=completeness != "complete",
            confirmed_at="2026-09-01T00:00:00Z" if confirmation == "confirmed" else None,
            supersedes_assertion_id=previous,
        ),
        records,
    )
    return assertion


def test_exact_two_party_shares_and_inclusive_bounds(tmp_path: Path) -> None:
    paths, evidence, generation, parties, accounts, _ = _active_repository(tmp_path, accounts=2)
    coefficients = ("3333333333333333333333333333", "6666666666666666666666666667")

    def write(context: MutationContext) -> MutationOutcome:
        _claim(
            context,
            accounts[0],
            [
                (party, coefficient, 28)
                for party, coefficient in zip(parties, coefficients, strict=True)
            ],
            start="2026-01-01",
            end="2026-01-31",
        )
        return MutationOutcome(result={"written": True})

    MutationService(paths, evidence).execute(_request(generation, "precise", 0), write)
    with sqlite3.connect(paths.generation(generation).database) as connection:
        for day in ("2026-01-01", "2026-01-31"):
            projected = ownership_projection(connection, accounts[0], as_of=day)
            assert projected["status"] == "confirmed"
            assert projected["assertions"][0]["evidence"] == {"kind": "synthetic"}
            assert {row["party_id"]: row["share"] for row in projected["shares"]} == {
                party: {"coefficient": coefficient, "scale": 28}
                for party, coefficient in zip(parties, coefficients, strict=True)
            }
            assert projected["remainder"] == {"coefficient": "0", "scale": 28}
            assert projected["unknown_remainder"] is False
            json.dumps(projected, allow_nan=False)
        for day in ("2025-12-31", "2026-02-01"):
            projected = ownership_projection(connection, accounts[0], as_of=day)
            assert projected["status"] == "unknown"
            assert projected["shares"] == []
            assert projected["remainder"] == {"coefficient": "1", "scale": 0}


def test_partial_remainder_and_unconfirmed_correction_stay_separate(tmp_path: Path) -> None:
    paths, evidence, generation, parties, accounts, _ = _active_repository(tmp_path, accounts=2)

    def write(context: MutationContext) -> MutationOutcome:
        previous = _claim(context, accounts[0], [(parties[0], "125", 3)], completeness="partial")
        _claim(
            context,
            accounts[0],
            [(parties[1], "1", 0)],
            confirmation="unconfirmed",
            previous=previous,
        )
        return MutationOutcome(result={"written": True})

    MutationService(paths, evidence).execute(_request(generation, "partial", 0), write)
    with sqlite3.connect(paths.generation(generation).database) as connection:
        projected = ownership_projection(connection, accounts[0], as_of="2026-02-01")
        assert projected["status"] == "confirmed"
        assert projected["completeness"] == "partial"
        assert projected["unknown_remainder"] is True
        assert projected["remainder"] == {"coefficient": "875", "scale": 3}
        assert [row["party_id"] for row in projected["shares"]] == [parties[0]]
        assert {row["confirmation_state"] for row in projected["assertions"]} == {
            "confirmed",
            "unconfirmed",
        }
        projected["shares"][0]["share"]["coefficient"] = "999"
        again = ownership_projection(connection, accounts[0], as_of="2026-02-01")
        assert again["shares"][0]["share"]["coefficient"] == "125"


def test_confirmed_correction_never_resurrects_old_period(tmp_path: Path) -> None:
    paths, evidence, generation, parties, accounts, _ = _active_repository(tmp_path, accounts=2)

    def write(context: MutationContext) -> MutationOutcome:
        previous = _claim(context, accounts[0], [(parties[0], "1", 0)])
        _claim(
            context,
            accounts[0],
            [(parties[1], "1", 0)],
            start="2026-02-01",
            end="2026-02-28",
            previous=previous,
        )
        return MutationOutcome(result={"written": True})

    MutationService(paths, evidence).execute(_request(generation, "correct", 0), write)
    with sqlite3.connect(paths.generation(generation).database) as connection:
        before = ownership_projection(connection, accounts[0], as_of="2026-01-01")
        assert before["status"] == "unknown"
        assert before["assertions"][0]["superseded_by"]
        current = ownership_projection(connection, accounts[0], as_of="2026-02-01")
        assert [share["party_id"] for share in current["shares"]] == [parties[1]]
        assert (
            ownership_projection(connection, accounts[0], as_of="2026-03-01")["status"] == "unknown"
        )


def test_unconfirmed_overallocation_and_rejection_do_not_assign_owners(tmp_path: Path) -> None:
    paths, evidence, generation, parties, accounts, _ = _active_repository(tmp_path, accounts=2)

    def write(context: MutationContext) -> MutationOutcome:
        _claim(
            context,
            accounts[0],
            [(party, "7", 1) for party in parties],
            confirmation="unconfirmed",
        )
        _claim(context, accounts[1], [(parties[1], "1", 0)], confirmation="rejected")
        return MutationOutcome(result={"written": True})

    MutationService(paths, evidence).execute(_request(generation, "proposed", 0), write)
    with sqlite3.connect(paths.generation(generation).database) as connection:
        proposed = ownership_projection(connection, accounts[0], as_of="2026-01-01")
        assert proposed["status"] == "unconfirmed"
        assert proposed["shares"] == []
        assert proposed["remainder"] == {"coefficient": "1", "scale": 0}
        assert proposed["assertions"][0]["total"] == {"coefficient": "14", "scale": 1}
        assert proposed["assertions"][0]["remainder"] is None
        assert (
            ownership_projection(connection, accounts[1], as_of="2026-01-01")["status"] == "unknown"
        )


@pytest.mark.parametrize("day", ["2026-02-30", "20260201", "2026-02-01T00:00:00"])
def test_invalid_asof_date_is_rejected(tmp_path: Path, day: str) -> None:
    paths, _, generation, _, accounts, _ = _active_repository(tmp_path, accounts=1)
    with sqlite3.connect(paths.generation(generation).database) as connection:
        with pytest.raises(ValueError):
            ownership_projection(connection, accounts[0], as_of=day)
