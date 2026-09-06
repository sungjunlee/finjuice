"""Structure tests for the detection.py candidate-pairing helper split.

``detect_transfer_pairs`` lives in ``detection_cluster`` and must stay
identity-equal when re-exported from ``detection``, so existing import paths
and monkeypatches keep working after the split. The split also keeps
``detection_cluster`` as the single canonical home for the moved cluster.
CSV orchestration stays in ``detection``. Pairing-scoring helpers stay in
``detection_helpers``. Candidate construction stays in ``detection_candidates``.
"""

from __future__ import annotations

import importlib
from pathlib import Path

TRANSFER_DIR = Path("src/finjuice/pipeline/transfer")


def test_detection_reexports_pairing_cluster_identity() -> None:
    """Candidate pairing stays on detection as a re-export after the split."""
    detection = importlib.import_module("finjuice.pipeline.transfer.detection")
    cluster = importlib.import_module("finjuice.pipeline.transfer.detection_cluster")

    assert detection.detect_transfer_pairs is cluster.detect_transfer_pairs
    assert callable(detection.run_transfer_detection)
    assert "detect_transfer_pairs" in detection.__all__


def test_detection_cluster_is_the_unique_home_for_moved_helpers() -> None:
    """The moved cluster is defined exactly once, in detection_cluster."""
    detection = importlib.import_module("finjuice.pipeline.transfer.detection")
    cluster = importlib.import_module("finjuice.pipeline.transfer.detection_cluster")
    canonical = "finjuice.pipeline.transfer.detection_cluster"

    assert cluster.detect_transfer_pairs.__module__ == canonical
    assert detection.detect_transfer_pairs.__module__ == canonical
    assert detection.run_transfer_detection.__module__ == "finjuice.pipeline.transfer.detection"


def test_pairing_cluster_lives_in_cluster_module() -> None:
    """Candidate pairing should not live in the detection entry module."""
    detection_text = (TRANSFER_DIR / "detection.py").read_text(encoding="utf-8")
    cluster_text = (TRANSFER_DIR / "detection_cluster.py").read_text(encoding="utf-8")
    helpers_text = (TRANSFER_DIR / "detection_helpers.py").read_text(encoding="utf-8")
    candidates_text = (TRANSFER_DIR / "detection_candidates.py").read_text(encoding="utf-8")

    assert "def run_transfer_detection" in detection_text
    assert "def detect_transfer_pairs" not in detection_text
    assert "def detect_transfer_pairs" in cluster_text
    assert "def run_transfer_detection" not in cluster_text

    assert "def _sign_rank" not in cluster_text
    assert "def _candidate_order_key" not in cluster_text
    assert "def _pair_order_key" not in cluster_text
    assert "def _build_pair_candidate" not in cluster_text
    assert "class _TransferPairCandidate" not in cluster_text
    assert "def _sign_rank" in helpers_text
    assert "class TransferCandidate" not in cluster_text
    assert "def _build_transfer_candidates" not in cluster_text
    assert "class TransferCandidate" in candidates_text
    assert "def _build_transfer_candidates" in candidates_text

    assert "detect_transfer_pairs" in detection_text
