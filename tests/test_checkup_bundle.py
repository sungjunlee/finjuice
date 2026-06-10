"""Focused tests for the unified read-only checkup bundle."""

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

import polars as pl

from finjuice.pipeline.checkup import collect_checkup_bundle
from finjuice.pipeline.config import Config


def _init_data_dir(tmp_path: Path, name: str = "data") -> Path:
    """Create a minimal initialized finjuice data directory."""
    data_dir = tmp_path / name
    data_dir.mkdir()
    (data_dir / "imports").mkdir()
    (data_dir / "transactions").mkdir()
    (data_dir / "exports").mkdir()
    (data_dir / "metadata").mkdir()
    (data_dir / "rules.yaml").write_text("version: 1\nrules: []\n", encoding="utf-8")
    return data_dir


def _write_transactions(data_dir: Path, month: str, rows: list[dict[str, object]]) -> None:
    """Write one transaction partition for tests."""
    year, mon = month.split("-")
    partition_dir = data_dir / "transactions" / year / mon
    partition_dir.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(rows).write_csv(partition_dir / "transactions.csv")


def _write_snapshot(data_dir: Path, month: str, rows: list[dict[str, object]]) -> None:
    """Write one asset snapshot partition for tests."""
    year, mon = month.split("-")
    partition_dir = data_dir / "assets" / "snapshots" / year / mon
    partition_dir.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(rows).write_csv(partition_dir / "snapshots.csv")


def _month_labels(start_year: int, start_month: int, count: int) -> list[str]:
    """Return count YYYY-MM labels starting at year/month."""
    labels: list[str] = []
    year = start_year
    month = start_month
    for _ in range(count):
        labels.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            year += 1
            month = 1
    return labels


def _tx_row(
    tx_date: str,
    amount: float,
    merchant: str,
    *,
    category_final: str,
    tags_final: str,
    needs_review: int = 0,
    confidence: float | None = 0.95,
    type_norm: str = "expense",
    type_raw: str = "지출",
    is_transfer: int = 0,
    row_hash: str | None = None,
) -> dict[str, object]:
    """Build a canonical transaction row for checkup tests."""
    row_id = row_hash or f"{tx_date}-{merchant}-{int(amount)}"
    time_value = "09:00" if amount >= 0 else "13:00"
    return {
        "row_hash": row_id,
        "date": tx_date,
        "time": time_value,
        "datetime": f"{tx_date}T{time_value}:00",
        "type_raw": type_raw,
        "type_norm": type_norm,
        "major_raw": category_final,
        "minor_raw": category_final,
        "merchant_raw": merchant,
        "memo_raw": None,
        "amount": amount,
        "account": "테스트계좌",
        "currency": "KRW",
        "counterparty": None,
        "category_rule": category_final,
        "category_final": category_final,
        "tags_rule": tags_final,
        "tags_ai": "[]",
        "tags_manual": "[]",
        "tags_final": tags_final,
        "confidence": confidence,
        "needs_review": needs_review,
        "is_transfer": is_transfer,
        "transfer_group_id": None,
        "file_id": "fixture_1",
        "source_row": 1,
    }


def test_collect_checkup_bundle_empty_state_is_explicit_and_actionable(tmp_path: Path) -> None:
    """Empty data/config state should be represented explicitly without exceptions."""
    data_dir = _init_data_dir(tmp_path, "empty")
    bundle = collect_checkup_bundle(Config(data_dir=data_dir), today=date(2026, 4, 18))

    assert bundle.actionable is True
    assert bundle.pipeline.status == "empty"
    assert bundle.pipeline.pending_import_status == "clear"
    assert bundle.pipeline.pending_import_files == 0
    assert bundle.pipeline.failed_import_files == 0
    assert bundle.review.status == "empty"
    assert bundle.budget.status == "missing_config"
    assert bundle.networth.status == "missing_data"
    assert bundle.warnings == [
        "No transaction partitions found. Import data before running the pipeline loop.",
        "goals.yaml not found. Budget posture is unconfigured.",
        "No asset snapshots or assets.yaml entries found for net worth posture.",
    ]
    assert [action.command for action in bundle.next_actions] == [
        "finjuice import <banksalad.xlsx>",
        "finjuice budget edit --set total=<monthly_budget> --yes",
        "finjuice networth init",
    ]


