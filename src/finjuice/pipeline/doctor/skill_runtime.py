"""Skill runtime doctor checks (version, helper path, CLI capabilities).

Extracted from :mod:`finjuice.pipeline.doctor.checks`. The assembler
re-exports these names so existing callers can keep importing from that
module.
"""

from __future__ import annotations

from pathlib import Path

from finjuice import get_version
from finjuice.pipeline.doctor.models import CheckResult

SKILL_RUNTIME_REQUIRED_VERSION = "0.7.1"
SKILL_RUNTIME_UPDATE_COMMAND = "skills/finjuice/scripts/ensure_finjuice_cli.sh --update --json"
KNOWN_SKILL_CAPABILITIES = {
    "tag.edit": "finjuice tag --edit",
}


def _parse_version_tuple(version: str) -> tuple[int, int, int] | None:
    """Parse a semantic version-ish string into a comparable three-part tuple."""
    parts: list[int] = []
    for raw_part in version.lstrip("vV").split("."):
        digits = ""
        for char in raw_part:
            if not char.isdigit():
                break
            digits += char
        if not digits:
            break
        parts.append(int(digits))
        if len(parts) == 3:
            break

    if not parts:
        return None

    while len(parts) < 3:
        parts.append(0)
    return (parts[0], parts[1], parts[2])


def _version_gte(local_version: str, required_version: str) -> bool:
    """Return whether *local_version* satisfies *required_version*."""
    local = _parse_version_tuple(local_version)
    required = _parse_version_tuple(required_version)
    if local is None or required is None:
        return False
    return local >= required


def _discover_skill_runtime_helper() -> Path | None:
    """Find the shared skill runtime helper without running it."""
    candidate_paths = [
        Path("skills/finjuice/scripts/ensure_finjuice_cli.sh"),
        Path.cwd() / "skills/finjuice/scripts/ensure_finjuice_cli.sh",
        Path.home() / ".codex/skills/finjuice/scripts/ensure_finjuice_cli.sh",
        Path.home() / ".claude/skills/finjuice/scripts/ensure_finjuice_cli.sh",
        Path(".claude/skills/finjuice/scripts/ensure_finjuice_cli.sh"),
        Path("scripts/ensure_finjuice_cli.sh"),
    ]

    for candidate in candidate_paths:
        if candidate.is_file():
            return candidate
    return None


def _probe_cli_capabilities() -> dict[str, bool]:
    """CLI-layer capability probe.

    The doctor command injects a real probe that may inspect Typer commands.
    Core doctor checks must not import ``finjuice.pipeline.cli``.
    """
    return {name: False for name in KNOWN_SKILL_CAPABILITIES}


def _known_skill_capability_checks() -> dict[str, bool]:
    """Return deterministic support checks for known skill runtime capabilities."""
    return _probe_cli_capabilities()


def _capability_check_name(capability: str) -> str:
    """Return a stable CheckResult name for a skill runtime capability."""
    normalized = capability.replace(".", "_").replace("-", "_")
    return f"skill_runtime_capability_{normalized}"


def _check_skill_runtime() -> list[CheckResult]:
    """Check finjuice skill runtime support without network or mutation."""
    results: list[CheckResult] = []
    local_version = get_version()
    version_message = (
        f"finjuice {local_version} (skills require >= {SKILL_RUNTIME_REQUIRED_VERSION})"
    )

    if _version_gte(local_version, SKILL_RUNTIME_REQUIRED_VERSION):
        results.append(
            CheckResult(
                status="ok",
                message=version_message,
                name="skill_runtime_finjuice_version",
            )
        )
    else:
        results.append(
            CheckResult(
                status="warning",
                message=version_message,
                detail="Skill runtime support may be stale.",
                suggestion=f"Run {SKILL_RUNTIME_UPDATE_COMMAND} explicitly.",
                name="skill_runtime_finjuice_version",
            )
        )

    helper_path = _discover_skill_runtime_helper()
    if helper_path is not None:
        results.append(
            CheckResult(
                status="ok",
                message=f"ensure_finjuice_cli.sh: {helper_path}",
                name="skill_runtime_helper",
            )
        )
    else:
        results.append(
            CheckResult(
                status="warning",
                message="ensure_finjuice_cli.sh not found",
                detail="Skill helper is not discoverable from this checkout or global skill paths.",
                suggestion="Install/update finjuice skills before running skill CLI preflight.",
                name="skill_runtime_helper",
            )
        )

    capability_support = _known_skill_capability_checks()
    for capability, cli_path in KNOWN_SKILL_CAPABILITIES.items():
        if capability_support.get(capability, False):
            results.append(
                CheckResult(
                    status="ok",
                    message=f"{capability}: supported",
                    detail=cli_path,
                    name=_capability_check_name(capability),
                )
            )
        else:
            results.append(
                CheckResult(
                    status="warning",
                    message=f"{capability}: missing",
                    detail=f"{cli_path} is stale or unsupported by this finjuice runtime.",
                    suggestion=f"Run {SKILL_RUNTIME_UPDATE_COMMAND} explicitly.",
                    name=_capability_check_name(capability),
                )
            )

    return results
