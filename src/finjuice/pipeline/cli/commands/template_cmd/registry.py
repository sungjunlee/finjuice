"""Template registry loading and lookup helpers."""

from __future__ import annotations

from importlib.resources import files
from typing import Any

import yaml

from .options import ListOptions, ShowOptions
from .result import TemplateListResult, TemplateShowResult


class TemplateUnknownError(ValueError):
    """Raised when a requested SQL template is not registered."""

    def __init__(self, template_name: str) -> None:
        super().__init__(f"Unknown template: {template_name}")
        self.template_name = template_name


def _load_registry() -> dict[str, dict[str, Any]]:
    """Load SQL template registry from package resources."""
    raw_text = files("finjuice.templates.sql").joinpath("registry.yaml").read_text(encoding="utf-8")
    payload = yaml.safe_load(raw_text) or {}
    templates = payload.get("templates", {})
    if not isinstance(templates, dict):
        raise ValueError("Invalid registry format: 'templates' must be a mapping")
    return templates


def _load_sql(sql_file: str) -> str:
    """Load SQL file from packaged template resources."""
    if not sql_file.endswith(".sql"):
        raise ValueError(f"Invalid SQL file extension: {sql_file}")

    if "/" in sql_file or "\\" in sql_file or ".." in sql_file:
        raise ValueError(f"Invalid SQL file path: {sql_file}")

    return files("finjuice.templates.sql").joinpath(sql_file).read_text(encoding="utf-8")


def load_template_list(_options: ListOptions) -> TemplateListResult:
    """Load all registered templates."""
    return TemplateListResult(templates=_load_registry())


def load_template_show(options: ShowOptions) -> TemplateShowResult:
    """Load one template's metadata and SQL text."""
    templates = _load_registry()
    if options.name not in templates:
        raise TemplateUnknownError(options.name)

    spec = templates[options.name]
    sql_file = str(spec.get("sql_file", ""))
    sql_text = _load_sql(sql_file)
    return TemplateShowResult(
        name=options.name,
        description=spec.get("description", ""),
        parameters=spec.get("params", {}),
        sql=sql_text.strip(),
    )