def test_collect_checkup_bundle_healthy_state_is_quiet(tmp_path: Path) -> None:
    """Recent data with no review pressure and healthy budgets should stay quiet."""
    data_dir = _init_data_dir(tmp_path, "healthy")
    _write_transactions(
        data_dir,
        "2026-04",
        [
            _tx_row(
                "2026-04-05",
                3_500_000.0,
                "회사",
                category_final="급여",
                tags_final='["급여"]',
                type_norm="income",
                type_raw="입금",
            ),
            _tx_row(
                "2026-04-08",
                -90_000.0,
                "마트",
                category_final="식비",
                tags_final='["식비"]',
            ),
            _tx_row(
                "2026-04-10",
                -20_000.0,
                "버스",
                category_final="교통",
                tags_final='["교통"]',
            ),
            _tx_row(
                "2026-04-12",
                -30_000.0,
                "카페",
                category_final="카페",
                tags_final='["카페"]',
            ),
        ],
    )
    (data_dir / "goals.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "net_worth_target: 100000000",
                "monthly_budget:",
                "  total: 300000",
                "  categories:",
                "    식비: 150000",
                "    교통: 60000",
                "    카페: 50000",
                "",
            ]
        ),
        encoding="utf-8",
    )
    _write_snapshot(
        data_dir,
        "2026-04",
        [
            {
                "snapshot_date": "2026-04-15",
                "account_id": "증권",
                "instrument_id": "인덱스펀드",
                "quantity": 1.0,
                "market_value": 200000000.0,
                "currency": "KRW",
                "file_id": "fixture_1",
                "source_row": 1,
            }
        ],
    )
    (data_dir / "assets.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "manual_assets:",
                "  - name: 비상금",
                "    category: cash",
                "    value: 20000000",
                "liabilities:",
                "  - name: 마이너스통장",
                "    principal: 10000000",
                "",
            ]
        ),
        encoding="utf-8",
    )

    bundle = collect_checkup_bundle(Config(data_dir=data_dir), today=date(2026, 4, 18))

    assert bundle.actionable is False
    assert bundle.warnings == []
    assert bundle.next_actions == []
    assert bundle.pipeline.status == "healthy"
    assert bundle.pipeline.pending_import_status == "clear"
    assert bundle.pipeline.pending_import_files == 0
    assert bundle.pipeline.failed_import_files == 0
    assert bundle.pipeline.days_since_latest == 6
    assert bundle.review.status == "healthy"
    assert bundle.review.total_candidates == 0
    assert bundle.review.low_confidence_count == 0
    assert bundle.budget.status == "healthy"
    assert bundle.budget.summary is not None
    assert bundle.budget.summary.actual == 140000
    assert bundle.budget.summary.status == "under"
    assert bundle.networth.status == "on_target"
    assert bundle.networth.net_worth == 210000000.0


def test_collect_checkup_bundle_pending_imports_trigger_refresh(tmp_path: Path) -> None:
    """Staged import files should make the pipeline summary actionable."""
    data_dir = _init_data_dir(tmp_path, "pending-imports")
    _write_transactions(
        data_dir,
        "2026-04",
        [
            _tx_row(
                "2026-04-12",
                -30_000.0,
                "카페",
                category_final="카페",
                tags_final='["카페"]',
            ),
        ],
    )
    (data_dir / "goals.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "monthly_budget:",
                "  total: 100000",
                "  categories:",
                "    카페: 50000",
                "",
            ]
        ),
        encoding="utf-8",
    )
    _write_snapshot(
        data_dir,
        "2026-04",
        [
            {
                "snapshot_date": "2026-04-15",
                "account_id": "증권",
                "instrument_id": "인덱스펀드",
                "quantity": 1.0,
                "market_value": 200000000.0,
                "currency": "KRW",
                "file_id": "fixture_1",
                "source_row": 1,
            }
        ],
    )
    (data_dir / "assets.yaml").write_text(
        "version: 1\nmanual_assets: []\nliabilities: []\n",
        encoding="utf-8",
    )
    shutil.copy(
        Path(__file__).resolve().parent / "fixtures" / "sample_banksalad.xlsx",
        data_dir / "imports" / "staged.xlsx",
    )

    bundle = collect_checkup_bundle(Config(data_dir=data_dir), today=date(2026, 4, 18))

    assert bundle.actionable is True
    assert bundle.pipeline.status == "pending_imports"
    assert bundle.pipeline.pending_import_status == "present"
    assert bundle.pipeline.pending_import_files == 1
    assert bundle.pipeline.failed_import_files == 0
    assert bundle.warnings == ["1 staged import file(s) are waiting in imports/."]
    assert bundle.next_actions[0].domain == "pipeline"
    assert bundle.next_actions[0].command == "finjuice refresh"


