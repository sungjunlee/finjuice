# Final Response Contract

Use this field vocabulary when a finjuice workflow finishes. Skill-specific
`## Final Response Contract` sections may add workflow details, but should keep
these field names so agents can finish consistently.

Final responses are Korean-first by default. Use concise Korean headings in the
user-facing answer, and keep the field intent clear:

- `evidence_commands`: finjuice commands or templates that produced the facts.
- `mutations_applied`: rule writes, tag edits, refreshes, imports, or "없음".
- `files_written`: journal/report/export paths written, or "없음".
- `skipped_steps`: skipped phases and why they were skipped.
- `residual_risk`: uncertainty, confidence limits, stale data, or remaining review needs.
- `next_suggested_action`: one concrete follow-up action, or "없음" when complete.

Do not imply hidden analysis. If a number, trend, file, or mutation is mentioned,
it must trace to command output, explicit user input, or a clearly labeled assumption.
