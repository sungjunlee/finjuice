"""Explicit recurring-rule proposals applied to the canonical rules revision."""

from __future__ import annotations

import io
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Mapping

from finjuice.pipeline.storage.sqlite.errors import MutationValidationError
from finjuice.pipeline.storage.sqlite.ids import new_entity_id
from finjuice.pipeline.storage.sqlite.objects import SourceObjectStore
from finjuice.pipeline.storage.sqlite.records import ConfigRevisionRecord, SourceOccurrenceRecord
from finjuice.pipeline.tagging.models import VALID_RULE_FIELDS
from finjuice.pipeline.tagging.rules_yaml_io import load_rules_bytes
from finjuice.pipeline.tagging.rules_yaml_roundtrip import (
    remove_rule_roundtrip_bytes,
    upsert_rule_roundtrip_bytes,
)
from finjuice.pipeline.tagging.validator import validate_rules

if TYPE_CHECKING:
    from finjuice.pipeline.storage.sqlite.mutations import MutationContext


def apply_rule_decision(context: MutationContext, decision: Mapping[str, Any]) -> dict[str, Any]:
    """Upsert or remove one explicit rule without editing existing transaction overrides."""
    action = decision.get("action")
    content = context.read_config_bytes("rules")
    rules = load_rules_bytes(content or b"version: 1\nrules: []\n")
    if action == "upsert" and set(decision) == {"action", "rule"}:
        rule = decision["rule"]
        if not isinstance(rule, dict) or not isinstance(rule.get("name"), str):
            raise MutationValidationError("Recurring rule needs an explicit rule object and name.")
        if set(rule) - VALID_RULE_FIELDS:
            raise MutationValidationError("Recurring rule contains unsupported fields.")
        name = rule["name"]
        matches = [item for item in rules if item.name == name]
        if len(matches) > 1:
            raise MutationValidationError(
                "Resolve duplicate rule names before applying a proposal."
            )
        updated = upsert_rule_roundtrip_bytes(
            rule, content, update=bool(matches), explicit_fields=frozenset(rule)
        )
    elif action == "remove" and set(decision) == {"action", "name"}:
        name = decision["name"]
        if not isinstance(name, str) or content is None:
            raise MutationValidationError("Rule removal requires an existing explicit rule name.")
        updated = remove_rule_roundtrip_bytes(name, content)
    else:
        raise MutationValidationError("Recurring rule decision needs an explicit upsert or remove.")
    validation = validate_rules(load_rules_bytes(updated))
    if validation.has_errors:
        raise MutationValidationError("Recurring rule proposal fails rules validation.")
    return {"action": action, "rule_name": name, **_publish_rules(context, updated)}


def _publish_rules(context: MutationContext, content: bytes) -> dict[str, Any]:
    from finjuice.pipeline.storage.mutation_facade import ConfigDocument
    from finjuice.pipeline.storage.sqlite.mutations import ConfigRevisionMutation

    document = ConfigDocument.from_validated_yaml(
        "rules", content, parser_version="finjuice.rules.v1"
    )
    artifact = SourceObjectStore(context.authority.paths).publish(io.BytesIO(content))
    context.retain_artifact(artifact.artifact_id)
    now = datetime.now(timezone.utc).isoformat()
    occurrence_id, revision_id = new_entity_id(), new_entity_id()
    changed = context.replace_config(
        ConfigRevisionMutation(
            revision=ConfigRevisionRecord(
                revision_id=revision_id,
                config_kind="rules",
                artifact_id=artifact.artifact_id,
                occurrence_id=occurrence_id,
                parsed_status=document.parsed_status,
                parser_version=document.parser_version,
                canonical_payload=document.canonical_payload,
            ),
            occurrence=SourceOccurrenceRecord(
                occurrence_id=occurrence_id,
                artifact_id=artifact.artifact_id,
                occurrence_kind="config_revision",
                original_filename="rules.yaml",
                imported_at=now,
                parser_version=document.parser_version,
                source_schema_version=None,
                legacy_path=None,
            ),
            artifact=artifact,
            updated_at=now,
        )
    )
    return {
        "changed": changed,
        "revision_id": revision_id if changed else context.config_head_revision_id("rules"),
        "artifact_id": artifact.artifact_id,
    }
