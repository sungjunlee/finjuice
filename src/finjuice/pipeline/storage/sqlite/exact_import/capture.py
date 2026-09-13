"""Capture workbook bytes once and bind them to raw evidence."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from finjuice.pipeline.ingest.xlsx_evidence import (
    DEFAULT_EVIDENCE_LIMITS,
    EvidenceLimits,
    WorkbookEvidence,
    _load_source,
    read_workbook_evidence,
)


@dataclass(frozen=True)
class ExactWorkbookCapture:
    """Immutable bytes, digest, filename, and evidence from one capture."""

    source_bytes: bytes
    digest_hex: str
    byte_length: int
    filename: str | None
    evidence: WorkbookEvidence

    def __post_init__(self) -> None:
        if self.byte_length != len(self.source_bytes):
            raise ValueError("Captured byte length does not match source bytes.")
        if self.digest_hex != hashlib.sha256(self.source_bytes).hexdigest():
            raise ValueError("Captured digest does not match source bytes.")
        if self.evidence.source_sha256 != self.digest_hex:
            raise ValueError("Workbook evidence digest does not match captured bytes.")
        if self.evidence.source_size != self.byte_length:
            raise ValueError("Workbook evidence size does not match captured bytes.")

    @property
    def artifact_id(self) -> str:
        """Return the content-addressed artifact identity for these bytes."""
        return f"sha256:{self.digest_hex}"


def capture_exact_xlsx(
    source: Path | bytes,
    *,
    filename: str | None = None,
    limits: EvidenceLimits = DEFAULT_EVIDENCE_LIMITS,
) -> ExactWorkbookCapture:
    """Read source bytes once, then derive evidence from those same bytes."""
    path = source if isinstance(source, Path) else None
    data = _load_source(source, limits)
    evidence = read_workbook_evidence(data, limits=limits)
    return ExactWorkbookCapture(
        source_bytes=data,
        digest_hex=hashlib.sha256(data).hexdigest(),
        byte_length=len(data),
        filename=_capture_filename(path, filename),
        evidence=evidence,
    )


def _capture_filename(path: Path | None, filename: str | None) -> str | None:
    if filename is not None:
        return filename
    if path is None:
        return None
    return path.name
