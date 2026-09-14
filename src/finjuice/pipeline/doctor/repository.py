"""Doctor domain diagnostics from one canonical revision and staged observation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from finjuice.pipeline.checkup.import_preview import (
    StagedImportObservation,
    capture_staged_imports,
    evaluate_staged_imports,
)
from finjuice.pipeline.config import Config
from finjuice.pipeline.doctor.models import CheckResult
from finjuice.pipeline.doctor.repository_data import transaction_checks
from finjuice.pipeline.doctor.repository_rules import rules_checks
from finjuice.pipeline.storage.authority import (
    ActivationEvidenceProvider,
    LegacyAuthority,
    resolve_storage_authority,
)
from finjuice.pipeline.storage.read_facade import read_checkup_snapshot
from finjuice.pipeline.storage.sqlite.checkup_reads import CheckupReadSnapshot


@dataclass(frozen=True)
class RepositoryDoctorResult:
    """Detached canonical domain checks for the ordinary doctor composer."""

    config_checks: list[CheckResult]
    data_checks: list[CheckResult]
    metadata: dict[str, Any]
    next_step: str


def collect_repository_doctor(
    config: Config, provider: ActivationEvidenceProvider | None
) -> RepositoryDoctorResult | None:
    """Return legacy only after verified authority resolution; failures stay diagnostic."""
    try:
        authority = resolve_storage_authority(config.data_dir, provider).authority
    except Exception:
        return _unavailable("repository_authority", "unavailable")
    if isinstance(authority, LegacyAuthority):
        return None
    try:
        staged = capture_staged_imports(config.import_dir)
    except Exception:
        staged = None
    try:
        snapshot = read_checkup_snapshot(
            config.data_dir, provider, digests=staged.digests if staged else ()
        )
        if snapshot is None:
            return _unavailable("repository_read", "unavailable")
        return _collect(snapshot, staged)
    except Exception:
        return _unavailable("repository_read", "repository")


def _unavailable(name: str, authority: str) -> RepositoryDoctorResult:
    return RepositoryDoctorResult(
        [],
        [CheckResult("error", "Canonical diagnostic evidence is unavailable.", name=name)],
        {
            "authority": authority,
            "canonical_domains": "unavailable",
            "calculation_policy": "canonical_doctor.v1",
        },
        "finjuice status --json",
    )


def _collect(
    snapshot: CheckupReadSnapshot, staged: StagedImportObservation | None
) -> RepositoryDoctorResult:
    rules, rules_meta = rules_checks(snapshot.rules)
    data, data_meta = transaction_checks(snapshot.status.transactions)
    staged_check, staged_meta = _staged_checks(snapshot, staged)
    data.insert(0, CheckResult("ok", "Canonical repository evidence verified.", name="repository"))
    data.append(staged_check)
    metadata = {
        "authority": "repository",
        "canonical_domains": "available",
        "dataset_generation": snapshot.info.dataset_generation,
        "dataset_revision": snapshot.info.dataset_revision,
        "sqlite_schema_version": snapshot.info.schema_version,
        "calculation_policy": "canonical_doctor.v1",
        **rules_meta,
        **data_meta,
        "staged_observation": staged_meta,
    }
    if any(check.status == "error" for check in data):
        next_step = "finjuice status --json"
    elif any(check.status != "ok" for check in rules):
        next_step = "finjuice rules validate"
    elif staged_meta.get("pending_files", 0):
        next_step = "finjuice ingest --only-unprocessed"
    else:
        next_step = "finjuice status --json"
    return RepositoryDoctorResult(rules, data, metadata, next_step)


def _staged_checks(
    snapshot: CheckupReadSnapshot, staged: StagedImportObservation | None
) -> tuple[CheckResult, dict[str, Any]]:
    try:
        if staged is None:
            raise ValueError("Staged observation unavailable.")
        summary = evaluate_staged_imports(staged, snapshot.imports).summary
        status = "warning" if summary.pending_files else "ok"
        if summary.failed_files:
            status = "error"
        return CheckResult(
            status,
            f"Staged imports: {summary.pending_files} pending, {summary.failed_files} failed.",
            name="repository_staged_imports",
        ), dict(summary.metadata)
    except Exception:
        return CheckResult(
            "error",
            "Staged import diagnostics are unavailable.",
            name="repository_staged_imports",
        ), {"authority": "observed_staged_files", "state": "unavailable"}
