"""CSV occurrences with original quoting, column order and missing-cell states."""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator
from typing import Any


def tokens(record: str) -> list[str]:
    """Retain lexical CSV cells, including quoted versus unquoted empty cells."""
    record = record.removesuffix("\n").removesuffix("\r")
    quoted = False
    start = 0
    result = []
    index = 0
    while index < len(record):
        char = record[index]
        if char == '"' and (quoted or index == start):
            if quoted and index + 1 < len(record) and record[index + 1] == '"':
                index += 1
            else:
                quoted = not quoted
        elif char == "," and not quoted:
            result.append(record[start:index])
            start = index + 1
        index += 1
    result.append(record[start:])
    return result


def rows(data: bytes) -> Iterator[tuple[int, dict[str, Any], dict[str, str | None] | None]]:
    text = data.decode("utf-8-sig")
    lines = io.StringIO(text, newline="").readlines()
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    header = next(reader, None)
    if not header or any(name == "" for name in header):
        raise csv.Error("Missing CSV header")
    previous = reader.line_num
    for ordinal, values in enumerate(reader, 1):
        raw = "".join(lines[previous : reader.line_num])
        previous = reader.line_num
        lexical = tokens(raw)
        cells: list[dict[str, Any]] = [
            {
                "column": name,
                "column_ordinal": index,
                "state": _cell_state(index, values, lexical),
                "value": values[index] if index < len(values) else None,
                "lexical": lexical[index] if index < len(lexical) else None,
            }
            for index, name in enumerate(header)
        ]
        payload = {"columns": header, "values": values, "cells": cells, "raw_record": raw}
        mapping: dict[str, str | None] | None = None
        if len(set(header)) == len(header) and len(values) <= len(header):
            mapping = {
                cell["column"]: None if cell["state"] in {"null", "missing"} else cell["value"]
                for cell in cells
            }
        yield ordinal, payload, mapping


def _cell_state(index: int, values: list[str], lexical: list[str]) -> str:
    if index >= len(values):
        return "missing"
    if lexical[index] == "":
        return "null"
    if values[index] == "":
        return "blank"
    return "value"
