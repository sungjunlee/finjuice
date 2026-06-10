# Side-Effect Policy

Every `finjuice*` skill declares its side-effect modes near the top of `SKILL.md`.
Use these terms exactly so agents can tell when data, artifacts, journals, or runtime
state may change.

## Taxonomy

- `read-only`: reads local finance data, config, rules, journals, or generated summaries without changing them.
- `mutating-with-confirmation`: changes imports, transaction partitions, tags, rules, goals, transfers, or generated runtime data only after an explicit user request or confirmation.
- `artifact-writing`: writes local report/export artifacts such as `evidence.json`, `commands.txt`, `report.md`, `index.html`, workbooks, or generated export files.
- `journal-writing`: creates or updates finjuice journal entries.
- `runtime-install/update`: installs a missing runtime, checks cached runtime metadata, snoozes update checks, or updates the installed runtime only when explicitly requested.

## Rule

If a workflow would mutate private financial data, write artifacts, write journals, or
install/update runtime state, state that before acting. Preview data/rule changes when
the CLI supports dry-run output and ask before applying unless the user directly asked
for that exact operation.
