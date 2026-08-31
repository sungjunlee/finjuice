"""Identity tests for the transfer candidate-construction helper split (Issue #333)."""

from datetime import datetime
from pathlib import Path

import polars as pl

from finjuice.pipeline.transfer import detection, detection_candidates

TRANSFER_DIR = Path("src/finjuice/pipeline/transfer")


def test_candidate_helpers_live_in_candidates_module() -> None:
    """Candidate model and row parsing should not live in the detection module itself."""
    detection_text = (TRANSFER_DIR / "detection.py").read_text(encoding="utf-8")
    candidates_text = (TRANSFER_DIR / "detection_candidates.py").read_text(encoding="utf-8")

    assert "def detect_transfer_pairs" in detection_text
    assert "def run_transfer_detection" in detection_text
    assert "class TransferCandidate" not in detection_text
    assert "def _build_transfer_candidates" not in detection_text
    assert "class TransferCandidate" in candidates_text
    assert "def _build_transfer_candidates" in candidates_text


def test_candidate_helpers_reexport_from_detection() -> None:
    """Existing detection imports should keep resolving to the candidate helpers."""
    assert detection.TransferCandidate is detection_candidates.TransferCandidate
    assert detection._build_transfer_candidates is detection_candidates._build_transfer_candidates
    assert "TransferCandidate" in detection.__all__
    assert "_build_transfer_candidates" in detection.__all__
    assert callable(detection.detect_transfer_pairs)
    assert callable(detection.run_transfer_detection)


def test_build_transfer_candidates_keeps_row_parsing_behavior() -> None:
    """The extracted builder keeps parsing valid rows and counting skipped ones."""
    df = pl.DataFrame(
        {
            "datetime": ["2025-01-15T14:30:00", "", "not-a-date"],
            "amount": [-50000, 50000, 10000],
            "account": ["신한카드", "우리은행", "A"],
            "merchant_raw": ["이체", "입금", "이체"],
            "major_raw": ["내계좌이체", "내계좌이체", "내계좌이체"],
            "currency": ["KRW", "KRW", "KRW"],
            "row_hash": ["hash_a", "hash_b", "hash_c"],
        }
    )

    candidates, skipped = detection_candidates._build_transfer_candidates(df)

    assert skipped == 2
    assert len(candidates) == 1
    assert candidates[0] == detection.TransferCandidate(
        id=0,
        datetime=datetime(2025, 1, 15, 14, 30),
        amount=-50000.0,
        account="신한카드",
        counterparty="이체",
        major_category="내계좌이체",
        currency="KRW",
        row_hash="hash_a",
    )
