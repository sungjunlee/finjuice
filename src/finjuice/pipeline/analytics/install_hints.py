"""Install hint helpers for optional analytics dependencies."""

from __future__ import annotations

import importlib.metadata
import json
import os
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

ANALYTICS_EXTRA = "analytics"
UV_TOOL_ANALYTICS_INSTALL = "uv tool install --force --with duckdb finjuice"
UV_SYNC_ANALYTICS_INSTALL = "uv sync --extra analytics"
PIP_ANALYTICS_INSTALL = "pip install 'finjuice[analytics]'"
DUCKDB_DOCTOR_HINT = (
    "DuckDB is required for analytics commands. Run 'finjuice doctor' to see the exact "
    "analytics install command."
)


def _finjuice_tool_source() -> str:
    """Return the installed finjuice source spec when PEP 610 metadata exposes it."""
    try:
        direct_url_text = importlib.metadata.distribution("finjuice").read_text("direct_url.json")
    except importlib.metadata.PackageNotFoundError:
        direct_url_text = None

    source = "finjuice"
    if direct_url_text:
        try:
            direct_url = json.loads(direct_url_text)
        except json.JSONDecodeError:
            direct_url = {}

        url = direct_url.get("url")
        if isinstance(url, str) and url:
            vcs_info = direct_url.get("vcs_info")
            if isinstance(vcs_info, dict) and vcs_info.get("vcs") == "git":
                source = url if url.startswith("git+") else f"git+{url}"
            else:
                parsed_url = urlparse(url)
                if parsed_url.scheme == "file" and parsed_url.path:
                    source = unquote(parsed_url.path)

    return source


def detect_analytics_install_command(sys_prefix: str | Path | None = None) -> str:
    """Return the best analytics install command for the current environment."""
    prefix = Path(sys_prefix or sys.prefix).expanduser().resolve()
    checkout_anchor = prefix if sys_prefix is not None else Path(__file__).resolve()
    tool_dirs = []
    if uv_tool_dir := os.getenv("UV_TOOL_DIR"):
        tool_dirs.append(Path(uv_tool_dir).expanduser().resolve())
    if xdg_data_home := os.getenv("XDG_DATA_HOME"):
        tool_dirs.append((Path(xdg_data_home).expanduser() / "uv" / "tools").resolve())
    else:
        tool_dirs.append((Path.home() / ".local" / "share" / "uv" / "tools").resolve())
    if local_app_data := os.getenv("LOCALAPPDATA") or os.getenv("APPDATA"):
        tool_dirs.append((Path(local_app_data).expanduser() / "uv" / "tools").resolve())
    if any(tool_dir == prefix or tool_dir in prefix.parents for tool_dir in tool_dirs):
        return f"uv tool install --force --with duckdb {_finjuice_tool_source()}"
    if any(
        (parent / "pyproject.toml").exists() and (parent / "uv.lock").exists()
        for parent in (checkout_anchor, *checkout_anchor.parents)
    ):
        return UV_SYNC_ANALYTICS_INSTALL
    return PIP_ANALYTICS_INSTALL