def test_collect_checkup_bundle_failed_import_preview_needs_investigation(tmp_path: Path) -> None:
    """Preview failures should not be reported as refreshable pending imports."""
    data_dir = _init_data_dir(tmp_path, "failed-imports")
    (data_dir / "imports" / "broken.xlsx").write_text("not-a-valid-xlsx", encoding="utf-8")

    bundle = collect_checkup_bundle(Config(data_dir=data_dir), today=date(2026, 4, 18))

    assert bundle.actionable is True
    assert bundle.pipeline.status == "import_failures"
    assert bundle.pipeline.pending_import_status == "clear"
    assert bundle.pipeline.pending_import_files == 0
    assert bundle.pipeline.failed_import_files == 1
    assert bundle.warnings[0] == "1 staged import file(s) failed preview validation."
    assert bundle.next_actions[0].domain == "pipeline"
    assert bundle.next_actions[0].command == "finjuice doctor"


def test_collect_checkup_bundle_mixed_import_preview_surfaces_failure_first(tmp_path: Path) -> None:
    """Failed staged files should stay visible even when other imports are refreshable."""
    data_dir = _init_data_dir(tmp_path, "mixed-imports")
    shutil.copy(
        Path(__file__).resolve().parent / "fixtures" / "sample_banksalad.xlsx",
        data_dir / "imports" / "staged.xlsx",
    )
    (data_dir / "imports" / "broken.xlsx").write_text("not-a-valid-xlsx", encoding="utf-8")

    bundle = collect_checkup_bundle(Config(data_dir=data_dir), today=date(2026, 4, 18))

    assert bundle.actionable is True
    assert bundle.pipeline.status == "import_failures"
    assert bundle.pipeline.pending_import_status == "present"
    assert bundle.pipeline.pending_import_files == 1
    assert bundle.pipeline.failed_import_files == 1
    assert bundle.warnings[0] == (
        "1 staged import file(s) failed preview validation. "
        "1 additional staged import file(s) are ready for refresh."
    )
    assert [action.command for action in bundle.next_actions[:2]] == [
        "finjuice doctor",
        "finjuice refresh",
    ]


