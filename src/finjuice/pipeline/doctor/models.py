"""Typed models for doctor environment checks."""

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class CheckResult:
    """Result of a diagnostic check."""

    status: str  # "ok", "warning", "error"
    message: str
    detail: Optional[str] = None
    suggestion: Optional[str] = None
    name: str = ""

    @property
    def icon(self) -> str:
        """Return emoji icon for status."""
        icons = {"ok": "✅", "warning": "⚠️", "error": "❌"}
        return icons.get(self.status, "❓")

    def to_dict(self) -> dict[str, Any]:
        """Convert the check to a JSON-safe dictionary."""
        status_map = {"ok": "pass", "warning": "warn", "error": "fail"}
        return {
            "name": self.name,
            "status": status_map.get(self.status, self.status),
            "message": self.message,
            "detail": self.detail,
            "suggestion": self.suggestion,
        }


@dataclass(frozen=True)
class DoctorResult:
    """Computed doctor payload plus rendering metadata."""

    payload: dict[str, Any]
    sections: list[tuple[str, list[CheckResult]]]
    next_step: str
