"""Typed results and execution state for template commands."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TemplateListResult:
    """Loaded template registry data for rendering."""

    templates: dict[str, dict[str, Any]]


@dataclass(frozen=True)
class TemplateShowResult:
    """Loaded template metadata and SQL text for rendering."""

    name: str
    description: Any
    parameters: Any
    sql: str


@dataclass(frozen=True)
class TemplateRunResult:
    """Executed template result ready for rendering."""

    template_name: str
    result_df: Any
    row_count: int
    total_row_count: int
    pagination: Any
    output_format: str
    file: Path | None
    machine_output: bool
    filters_applied: int
    template_meta_extras: dict[str, Any]
    pivot_columns: list[str] | None
    user_params: dict[str, str]
    max_bytes: int
    duration: float


@dataclass
class TemplateRunAuditState:
    """Mutable run state used to preserve legacy failure audit details."""

    started_at: float
    user_params: dict[str, str] = field(default_factory=dict)
