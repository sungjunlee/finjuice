"""Required package dependency doctor checks.

Owns :func:`_check_dependencies`. The assembler
:func:`~finjuice.pipeline.doctor.checks._build_doctor_result` stays in
:mod:`finjuice.pipeline.doctor.checks` and re-exports this check so existing
callers can keep importing from that module.
"""

from __future__ import annotations

import importlib.metadata

from finjuice.pipeline.doctor.models import CheckResult


def _check_dependencies() -> list[CheckResult]:
    """Check package dependencies."""
    results = []

    # Required packages
    required_packages = {
        "polars": "polars",
        "typer": "typer",
        "rich": "rich",
        "pyyaml": "PyYAML",
        "openpyxl": "openpyxl",
    }

    for import_name, package_name in required_packages.items():
        try:
            version = importlib.metadata.version(package_name)
            results.append(
                CheckResult(
                    status="ok",
                    message=f"{package_name} {version}",
                    name=f"dependency_{import_name}",
                )
            )
        except importlib.metadata.PackageNotFoundError:
            results.append(
                CheckResult(
                    status="error",
                    message=f"{package_name} 미설치",
                    suggestion=f"uv pip install {package_name}",
                    name=f"dependency_{import_name}",
                )
            )

    return results
