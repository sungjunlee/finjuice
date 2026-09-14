"""Stable workbook metadata and ZIP packaging for repository-derived exports."""

from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import polars as pl


def write_deterministic_xlsx(frame: pl.DataFrame, output_path: Path) -> None:
    """Write identical workbook bytes for identical frames in the same environment."""
    import xlsxwriter

    buffer = io.BytesIO()
    with xlsxwriter.Workbook(buffer) as workbook:
        workbook.set_properties({"created": datetime(2000, 1, 1)})
        frame.write_excel(workbook=workbook, worksheet="Transactions")
    with ZipFile(buffer) as source, ZipFile(output_path, "w", compression=ZIP_DEFLATED) as target:
        for name in sorted(source.namelist()):
            info = ZipInfo(name, date_time=(2000, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.create_system = 0
            info.external_attr = 0o600 << 16
            target.writestr(info, source.read(name))
