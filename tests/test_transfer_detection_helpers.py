"""Identity tests for the transfer detection helper split."""

from pathlib import Path

from finjuice.pipeline.transfer import detection, detection_helpers

TRANSFER_DIR = Path("src/finjuice/pipeline/transfer")


def test_pairing_helpers_live_in_helper_module() -> None:
    """Pairing-scoring helpers should not live in the detection module itself."""
    detection_text = (TRANSFER_DIR / "detection.py").read_text(encoding="utf-8")
    helpers_text = (TRANSFER_DIR / "detection_helpers.py").read_text(encoding="utf-8")

    assert "def detect_transfer_pairs" in detection_text
    assert "def run_transfer_detection" in detection_text
    assert "def _sign_rank" not in detection_text
    assert "def _candidate_order_key" not in detection_text
    assert "def _pair_order_key" not in detection_text
    assert "def _build_pair_candidate" not in detection_text
    assert "class _TransferPairCandidate" not in detection_text
    assert "def _sign_rank" in helpers_text
    assert "def _candidate_order_key" in helpers_text
    assert "def _pair_order_key" in helpers_text
    assert "def _build_pair_candidate" in helpers_text
    assert "class _TransferPairCandidate" in helpers_text


def test_pairing_helpers_reexport_from_detection() -> None:
    """Existing detection imports should keep resolving to the pairing helpers."""
    assert detection._sign_rank is detection_helpers._sign_rank
    assert detection._candidate_order_key is detection_helpers._candidate_order_key
    assert detection._pair_order_key is detection_helpers._pair_order_key
    assert detection._build_pair_candidate is detection_helpers._build_pair_candidate
    assert detection._TransferPairCandidate is detection_helpers._TransferPairCandidate
    assert detection.CandidateOrderKey is detection_helpers.CandidateOrderKey
    assert detection.PairOrderKey is detection_helpers.PairOrderKey
    assert callable(detection.detect_transfer_pairs)
    assert callable(detection.run_transfer_detection)
