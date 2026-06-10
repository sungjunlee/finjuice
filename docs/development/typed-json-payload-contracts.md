# Typed JSON Payload Contracts

Status: Active

CLI JSON output is finjuice's stable public API. The generated JSON schemas in
`schemas/` remain the external contract. Typed internal payload contracts are a
lightweight implementation guard for commands that build stable JSON payloads.

## Pattern

Use this pattern for high-value `--json` command surfaces:

1. Define command-local `TypedDict` contracts for the top-level payload and
   important stable nested objects.
2. Keep collection/domain dataclasses separate from CLI JSON projection.
3. Add one serializer function that converts domain objects into the typed
   payload before `_meta` is attached.
4. Keep `emit()` and privacy helpers on the existing `dict[str, Any]` boundary;
   cast there only to preserve the shared output plumbing.
5. Add tests that validate the internal serializer output against the existing
   command schema after adding a representative `_meta` envelope.

`automation run` and `checkup` are the initial reference surfaces.

## Non-Goals

- Do not rename JSON fields, change field shapes, or relax schema tests.
- Do not add Pydantic or runtime validation dependencies.
- Do not expose these contracts as a public Python API facade.
- Do not try to type every transient internal dict in a large command.

When extending this pattern, prefer the stable top-level payload and workflow-
driving nested blocks first. Leave volatile implementation details as ordinary
internal data until they become part of a stable JSON surface.
