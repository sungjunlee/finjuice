"""Persist exact asset snapshots without merging display-name identities."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from finjuice.pipeline.ingest.exact_assets import ExactAssetMapping, ExactMappedAssetRow
from finjuice.pipeline.storage.sqlite.exact import ExactValue
from finjuice.pipeline.storage.sqlite.exact_import.constants import (
    UNRESOLVED_ACCOUNT_KIND,
    UNRESOLVED_RESOURCE_KIND,
)
from finjuice.pipeline.storage.sqlite.exact_import.evidence import (
    PersistSession,
    SourcePlace,
    add_mapper_issues,
    add_row_provenance,
)
from finjuice.pipeline.storage.sqlite.exact_import.models import RowDecision
from finjuice.pipeline.storage.sqlite.ids import new_entity_id
from finjuice.pipeline.storage.sqlite.records import (
    AccountRecord,
    AssetSnapshotRecord,
    ObservationRecord,
    ResourceRecord,
)


@dataclass
class _AssetIds:
    accounts: dict[str, str] = field(default_factory=dict)
    resources: dict[str, str] = field(default_factory=dict)


def persist_assets(
    session: PersistSession,
    mapping: ExactAssetMapping,
    decisions: Sequence[RowDecision],
) -> list[str]:
    """Write planned asset snapshots and return inserted snapshot IDs."""
    inserted: list[str] = []
    identities = _AssetIds()
    by_row = {row.source_row: row for row in mapping.rows}
    for decision in decisions:
        if decision.family != "assets":
            continue
        row = by_row[decision.source_row]
        snapshot_id = _persist_asset_row(session, mapping, row, decision, identities)
        if snapshot_id is not None:
            inserted.append(snapshot_id)
    return inserted


def _persist_asset_row(
    session: PersistSession,
    mapping: ExactAssetMapping,
    row: ExactMappedAssetRow,
    decision: RowDecision,
    identities: _AssetIds,
) -> str | None:
    place = SourcePlace("asset", row.sheet_name, row.source_row)
    extra = _row_payload(mapping, row, decision)
    provenance_id = add_row_provenance(session, place, row.cells, extra)
    add_mapper_issues(session, provenance_id, row.issues, sheet_name=row.sheet_name)
    if decision.action != "insert":
        return None
    return _insert_snapshot(session, row, provenance_id, identities)


def _insert_snapshot(
    session: PersistSession,
    row: ExactMappedAssetRow,
    provenance_id: str,
    identities: _AssetIds,
) -> str:
    assert row.snapshot.parsed_date is not None
    account_id = _account_id(session, row, identities.accounts)
    resource_id = _resource_id(session, row, identities.resources)
    observation_id = _add_observation(session, row)
    quantity_id = _add_optional_value(session, provenance_id, row.quantity)
    market_id = _add_optional_value(session, provenance_id, row.market_value)
    snapshot_id = new_entity_id()
    session.context.add_asset_snapshot(
        AssetSnapshotRecord(
            snapshot_id=snapshot_id,
            observation_id=observation_id,
            provenance_id=provenance_id,
            account_id=account_id,
            resource_id=resource_id,
            quantity_value_id=quantity_id,
            market_value_id=market_id,
            snapshot_date=row.snapshot.parsed_date.isoformat(),
        )
    )
    return snapshot_id


def _account_id(
    session: PersistSession,
    row: ExactMappedAssetRow,
    accounts: dict[str, str],
) -> str:
    explicit = row.source_account_id
    if explicit is not None and explicit in accounts:
        return accounts[explicit]
    account_id = new_entity_id()
    session.context.add_account(
        AccountRecord(
            account_id=account_id,
            account_kind=UNRESOLVED_ACCOUNT_KIND,
            display_name=row.source_account_name or explicit,
            ownership_state="unknown",
        )
    )
    if explicit is not None:
        accounts[explicit] = account_id
    return account_id


def _resource_id(
    session: PersistSession,
    row: ExactMappedAssetRow,
    resources: dict[str, str],
) -> str:
    explicit = row.source_instrument_id
    if explicit is not None and explicit in resources:
        return resources[explicit]
    resource_id = new_entity_id()
    session.context.add_resource(
        ResourceRecord(
            resource_id=resource_id,
            resource_kind=UNRESOLVED_RESOURCE_KIND,
            display_name=row.source_instrument_name or explicit,
        )
    )
    if explicit is not None:
        resources[explicit] = resource_id
    return resource_id


def _add_observation(session: PersistSession, row: ExactMappedAssetRow) -> str:
    observation_id = new_entity_id()
    source = row.snapshot.source
    parsed = row.snapshot.parsed_date
    effective = parsed.isoformat() if parsed is not None and source in {"row", "explicit"} else None
    session.context.add_observation(
        ObservationRecord(
            observation_id=observation_id,
            occurrence_id=session.occurrence_id,
            observed_at=None,
            effective_at=effective,
            collected_at=session.collected_at,
            scope_state="partial",
            confirmation_state="unconfirmed",
        )
    )
    return observation_id


def _add_optional_value(
    session: PersistSession,
    provenance_id: str,
    value: ExactValue | None,
) -> str | None:
    if value is None:
        return None
    value_id = new_entity_id()
    session.context.add_exact_value(value_id, value, provenance_id=provenance_id)
    return value_id


def _row_payload(
    mapping: ExactAssetMapping,
    row: ExactMappedAssetRow,
    decision: RowDecision,
) -> dict[str, object]:
    return {
        "action": decision.action,
        "date1904": mapping.date1904,
        "source_account_id": row.source_account_id,
        "source_instrument_id": row.source_instrument_id,
        "supported": row.supported,
        "temporal_policy": row.snapshot.temporal_policy,
    }
