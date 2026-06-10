# CLI Thin-Wrapper Pattern

Status: Active

Use this pattern when refactoring or adding non-trivial CLI commands. Keep the
change internal to `finjuice.pipeline.cli`; this is not a stable Python API
facade.

## Shape

Typer command functions should stay thin:

1. Read `typer.Context` and raw option values.
2. Build a typed options object for the command.
3. Call a use-case function with that options object.
4. Emit JSON or render human output from the typed result object.

Use-case functions should not depend on `typer.Context`, raw Typer option
defaults, or output mode flags such as `--json`. They should return a typed
result object whose JSON payload is separate from any render-only context.

Rendering functions should receive the computed result and format human output
only. JSON emission should serialize the result payload and attach CLI metadata
outside the computation path.

## Example

`finjuice status` is the reference implementation:

- `StatusOptions` carries parsed context, report filters, and option values.
- `_compute_status(options)` computes a `StatusResult`.
- `StatusResult.payload` is the JSON-compatible command payload.
- `StatusResult.render_context` stores render-only values such as `top_n`.
- `_emit_status_result()` chooses JSON emission or Rich rendering.

## Non-Goals

- Do not rename commands, flags, help text, JSON keys, or exit semantics as part
  of a thin-wrapper refactor.
- Do not introduce broad command registries or public Python API facades.
- Do not refactor many commands at once; prefer one representative command with
  focused tests for human and `--json` behavior.
