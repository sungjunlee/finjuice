"""Atomicity and partial-update regressions for round-trip YAML writers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from ruamel.yaml.comments import CommentedMap

from finjuice.pipeline.goals import _write_goals_roundtrip_unleased
from finjuice.pipeline.tagging.rules_yaml_roundtrip import (
    _write_document,
    upsert_rule_roundtrip_bytes,
)


class _FailingYaml:
    def dump(self, _data: object, stream: Any) -> None:
        stream.write("partial output")
        raise OSError("synthetic dump failure")


@pytest.mark.parametrize("writer", [_write_document, _write_goals_roundtrip_unleased])
def test_dump_failure_preserves_original_bytes(tmp_path: Path, writer: Any) -> None:
    target = tmp_path / "document.yaml"
    original = b"# exact original\nvalue: 1.234567890123456789e-400\n"
    target.write_bytes(original)

    with pytest.raises(OSError, match="synthetic dump failure"):
        writer(_FailingYaml(), CommentedMap(), target)

    assert target.read_bytes() == original
    assert list(tmp_path.glob(".document.yaml.*.tmp")) == []


def test_rule_patch_retains_unknown_and_omitted_optional_fields() -> None:
    original = b"""version: 1
rules:
  - name: retained
    match: old  # match comment
    fields: [memo_raw]  # fields comment
    conditions:
      - field: amount
        op: greater_than
        value: 1.234567890123456789e-400
    tags: [old]
    priority: 88  # priority comment
    category: Existing
    enabled: false
    confidence: 0.75
    notes: keep notes
    custom_id: keep-id
"""
    validated_defaults = {
        "name": "retained",
        "match": "new",
        "fields": ["merchant_raw"],
        "conditions": [],
        "logic": "all",
        "tags": ["new"],
        "priority": 50,
        "enabled": True,
        "category": "",
        "created_by": "manual",
        "created_at": "",
        "confidence": 1.0,
        "notes": "",
    }

    updated = upsert_rule_roundtrip_bytes(
        validated_defaults,
        original,
        update=True,
        explicit_fields=frozenset(),
    )

    assert b"match: new  # match comment" in updated
    assert b"fields: [memo_raw]  # fields comment" in updated
    assert b"priority: 88  # priority comment" in updated
    assert b"value: 1.234567890123456789e-400" in updated
    assert b"category: Existing" in updated
    assert b"enabled: false" in updated
    assert b"confidence: 0.75" in updated
    assert b"notes: keep notes" in updated
    assert b"custom_id: keep-id" in updated


def test_rule_patch_applies_explicit_clear_and_default_without_unknown_loss() -> None:
    original = b"""version: 1
rules:
  - name: retained
    match: old
    fields: [memo_raw]
    tags: [old]
    priority: 88
    category: Existing
    notes: keep notes
    custom_id: keep-id
"""
    validated = {
        "name": "retained",
        "match": "new",
        "fields": ["merchant_raw"],
        "conditions": [],
        "logic": "all",
        "tags": ["new"],
        "priority": 50,
        "enabled": True,
        "category": "",
        "created_by": "manual",
        "created_at": "",
        "confidence": 1.0,
        "notes": "",
    }

    updated = upsert_rule_roundtrip_bytes(
        validated,
        original,
        update=True,
        explicit_fields=frozenset({"category", "priority", "fields"}),
    )

    assert b"category:" not in updated
    assert b"priority: 50" in updated
    assert b"fields: [merchant_raw]" in updated
    assert b"notes: keep notes" in updated
    assert b"custom_id: keep-id" in updated
