"""Privacy profiles for selected agent-facing JSON commands."""

from __future__ import annotations

import re
from enum import Enum
from typing import Any, Callable


class PrivacyProfile(str, Enum):
    """Supported JSON privacy profiles."""

    RAW = "raw"
    REDACTED = "redacted"
    COMPACT = "compact"


_PROFILE_VALUES = {item.value for item in PrivacyProfile}
REDACTED_TEXT = "[REDACTED]"
REDACTED_PATH = "[REDACTED_PATH]"
REDACTED_FILE = "[REDACTED_FILE]"

_PATH_PATTERN = re.compile(r"(?<![\w.-])(?:~|/)[^\s'\"),;]+")
_WINDOWS_PATH_PATTERN = re.compile(r"(?<![\w.-])[A-Za-z]:\\[^\s'\"),;]+")
_FILE_PATTERN = re.compile(
    r"(?<![\w.-])[\w가-힣 ._@+-]+\.(?:csv|db|json|jsonl|xls|xlsx|yaml|yml)(?![\w.-])"
)

_SENSITIVE_COLLECTION_KEYS = {
    "failed_files",
    "sample_files",
    "sample_memos",
    "samples",
}
_SENSITIVE_EXACT_KEYS = {
    "account",
    "account_raw",
    "counterparty",
    "data_dir",
    "file_id",
    "file_path",
    "label",
    "match",
    "memo",
    "memo_raw",
    "merchant",
    "merchant_raw",
    "path",
    "pattern",
    "payment_method",
    "raw_sample",
    "raw_samples",
    "rules_file",
    "source_file",
    "source_path",
    "suggested_confirmation_question",
}
_SENSITIVE_FINANCIAL_KEYS = {
    "actual",
    "amount",
    "amount_krw",
    "amount_range",
    "amount_stddev",
    "average_monthly_amount",
    "avg_amount",
    "gap_to_target",
    "monthly_avg_expense",
    "monthly_avg_income",
    "net_worth",
    "remaining",
    "target",
    "total_amount",
    "total_assets",
    "total_liabilities",
}


def privacy_meta(profile: PrivacyProfile | str) -> dict[str, Any]:
    """Return additive metadata identifying the applied privacy profile."""
    value = privacy_profile_value(profile) or str(getattr(profile, "value", profile))
    return {"privacy": {"profile": value}}


def privacy_profile_value(profile: Any) -> str | None:
    """Return a supported privacy profile value from an enum or raw string."""
    value = getattr(profile, "value", profile)
    if value in _PROFILE_VALUES:
        return str(value)
    return None


def is_lower_pii_profile(profile: Any) -> bool:
    """Return whether a profile should suppress high-risk values in error text."""
    return privacy_profile_value(profile) in {
        PrivacyProfile.REDACTED.value,
        PrivacyProfile.COMPACT.value,
    }


def redact_error_message(message: str) -> str:
    """Mask path and filename-like values embedded in human-readable errors."""
    redacted = _WINDOWS_PATH_PATTERN.sub(REDACTED_PATH, message)
    redacted = _PATH_PATTERN.sub(REDACTED_PATH, redacted)
    return _FILE_PATTERN.sub(REDACTED_FILE, redacted)


def compact_rule_notes(rule_notes: Any) -> list[dict[str, Any]]:
    """Return rule note context without merchant-derived names or free-text notes."""
    if not isinstance(rule_notes, list):
        return []

    compact_notes: list[dict[str, Any]] = []
    for note in rule_notes:
        if not isinstance(note, dict):
            continue

        compact_note: dict[str, Any] = {}
        tags = note.get("tags")
        if isinstance(tags, list):
            compact_note["tags"] = [str(tag) for tag in tags if tag is not None]
        elif tags is not None:
            compact_note["tags"] = [str(tags)]

        if note.get("category") is not None:
            compact_note["category"] = note["category"]

        compact_notes.append(compact_note)

    return compact_notes


def apply_privacy_profile(
    payload: dict[str, Any],
    profile: PrivacyProfile,
    *,
    compact: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    """Apply a privacy profile while preserving raw payload compatibility."""
    if profile is PrivacyProfile.RAW:
        return payload
    if profile is PrivacyProfile.REDACTED:
        redacted = redact_sensitive_fields(payload)
        assert isinstance(redacted, dict)
        return redacted
    return compact(payload)


def redact_sensitive_fields(value: Any) -> Any:
    """Recursively mask or remove high-risk values from a JSON-like object."""
    return _redact_value(value, path=())


def _redact_value(value: Any, *, path: tuple[str, ...]) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            next_path = (*path, key_text)
            if _is_sensitive_collection_key(key_text):
                redacted[key_text] = []
            elif _is_sensitive_key(key_text, path=path):
                redacted[key_text] = _redact_sensitive_value(item, path=next_path)
            else:
                redacted[key_text] = _redact_value(item, path=next_path)
        return redacted

    if isinstance(value, list):
        return [_redact_value(item, path=path) for item in value]

    return value


def _redact_sensitive_value(value: Any, *, path: tuple[str, ...]) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return {
            str(key): _redact_sensitive_value(item, path=(*path, str(key)))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return []
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return None
    return REDACTED_TEXT


def _is_sensitive_collection_key(key: str) -> bool:
    return key.lower() in _SENSITIVE_COLLECTION_KEYS


def _is_sensitive_key(key: str, *, path: tuple[str, ...]) -> bool:
    normalized = key.lower()
    if normalized in _SENSITIVE_EXACT_KEYS or normalized in _SENSITIVE_FINANCIAL_KEYS:
        return True
    if normalized.endswith("_raw") or normalized.endswith("_krw"):
        return True
    if "amount" in normalized:
        return True
    if normalized in {"key", "name", "rule_name"} and any(
        part in {"merchant_cluster", "rule", "rule_notes", "suggested_rule", "would_apply"}
        for part in path
    ):
        return True
    if normalized == "notes" and "rule_notes" in path:
        return True
    return False
