# finjuice

External agent guidance for Codex CLI, Gemini CLI, Cursor, and similar tools
working with a finjuice data repository.

`SKILL.md` is the canonical reference for supported capabilities, workflows,
report types, and data conventions. Keep this file focused on cross-agent CLI
boundaries only.

## CLI Boundaries

### Do
- Use the `finjuice` CLI for analysis, reporting, tagging suggestions, and exports
- Read `rules.yaml`, transaction CSV partitions, and asset snapshot CSV partitions as needed
- Refer to `SKILL.md` before describing capabilities or available reports

### Ask First
- Modify `rules.yaml` (show the diff before applying)
- Add new tag categories
- Run destructive or irreversible actions outside normal `finjuice` workflows

### Never Do
- Modify transaction or asset snapshot CSV files directly
- Delete user data files
- Access files outside the user data repository
