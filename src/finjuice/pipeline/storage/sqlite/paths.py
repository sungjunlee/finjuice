"""Path roles for one inactive or active SQLite dataset generation."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from finjuice.pipeline.storage.sqlite.errors import RepositoryPathError

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class GenerationPaths:
    """Resolve the closed storage roles beneath one dataset generation root."""

    root: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", self.root.expanduser().absolute())

    @property
    def database(self) -> Path:
        """Return the authoritative SQLite file path."""
        return self.root / "finjuice.sqlite3"

    @property
    def objects(self) -> Path:
        """Return the immutable source-object root."""
        return self.root / "objects"

    @property
    def sha256_objects(self) -> Path:
        """Return the SHA-256 object namespace root."""
        return self.objects / "sha256"

    @property
    def manifests(self) -> Path:
        """Return the immutable manifest directory."""
        return self.root / "manifests"

    @property
    def derived(self) -> Path:
        """Return the disposable derived-output root."""
        return self.root / "derived"

    def object_path(self, digest_hex: str) -> Path:
        """Return the canonical object path for a lowercase SHA-256 digest."""
        if _DIGEST_RE.fullmatch(digest_hex) is None:
            raise RepositoryPathError("Object digest must contain 64 lowercase hex digits.")
        return self.sha256_objects / digest_hex[:2] / digest_hex

    def derived_revision(self, dataset_generation: str, revision: int) -> Path:
        """Return the deterministic projection path for a dataset revision."""
        try:
            generation = str(uuid.UUID(dataset_generation))
        except (AttributeError, TypeError, ValueError) as exc:
            raise RepositoryPathError("Dataset generation must be a canonical UUID.") from exc
        if generation != dataset_generation:
            raise RepositoryPathError("Dataset generation must be a canonical UUID.")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
            raise RepositoryPathError("Dataset revision must be a non-negative integer.")
        return self.derived / generation / str(revision)
