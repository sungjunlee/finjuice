# 9. No CLI Command Spec Registry

Date: 2026-05-12

## Status

Accepted

## Context

Issue #601 evaluated whether finjuice should add a command spec registry to keep
these CLI-facing surfaces coherent:

- command registration in `src/finjuice/pipeline/cli/main.py`
- `finjuice manifest --json`
- generated tool schema in `templates/tools.json`
- generated command output schemas in `schemas/*.schema.json`
- generated CLI reference docs in `docs/reference/cli.md`

The current registration path is Typer/Click. `finjuice manifest --json` and
`scripts/generate_tool_schema.py` already share runtime command introspection via
`finjuice.pipeline.cli.introspection`. `tests/cli/test_manifest.py`,
`tests/test_tool_schema.py`, and `tests/test_json_schemas.py` verify most of the
machine-readable command and schema coherence from the live Click tree.

## Decision

Do not add a command spec registry now.

Keep `main.py` plus the registered Typer apps as the executable command source
of truth. Keep manifest and tool schema generation on shared runtime
introspection. Treat command output JSON schemas as explicit contracts because
they describe response shapes, examples, and validation fixtures that cannot be
derived safely from command registration alone.

## Inventory

Current drift risks:

- CLI registration vs manifest/tool schema: low, because both use shared Click
  introspection. The missing case found in this evaluation was standalone
  executable group callbacks, such as `finjuice networth --json`; the command
  walker now includes groups whose Click configuration allows invocation without
  a subcommand.
- CLI registration vs output JSON schemas: medium, because output shape schemas
  are intentionally hand-authored. `tests/test_json_schemas.py` keeps the
  catalog of `--json` commands equal to the live Typer command tree and validates
  representative outputs against generated schema artifacts.
- Manifest vs output schemas: low to medium, because manifest schema refs follow
  a naming convention for commands with `--json`. Existing tests verify the ref
  convention and JSON schema artifacts.
- Tool schema vs output schemas: low, because `scripts/generate_tool_schema.py`
  reads generated schema artifacts when available and tests require all live
  `--json` commands to expose lightweight output schema metadata.
- CLI docs vs command registration: medium. `scripts/generate_cli_docs.py`
  captures live help text, but the documented command list is curated rather
  than a full registry. This is acceptable while `finjuice manifest --json` is
  the preferred machine-readable discovery surface. Revisit only if the human
  CLI reference is expected to document every executable subcommand.

## Consequences

- No new abstraction is added to keep in sync with Typer registration.
- Adding a command still requires normal CLI registration plus output schema work
  when the command exposes `--json`.
- Machine-readable surfaces stay guarded by live introspection tests instead of
  a parallel static registry.
- A registry can be reconsidered only if one of these becomes true:
  - command metadata must be consumed before importing the Typer app,
  - multiple generators need metadata that Click cannot expose,
  - adding one command repeatedly requires edits across more generator files than
    tests can guard,
  - CLI docs become a complete command catalog rather than a curated reference.
