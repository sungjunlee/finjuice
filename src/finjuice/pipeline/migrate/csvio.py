"""String-preserving CSV readers for frozen migration inputs."""

from __future__ import annotations

import csv
from pathlib import Path


def read_csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    """Read a CSV file as ordered string rows, including unknown columns.

    Empty cells stay empty strings. Completely empty files return no rows.
    """
    text = path.read_text(encoding="utf-8-sig")
    if not text.strip():
        return [], []
    reader = csv.reader(text.splitlines())
    try:
        headers = next(reader)
    except StopIteration:
        return [], []
    rows: list[dict[str, str]] = []
    for values in reader:
        row: dict[str, str] = {}
        for index, header in enumerate(headers):
            row[header] = values[index] if index < len(values) else ""
        if len(values) > len(headers):
            for extra_index, value in enumerate(values[len(headers) :]):
                row[f"_extra_{extra_index}"] = value
        rows.append(row)
    return headers, rows
