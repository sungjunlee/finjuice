"""Parameter parsing and coercion for SQL templates."""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any, Sequence

from finjuice.pipeline.sql_utils import quote_duckdb_string_literal

MONTH_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
DATE_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$")
SAFE_STRING_PATTERN = re.compile(r"^[\w\-\s./(),&+]+$")
MONTH_WINDOW_FORMAT = "YYYY-MM:YYYY-MM or YYYY-MM,YYYY-MM,..."


def _parse_param_kv(params: Sequence[str]) -> dict[str, str]:
    """Parse repeated --param key=value options."""
    parsed: dict[str, str] = {}
    for item in params:
        if "=" not in item:
            raise ValueError(f"Invalid --param format: '{item}' (expected key=value)")
        key, value = item.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            raise ValueError(f"Invalid --param key in: '{item}'")
        if value == "":
            raise ValueError(f"Empty value is not allowed for --param '{key}'")
        parsed[key] = value
    return parsed


def _parse_month_start(raw: str, *, param_name: str) -> date:
    """Parse a YYYY-MM literal into the first day of that month."""
    if not MONTH_PATTERN.match(raw):
        raise ValueError(f"Invalid month value for '{param_name}': {raw} (expected YYYY-MM)")
    year, month = raw.split("-", 1)
    return date(int(year), int(month), 1)


def _coerce_param_value(raw_value: Any, spec: dict[str, Any], param_name: str) -> Any:
    """Validate and normalize a template parameter into a Python value."""
    if raw_value is None:
        return None

    type_name = spec.get("type", "str")
    raw = str(raw_value)

    if type_name == "month":
        _parse_month_start(raw, param_name=param_name)
        return raw

    if type_name == "month_range":
        parts = raw.split(":", 1)
        if len(parts) != 2:
            raise ValueError(
                f"Invalid month range for '{param_name}': {raw} (expected YYYY-MM:YYYY-MM)"
            )
        start_raw, end_raw = parts
        start_month = _parse_month_start(start_raw, param_name=param_name)
        end_month = _parse_month_start(end_raw, param_name=param_name)
        if start_month > end_month:
            raise ValueError(
                f"Invalid month range for '{param_name}': {raw} (start month must be <= end month)"
            )
        return raw

    if type_name == "month_window":
        month_values = _parse_month_window(raw, param_name)
        return json.dumps(month_values, ensure_ascii=False, separators=(",", ":"))

    if type_name == "date":
        if not DATE_PATTERN.match(raw):
            raise ValueError(f"Invalid date value for '{param_name}': {raw} (expected YYYY-MM-DD)")
        return raw

    if type_name == "int":
        try:
            int_value = int(raw)
        except ValueError as e:
            raise ValueError(f"Invalid integer value for '{param_name}': {raw}") from e

        min_value = spec.get("min")
        max_value = spec.get("max")
        if min_value is not None and int_value < int(min_value):
            raise ValueError(f"'{param_name}' must be >= {min_value}")
        if max_value is not None and int_value > int(max_value):
            raise ValueError(f"'{param_name}' must be <= {max_value}")
        return int_value

    if type_name == "enum":
        allowed = spec.get("values", [])
        if raw not in allowed:
            allowed_values = ", ".join(allowed)
            raise ValueError(f"Invalid value for '{param_name}': {raw}. Allowed: {allowed_values}")
        return raw

    if type_name == "bool":
        lowered = raw.lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
        raise ValueError(f"Invalid boolean value for '{param_name}': {raw}")

    if not SAFE_STRING_PATTERN.match(raw):
        raise ValueError(
            f"Unsafe string value for '{param_name}': {raw}. "
            "Allowed characters: letters, numbers, _, -, space, ., /, (, ), comma, &, +"
        )
    return raw


def _to_sql_literal(raw_value: Any, spec: dict[str, Any], param_name: str) -> str:
    """Validate and convert parameter value into a SQL-safe literal."""
    value = _coerce_param_value(raw_value, spec, param_name)
    if value is None:
        return "NULL"

    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return str(value)

    return quote_duckdb_string_literal(value)


def _expand_month_range(start_month: str, end_month: str) -> list[str]:
    """Expand an inclusive YYYY-MM month range."""
    months: list[str] = []
    year, month = map(int, start_month.split("-"))
    end_year, end_month_num = map(int, end_month.split("-"))

    while (year, month) <= (end_year, end_month_num):
        months.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            year += 1
            month = 1

    return months


def _parse_month_window(raw_value: str, param_name: str) -> list[str]:
    """Parse a month selector that supports inclusive ranges or explicit lists."""
    raw = raw_value.strip()
    if not raw:
        raise ValueError(
            f"Invalid month window value for '{param_name}': {raw_value} "
            f"(expected {MONTH_WINDOW_FORMAT})"
        )

    if ":" in raw and "," in raw:
        raise ValueError(
            f"Invalid month window value for '{param_name}': {raw} (expected {MONTH_WINDOW_FORMAT})"
        )

    if ":" in raw:
        parts = [part.strip() for part in raw.split(":")]
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise ValueError(
                f"Invalid month window value for '{param_name}': {raw} "
                f"(expected {MONTH_WINDOW_FORMAT})"
            )
        start_month, end_month = parts
        if not MONTH_PATTERN.match(start_month) or not MONTH_PATTERN.match(end_month):
            raise ValueError(
                f"Invalid month window value for '{param_name}': {raw} "
                f"(expected {MONTH_WINDOW_FORMAT})"
            )
        if start_month > end_month:
            raise ValueError(
                f"Invalid month window value for '{param_name}': {raw} "
                "(start month must be <= end month)"
            )
        return _expand_month_range(start_month, end_month)

    month_values = [part.strip() for part in raw.split(",")]
    if not month_values or any(not month for month in month_values):
        raise ValueError(
            f"Invalid month window value for '{param_name}': {raw} (expected {MONTH_WINDOW_FORMAT})"
        )

    deduped_months: list[str] = []
    seen: set[str] = set()
    for month_value in month_values:
        if not MONTH_PATTERN.match(month_value):
            raise ValueError(
                f"Invalid month window value for '{param_name}': {raw} "
                f"(expected {MONTH_WINDOW_FORMAT})"
            )
        if month_value not in seen:
            deduped_months.append(month_value)
            seen.add(month_value)

    return deduped_months


