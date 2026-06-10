"""
finjuice - Local-first personal finance pipeline for Banksalad data.

Namespace package for modular finance tools.
"""

__version__ = "0.6.2"


def get_version() -> str:
    """Return the installed finjuice version.

    Uses ``importlib.metadata`` for the installed package version (preferred),
    falling back to the ``__version__`` constant for development installs.
    """
    try:
        from importlib.metadata import PackageNotFoundError, version

        return version("finjuice")
    except PackageNotFoundError:
        return __version__
