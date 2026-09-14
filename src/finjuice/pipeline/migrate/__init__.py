"""Frozen-source plan/build/verify for preservation migration.

Public names are defined in child modules and re-exported here so callers and
monkeypatch targets stay stable.
"""

from finjuice.pipeline.migrate.errors import MigrationError
from finjuice.pipeline.migrate.inventory import (
    capture_frozen_inputs,
    load_capture_manifest,
    write_capture_manifest,
)
from finjuice.pipeline.migrate.ops import (
    build_migration,
    load_plan,
    notify_build_progress,
    plan_migration,
    verify_migration,
    write_plan,
)
from finjuice.pipeline.migrate.preserve import split_hidden_category
from finjuice.pipeline.migrate.types import (
    ORIGIN_KIND,
    SCHEMA_VERSION,
    CaptureManifest,
    MigrationPlan,
    MigrationResult,
)

__all__ = [
    "ORIGIN_KIND",
    "SCHEMA_VERSION",
    "CaptureManifest",
    "MigrationError",
    "MigrationPlan",
    "MigrationResult",
    "build_migration",
    "capture_frozen_inputs",
    "load_capture_manifest",
    "load_plan",
    "notify_build_progress",
    "plan_migration",
    "split_hidden_category",
    "verify_migration",
    "write_capture_manifest",
    "write_plan",
]
