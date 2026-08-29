"""Subprocess timeout constants for finjuice.

Owns the short/medium/long subprocess timeout values. These are re-exported
from :mod:`finjuice.pipeline.constants` so existing callers can keep importing
from that module.
"""

from typing import Final

SUBPROCESS_TIMEOUT_SHORT: Final = 5
"""Short timeout for quick subprocess operations (seconds).

Used for:
- Version checks (git --version, claude --version)
- Opening files in external apps (open, xdg-open)

Rationale:
- These operations should complete almost instantly
- 5 seconds allows for slow disk/network but catches hangs
"""

SUBPROCESS_TIMEOUT_MEDIUM: Final = 10
"""Medium timeout for typical subprocess operations (seconds).

Used for:
- Git operations (init, add, commit)
- File system operations

Rationale:
- Git operations may be slow on large repos or slow storage
- 10 seconds is generous for typical personal finance data
"""

SUBPROCESS_TIMEOUT_LONG: Final = 60
"""Long timeout for AI/network operations (seconds).

Used for:
- Claude Code CLI calls
- Network-dependent operations

Rationale:
- AI model responses can take 30-60 seconds for complex queries
- Network latency varies significantly
"""
