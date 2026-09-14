"""Revision-pinned portfolio display inputs with explicit calculation readiness."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from finjuice.pipeline.consumer_bundle import (
    OVERLAY_OUTPUT,
    ConsumerBundleError,
    LegacyConsumerBundle,
    _bundle,
    _canonical,
    _digest,
    _overlay_file,
    _publish,
    _reject_staging_symlinks,
    _reuse_complete,
    _validated_output,
)
from finjuice.pipeline.portfolio_display import PortfolioDisplay, PortfolioDisplayError
from finjuice.pipeline.storage.sqlite.portfolio_reads import PortfolioReadSnapshot
from finjuice.pipeline.storage.sqlite.repository import RepositoryReader

BUNDLE_FORMAT = "finjuice.portfolio-consumer-bundle.v1"
_DOMAINS = {
    "balance": ("balance", ("amount",)),
    "investment": ("investments", ("principal_amount", "valuation_amount")),
    "loan": ("loans", ("balance_amount",)),
}


def materialize_portfolio_consumer_bundle(
    reader: RepositoryReader,
    output_root: Path,
    *,
    data_dir: Path | None = None,
    source_roots: tuple[Path, ...] = (),
) -> LegacyConsumerBundle:
    """Publish native-aware display CSVs from one snapshot, never live source CSV.

    Readiness applies to the declared report inputs, not current household wealth.
    Exact numbers, per-value currencies and unconverted rate units remain sidecars.
    Captured overlay bytes are authenticated but their freshness is not inferred.
    """
    snapshot = reader.portfolio_snapshot()
    output = _validated_output(output_root, reader.paths, data_dir, source_roots)
    display = PortfolioDisplay(snapshot)
    files: dict[str, bytes] = {}
    domains: dict[str, Any] = {}
    try:
        for kind, (directory, amounts) in _DOMAINS.items():
            months = getattr(display, f"{kind}_months")
            partitions = getattr(display, f"{kind}_partition")
            frames = {month: partitions(month) for month in months}
            schema = (
                pl.concat(
                    [frame.clear() for frame in frames.values()], how="diagonal_relaxed"
                ).schema
                if frames
                else {}
            )
            last_rows: list[dict[str, Any]] = []
            row_count = 0
            for month, frame in frames.items():
                assert frame is not None
                frame = (
                    frame.with_columns(
                        pl.lit(None, dtype=dtype).alias(name)
                        for name, dtype in schema.items()
                        if name not in frame.columns
                    )
                    .select(list(schema))
                    .cast(schema)
                )
                relative = f"banksalad/{directory}/{month.replace('-', '/')}/{directory}.csv"
                files[relative] = frame.write_csv().encode("utf-8")
                # JSON keeps integer/string exact sidecars independent of CSV type inference.
                files[relative + ".exact.json"] = _canonical({"rows": frame.to_dicts()})
                row_count += frame.height
                last_rows = frame.to_dicts()
            dates = [date.fromisoformat(row["snapshot_date"]).isoformat() for row in last_rows]
            as_of = max(dates) if dates else None
            selected = [row for row in last_rows if row["snapshot_date"] == as_of]
            reasons = _readiness(kind, selected, amounts)
            source_count = _selected_source_count(snapshot, selected)
            if source_count > 1:
                reasons.add("multiple_selected_report_sources")
            coverage = _native_coverage(snapshot, kind, as_of)
            if coverage["unrepresented_projection_count"]:
                reasons.add("unrepresented_native_projection")
            if coverage["unmapped_fact_count"]:
                reasons.add("unmapped_native_overview")
            domains[kind] = {
                "months": list(months),
                "as_of": as_of,
                "row_count": row_count,
                "selected_row_count": len(selected),
                "readiness": "usable" if not reasons else "incomplete",
                "reasons": sorted(reasons),
                "coverage": {
                    "scope": "typed_primary_and_native_reports",
                    "selected_report_source_count": source_count,
                    **coverage,
                },
            }
    except (PortfolioDisplayError, KeyError, TypeError, ValueError) as exc:
        raise ConsumerBundleError(
            "Portfolio projection evidence is incomplete or invalid."
        ) from exc

    scopes = reader.capture_file_scopes()
    artifacts = {row["source_artifact_id"]: row for row in reader.rows("source_artifacts")}
    occurrences = {row["entity_id"]: row for row in reader.rows("source_occurrences")}
    overlay = _overlay_file(scopes, occurrences, artifacts, reader.paths)
    overlay_identity: dict[str, Any] = {"presence": "absent", "as_of": None}
    if overlay is not None:
        files[OVERLAY_OUTPUT] = overlay[0]
        overlay_identity = {
            **overlay[1],
            "sha256": _digest(overlay[0]),
            "byte_count": len(overlay[0]),
            "as_of": None,
        }
    native_occurrences = {
        row["entity_id"]
        for row in snapshot.evidence["source_occurrences"]
        if row["occurrence_kind"] != "legacy_capture"
    }
    provenance = {row["provenance_id"]: row for row in snapshot.evidence["record_provenance"]}
    uncovered_assets = sum(
        provenance[row["provenance_id"]]["source_occurrence_id"] in native_occurrences
        for row in snapshot.asset_snapshots
    )
    domain_ready = all(domain["readiness"] == "usable" for domain in domains.values())
    usable = domain_ready and uncovered_assets == 0
    manifest = {
        "format": BUNDLE_FORMAT,
        "materialization_policy": "portfolio_display_inputs.v1",
        **display.metadata(),
        "domains": domains,
        "source_identities": {"overlay": overlay_identity},
        "readiness": {
            "decision": "usable_for_declared_report_inputs" if usable else "incomplete",
            "complete_report_usable": usable,
            "scope": "declared_report_inputs_excluding_manual_overlay",
            "uncovered_native_asset_snapshots": uncovered_assets,
            "overlay": {"freshness": "unverified", "calculation_coverage": "not_assessed"},
            "current_household_coverage": "unverified",
        },
        "limitations": [
            "no_owner_inference",
            "no_currency_conversion",
            "no_rate_unit_conversion",
            "no_snapshot_to_overview_inference",
            "captured_overlay_freshness_unverified",
            "independent_report_sources_require_explicit_disjointness_evidence",
        ],
        "outputs": {
            path: {"sha256": _digest(content), "byte_count": len(content)}
            for path, content in files.items()
        },
    }
    if output.exists():
        _reject_staging_symlinks(output)
        return _reuse_complete(output, snapshot, files, manifest)
    _publish(output, files, manifest)
    return _bundle(output, files, manifest)


def _readiness(kind: str, rows: list[dict[str, Any]], amounts: tuple[str, ...]) -> set[str]:
    reasons: set[str] = set()
    if not rows:
        reasons.add("no_selected_rows")
    for row in rows:
        for field in amounts:
            prefix = "" if kind == "balance" else field + "_"
            if row.get(field) is None:
                reasons.add("missing_amount")
            if row.get(prefix + "currency_unknown") != 0:
                reasons.add("unknown_currency")
            if row.get(prefix + "currency") != "KRW":
                reasons.add("non_krw_or_missing_currency")
        if kind != "balance" and any(not row.get(key) for key in ("institution", "product_name")):
            reasons.add("missing_report_identity_fields")
        rate = {"investment": "return_rate", "loan": "interest_rate"}.get(kind)
        if rate is not None and row.get(rate) is not None:
            # The source-only rate contract deliberately does not choose percent vs fraction.
            reasons.add("rate_unit_not_normalized_for_percentage_consumer")
        if kind == "balance" and row.get("side") not in {"asset", "liability"}:
            reasons.add("unsupported_balance_side")
    return reasons


def _native_coverage(
    snapshot: PortfolioReadSnapshot, kind: str, as_of: str | None
) -> dict[str, int]:
    """Count preserved but unrepresented selected/newer native overview fragments."""
    native = {
        row["entity_id"]
        for row in snapshot.evidence["source_occurrences"]
        if row["occurrence_kind"] == "exact_xlsx_import"
    }
    dates: dict[str, list[str]] = {}
    unknown_dates: set[str] = set()
    overview_observations = {row["observation_id"] for row in snapshot.overview_facts}
    for observation in snapshot.evidence["observations"]:
        if observation["entity_id"] not in overview_observations:
            continue
        if observation["effective_at"] is not None:
            dates.setdefault(observation["source_occurrence_id"], []).append(
                observation["effective_at"][:10]
            )
        else:
            unknown_dates.add(observation["source_occurrence_id"])
    table = {"balance": "balances", "investment": "investments", "loan": "loans"}[kind]
    represented = {
        row["provenance_id"] for row in snapshot.native_overview_reports[f"overview_{table}"]
    }
    payloads = {row["provenance_id"]: row for row in snapshot.evidence["legacy_payloads"]}
    missing = unmapped = 0
    for provenance in snapshot.evidence["record_provenance"]:
        occurrence = provenance["source_occurrence_id"]
        if occurrence not in native:
            continue
        observed = dates.get(occurrence, [])
        if (
            as_of is not None
            and observed
            and occurrence not in unknown_dates
            and max(observed) < as_of
        ):
            continue
        coordinate = _object(provenance["source_coordinate_json"])
        family = coordinate.get("family")
        if family == f"overview_{kind}" and provenance["provenance_id"] not in represented:
            missing += 1
        if family == "overview_fact":
            payload = payloads.get(provenance["provenance_id"])
            if payload is None or _object(payload["payload_json"]).get("typed") is not True:
                unmapped += 1
    return {"unrepresented_projection_count": missing, "unmapped_fact_count": unmapped}


def _object(content: str) -> dict[str, Any]:
    parsed = json.loads(content)
    if not isinstance(parsed, dict):
        raise ConsumerBundleError("Portfolio JSON evidence is not an object.")
    return parsed


def _selected_source_count(snapshot: PortfolioReadSnapshot, rows: list[dict[str, Any]]) -> int:
    """Do not infer disjoint account coverage from names or deduplicate source rows.

    Allowing multiple report sources would require explicit, independently verified
    account/report coverage and non-overlap assertions, or an authoritative replacement
    relation selecting one report. Current inputs supply neither contract. A captured
    file's multiple row observations remain one report; native snapshot observations
    remain distinct even when imported in the same workbook.
    """
    provenance = {row["provenance_id"]: row for row in snapshot.evidence["record_provenance"]}
    return len(
        {
            (
                row["source_basis"],
                provenance[row["provenance_id"]]["source_occurrence_id"],
                row["observation_id"] if row["source_basis"] == "native" else None,
            )
            for row in rows
        }
    )
