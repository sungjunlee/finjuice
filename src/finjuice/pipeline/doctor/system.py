"""System environment doctor checks (Python, finjuice version, OS).

Extracted from :mod:`finjuice.pipeline.doctor.checks`. The assembler
re-exports these names so existing callers can keep importing from that
module.
"""

from __future__ import annotations

import platform
import sys

from finjuice import get_version
from finjuice.pipeline.doctor.models import CheckResult


def _check_python_version() -> CheckResult:
    """Check Python version meets requirements (3.10+)."""
    version = sys.version_info
    version_str = f"{version.major}.{version.minor}.{version.micro}"

    if version >= (3, 10):
        return CheckResult(status="ok", message=f"Python {version_str}", name="python_version")
    else:
        return CheckResult(
            status="error",
            message=f"Python {version_str}",
            detail="Python 3.10+ required",
            suggestion="Install Python 3.10 or higher",
            name="python_version",
        )


def _check_finjuice_version() -> CheckResult:
    """Check finjuice version."""
    version = get_version()
    return CheckResult(status="ok", message=f"finjuice v{version}", name="finjuice_version")


def _check_os_info() -> CheckResult:
    """Get OS information."""
    system = platform.system()
    release = platform.release()

    os_names = {"Darwin": "macOS", "Linux": "Linux", "Windows": "Windows"}
    os_display = os_names.get(system, system)

    return CheckResult(status="ok", message=f"OS: {os_display} {release}", name="operating_system")
