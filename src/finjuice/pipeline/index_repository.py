"""Canonical index counts from one detached repository revision."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import yaml
from ruamel.yaml.error import YAMLError as RuamelYAMLError

from finjuice.pipeline.config import Config
from finjuice.pipeline.forecast_validators import validate_scenarios_config_bytes
from finjuice.pipeline.goals import load_goals_roundtrip_bytes, validate_goals_payload
from finjuice.pipeline.portfolio_display import PortfolioDisplay, PortfolioDisplayError
from finjuice.pipeline.storage.authority import ActivationEvidenceProvider
from finjuice.pipeline.storage.read_facade import read_checkup_snapshot
from finjuice.pipeline.storage.sqlite.checkup_reads import CheckupReadSnapshot
from finjuice.pipeline.storage.sqlite.portfolio_reads import PortfolioConfigSnapshot
from finjuice.pipeline.storage.sqlite.transaction_reads import TransactionReadSnapshot
from finjuice.pipeline.tagging.rules_yaml_io import load_rules_bytes

_ERROR = "Canonical index could not read verified collection evidence."
_GOALS_KEYS = (
    "monthly_budget",
    "net_worth_target",
    "known_obligations",
    "recurring_savings",
    "financial_context",
)
_SCENARIO_KEYS = ("assumptions", "lifecycle_events")


class RepositoryIndexError(ValueError):
    """Static whole-catalog authority/integrity failure; no legacy fallback."""


@dataclass(frozen=True)
class FinancialCollection:
    """Content-free logical inventory; preserve these fields in compact output."""

    name: str
    exists: bool
    count: int | None
    status: Literal["missing", "empty", "populated", "unavailable"]
    count_label: str
    count_basis: str
    count_state: Literal["known", "absent", "unavailable"]
    selection_state: str | None = None
    revision_id: str | None = None
    unavailable_reason: str | None = None
    basis: str = "repository"


@dataclass(frozen=True)
class RepositoryIndexInputs:
    """Five canonical collections from one revision, without paths/financial content."""

    collections: tuple[FinancialCollection, ...]
    metadata: dict[str, Any]


def collect_repository_index_inputs(
    config: Config, *, evidence_provider: ActivationEvidenceProvider | None = None
) -> RepositoryIndexInputs | None:
    """Return None only when the existing facade verifies legacy authority."""
    try:
        snapshot = read_checkup_snapshot(config.data_dir, evidence_provider, digests=())
        return None if snapshot is None else index_inputs_from_snapshot(snapshot)
    except Exception:
        raise RepositoryIndexError(_ERROR) from None


def index_inputs_from_snapshot(snapshot: CheckupReadSnapshot) -> RepositoryIndexInputs:
    """Count only detached evidence; no frame conversion or financial arithmetic."""
    try:
        collections = (
            _transactions(snapshot.status.transactions),
            _configuration("rules", snapshot.rules),
            _assets(snapshot),
            _configuration("goals", snapshot.portfolio.goals),
            _configuration("scenarios", snapshot.portfolio.scenarios),
        )
        return RepositoryIndexInputs(
            collections,
            {
                "authority": "repository",
                "dataset_generation": snapshot.info.dataset_generation,
                "dataset_revision": snapshot.info.dataset_revision,
                "sqlite_schema_version": snapshot.info.schema_version,
                "calculation_policy": "canonical_index_counts.v1",
            },
        )
    except Exception:
        raise RepositoryIndexError(_ERROR) from None


def _transactions(snapshot: TransactionReadSnapshot) -> FinancialCollection:
    identifiers = [row["transaction_id"] for row in snapshot.rows]
    scope_ids = [scope.transaction_id for scope in snapshot.scopes]
    # Match existing scoped_transactions evidence checks without amount->float projection.
    # UUID duplicates are integrity failures; duplicate row_hash aliases remain separate rows.
    if len(set(identifiers)) != len(identifiers) or len(set(scope_ids)) != len(scope_ids):
        raise RepositoryIndexError(_ERROR)
    if set(scope_ids) != set(identifiers):
        return _unavailable(
            "transactions", "transaction_rows", "primary_native_rows", "scope_unknown"
        )
    if snapshot.unmaterialized_months:
        return _unavailable(
            "transactions", "transaction_rows", "primary_native_rows", "unmaterialized_rows"
        )
    count = sum(scope.included for scope in snapshot.scopes)
    return FinancialCollection(
        "transactions",
        True,
        count,
        "populated" if count else "empty",
        "transaction_rows",
        "primary_native_rows",
        "known",
    )


def _assets(snapshot: CheckupReadSnapshot) -> FinancialCollection:
    try:
        display = PortfolioDisplay(snapshot.portfolio)
        rows = snapshot.portfolio.asset_snapshots
        display._guard("snapshot", {row["provenance_id"] for row in rows})
        # Reuse the existing exact source scope/date contract without converting money.
        count = sum(display._location(row, "snapshot") is not None for row in rows)
    except PortfolioDisplayError:
        return _unavailable(
            "assets", "snapshot_rows", "primary_native_snapshots", "snapshot_unavailable"
        )
    return FinancialCollection(
        "assets",
        True,
        count,
        "populated" if count else "empty",
        "snapshot_rows",
        "primary_native_snapshots",
        "known",
    )


def _configuration(name: str, selection: PortfolioConfigSnapshot) -> FinancialCollection:
    label = "rules" if name == "rules" else "configured_signals"
    basis = "selected_rules_all_entries" if name == "rules" else "selected_configured_signals"
    if selection.head is None and selection.selection_state == "absent" and not selection.revisions:
        return FinancialCollection(name, False, None, "missing", label, basis, "absent", "absent")
    head = selection.head
    revision_id = head.revision_id if head else None
    if selection.selection_state != "selected" or head is None or head.parsed_status != "parsed":
        return _unavailable(name, label, basis, "selection_unavailable", selection)
    try:
        count = _config_count(name, head.content)
    except (ValueError, TypeError, UnicodeError, yaml.YAMLError, RuamelYAMLError):
        return _unavailable(name, label, basis, "configuration_invalid", selection)
    return FinancialCollection(
        name,
        True,
        count,
        "populated" if count else "empty",
        label,
        basis,
        "known",
        selection.selection_state,
        revision_id,
    )


def _config_count(name: str, content: bytes) -> int:
    if name == "rules":
        # Existing loader preserves disabled entries and default tolerant unknown-field policy.
        return len(load_rules_bytes(content))
    if name == "goals":
        _, payload = load_goals_roundtrip_bytes(content)
        document, problems = validate_goals_payload(payload)
        if document is None or problems:
            raise ValueError("Canonical goals configuration is unavailable.")
        return _signal_count(payload, _GOALS_KEYS)
    if not validate_scenarios_config_bytes(content).is_valid:
        raise ValueError("Canonical scenarios configuration is unavailable.")
    return _signal_count(yaml.safe_load(content.decode("utf-8")) or {}, _SCENARIO_KEYS)


def _signal_count(payload: Any, keys: tuple[str, ...]) -> int:
    # Same arithmetic as legacy index_collections_helpers._yaml_signal_count.
    if not isinstance(payload, dict):
        return 0
    count = 0
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            count += len(value)
        elif isinstance(value, dict):
            count += int(bool(value))
        elif value not in (None, ""):
            count += 1
    return count


def _unavailable(
    name: str,
    label: str,
    basis: str,
    reason: str,
    selection: PortfolioConfigSnapshot | None = None,
) -> FinancialCollection:
    revision_id = selection.head.revision_id if selection and selection.head else None
    return FinancialCollection(
        name,
        True,
        None,
        "unavailable",
        label,
        basis,
        "unavailable",
        selection.selection_state if selection else None,
        revision_id,
        reason,
    )