def _resolve_param_values(
    template_name: str,
    template_spec: dict[str, Any],
    user_params: dict[str, str],
) -> dict[str, Any]:
    """Resolve, validate, and normalize template parameters as Python values."""
    param_specs = template_spec.get("params", {}) or {}
    if not isinstance(param_specs, dict):
        raise ValueError(f"Invalid params section for template '{template_name}'")

    unknown_params = sorted(set(user_params) - set(param_specs))
    if unknown_params:
        raise ValueError(
            f"Unknown parameters for template '{template_name}': {', '.join(unknown_params)}"
        )

    resolved: dict[str, Any] = {}
    for param_name, spec in param_specs.items():
        if not isinstance(spec, dict):
            raise ValueError(f"Invalid spec for parameter '{param_name}' in '{template_name}'")

        required = bool(spec.get("required", False))
        raw_value: Any | None
        if param_name in user_params:
            raw_value = user_params[param_name]
        else:
            raw_value = spec.get("default")

        if raw_value is None and required:
            raise ValueError(f"Missing required parameter: {param_name}")

        resolved[param_name] = _coerce_param_value(raw_value, spec, param_name)

    return resolved


def _resolve_sql_params(
    template_name: str,
    template_spec: dict[str, Any],
    user_params: dict[str, str],
) -> dict[str, str]:
    """Resolve template parameters as SQL literals for {{param}} substitution."""
    values = _resolve_param_values(template_name, template_spec, user_params)
    resolved: dict[str, str] = {}
    for param_name, raw_value in values.items():
        if raw_value is None:
            resolved[param_name] = "NULL"
            continue
        if isinstance(raw_value, bool):
            resolved[param_name] = "TRUE" if raw_value else "FALSE"
            continue
        if isinstance(raw_value, int):
            resolved[param_name] = str(raw_value)
            continue
        resolved[param_name] = quote_duckdb_string_literal(raw_value)
    return resolved


def _get_param_raw_value(
    template_spec: dict[str, Any], user_params: dict[str, str], param_name: str
) -> Any | None:
    """Read a raw template parameter from user input or registry default."""
    if param_name in user_params:
        return user_params[param_name]

    param_specs = template_spec.get("params", {}) or {}
    param_spec = param_specs.get(param_name, {})
    if isinstance(param_spec, dict):
        return param_spec.get("default")
    return None


def _build_compare_meta_extras(
    template_spec: dict[str, Any], user_params: dict[str, str]
) -> dict[str, Any]:
    """Build compare-specific JSON metadata."""
    baseline_raw = _get_param_raw_value(template_spec, user_params, "baseline_months")
    current_raw = _get_param_raw_value(template_spec, user_params, "current_months")
    if baseline_raw is None or current_raw is None:
        return {}

    baseline_months = _parse_month_window(str(baseline_raw), "baseline_months")
    current_months = _parse_month_window(str(current_raw), "current_months")
    return {
        "baseline_months_count": len(baseline_months),
        "current_months_count": len(current_months),
    }


def _build_compare_sql_overrides(
    template_spec: dict[str, Any], user_params: dict[str, str]
) -> dict[str, str]:
    """Build compare-only SQL snippets from validated allowlists."""
    group_by = str(_get_param_raw_value(template_spec, user_params, "group_by"))
    type_norm = str(_get_param_raw_value(template_spec, user_params, "type_norm"))

    group_by_expr = {
        "category_final": "category_final",
        "major_raw": "major_raw",
        "merchant_raw": "merchant_raw",
    }[group_by]
    type_norm_filter = {
        "expense": "amount < 0 AND is_transfer_bool = FALSE",
        "income": "amount > 0 AND is_transfer_bool = FALSE",
        "all": "is_transfer_bool = FALSE",
    }[type_norm]
    return {
        "group_by_expr": group_by_expr,
        "type_norm_filter": type_norm_filter,
    }


def _resolve_template_context(
    template_name: str,
    template_spec: dict[str, Any],
    user_params: dict[str, str],
) -> tuple[dict[str, str], dict[str, Any]]:
    """Resolve SQL params and command-specific metadata for a template."""
    resolved_params = _resolve_sql_params(template_name, template_spec, user_params)
    meta_extras: dict[str, Any] = {}

    if template_name == "compare":
        meta_extras = _build_compare_meta_extras(template_spec, user_params)
        resolved_params.update(_build_compare_sql_overrides(template_spec, user_params))

    return resolved_params, meta_extras


def _quote_sql_literal(value: str) -> str:
    """Return a single-quoted SQL literal."""
    return quote_duckdb_string_literal(value)