def test_collect_checkup_bundle_flags_attention_across_domains(tmp_path: Path) -> None:
    """Stale data, review backlog, over-budget spend, and negative net worth should surface."""
    data_dir = _init_data_dir(tmp_path, "attention")
    _write_transactions(
        data_dir,
        "2026-01",
        [
            _tx_row(
                "2026-01-10",
                2_000_000.0,
                "회사",
                category_final="급여",
                tags_final='["급여"]',
                type_norm="income",
                type_raw="입금",
            ),
            _tx_row(
                "2026-01-12",
                -105_000.0,
                "마트",
                category_final="식비",
                tags_final='["식비"]',
            ),
            _tx_row(
                "2026-01-15",
                -30_000.0,
                "병원",
                category_final="의료",
                tags_final='["의료"]',
            ),
            _tx_row(
                "2026-01-20",
                -15_000.0,
                "미확인 가맹점",
                category_final="미분류",
                tags_final="[]",
                needs_review=1,
                confidence=0.42,
            ),
            _tx_row(
                "2026-01-21",
                -22_000.0,
                "태그됐지만 신뢰도 낮음",
                category_final="식비",
                tags_final='["식비"]',
                confidence=0.31,
            ),
            _tx_row(
                "2026-01-22",
                -18_000.0,
                "신뢰도 누락",
                category_final="생활",
                tags_final='["생활"]',
                confidence=None,
            ),
            _tx_row(
                "2026-01-23",
                -9_000.0,
                "추가 후보",
                category_final="교통",
                tags_final='["교통"]',
                confidence=0.6,
            ),
        ],
    )
    (data_dir / "goals.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "monthly_budget:",
                "  total: 100000",
                "  categories:",
                "    식비: 100000",
                "",
            ]
        ),
        encoding="utf-8",
    )
    _write_snapshot(
        data_dir,
        "2026-01",
        [
            {
                "snapshot_date": "2026-01-31",
                "account_id": "증권",
                "instrument_id": "ETF",
                "quantity": 1.0,
                "market_value": 20000000.0,
                "currency": "KRW",
                "file_id": "fixture_1",
                "source_row": 1,
            }
        ],
    )
    (data_dir / "assets.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "liabilities:",
                "  - name: 대출",
                "    principal: 40000000",
                "",
            ]
        ),
        encoding="utf-8",
    )

    bundle = collect_checkup_bundle(Config(data_dir=data_dir), today=date(2026, 4, 18))

    assert bundle.actionable is True
    assert bundle.warnings == []
    assert bundle.pipeline.status == "stale"
    assert bundle.pipeline.days_since_latest == 85
    assert bundle.review.status == "needs_attention"
    assert bundle.review.total_candidates == 4
    assert bundle.review.low_confidence_count == 4
    assert len(bundle.review.samples) == 3
    assert [sample.merchant for sample in bundle.review.samples] == [
        "추가 후보",
        "신뢰도 누락",
        "태그됐지만 신뢰도 낮음",
    ]
    assert [sample.reasons for sample in bundle.review.samples] == [
        ["low_confidence"],
        ["low_confidence"],
        ["low_confidence"],
    ]
    assert bundle.budget.status == "needs_attention"
    assert bundle.budget.summary is not None
    assert bundle.budget.summary.actual == 199000
    assert bundle.budget.over_budget_categories == ["식비"]
    assert bundle.budget.unbudgeted_categories == ["의료", "생활", "미분류", "교통"]
    assert bundle.networth.status == "negative"
    assert bundle.networth.net_worth == -20000000.0
    assert [action.command for action in bundle.next_actions] == [
        "finjuice budget status --json",
        "finjuice review --json",
        "finjuice networth --json",
        "finjuice refresh",
    ]


def test_collect_checkup_bundle_surfaces_large_recurring_obligation_candidates(
    tmp_path: Path,
) -> None:
    """Large monthly outflows should surface without income, transfer, or irregular noise."""
    data_dir = _init_data_dir(tmp_path, "recurring-obligations")
    months = _month_labels(2025, 4, 13)
    irregular_months = set(months[::2])

    for month in months:
        tx_date = f"{month}-05"
        rows = [
            _tx_row(
                tx_date,
                -450_000.0,
                "주담대 1234-5678",
                category_final="대출",
                tags_final='["대출"]',
            ),
            _tx_row(
                tx_date,
                -250_000.0,
                "소액구독",
                category_final="구독",
                tags_final='["구독"]',
            ),
            _tx_row(
                tx_date,
                500_000.0,
                "급여성입금",
                category_final="수입",
                tags_final='["수입"]',
                type_norm="income",
                type_raw="입금",
            ),
            _tx_row(
                tx_date,
                -700_000.0,
                "내계좌이체",
                category_final="이체",
                tags_final='["이체"]',
                type_norm="transfer",
                type_raw="이체",
                is_transfer=1,
            ),
        ]
        if month in irregular_months:
            rows.append(
                _tx_row(
                    tx_date,
                    -520_000.0,
                    "불규칙보험",
                    category_final="보험",
                    tags_final='["보험"]',
                )
            )
        _write_transactions(data_dir, month, rows)

    bundle = collect_checkup_bundle(Config(data_dir=data_dir), today=date(2026, 5, 5))

    assert bundle.obligations.status == "needs_confirmation"
    assert bundle.obligations.actionable is True
    assert bundle.obligations.threshold_monthly_krw == 300_000
    assert bundle.obligations.candidate_count == 1
    candidate = bundle.obligations.candidates[0]
    assert candidate.label == "주담대 #"
    assert candidate.cadence == "monthly"
    assert candidate.amount_range == {"min": 450_000, "max": 450_000}
    assert candidate.average_monthly_amount == 450_000
    assert candidate.active_month_count == 13
    assert candidate.active_months == months
    assert candidate.transaction_count == 13
    assert "known_obligations" in candidate.suggested_confirmation_question
    assert "1234" not in candidate.label
    assert {action.domain for action in bundle.next_actions} >= {"obligations"}
