# Code Quality

## Incremental mypy strictness

`disallow_untyped_defs = true` is enabled for these core packages:

- `finjuice.pipeline.transfer`
- `finjuice.pipeline.storage`
- `finjuice.pipeline.tagging`
- `finjuice.pipeline.analytics`

Command-heavy Typer modules remain on the relaxed global default until their wrappers are
thin enough to ratchet separately.

## Command refactor notes

`finjuice.pipeline.cli.commands.import_cmd` now uses the package-style command split:

- `__init__.py` keeps the stable import path and Typer registration wrapper.
- `options.py` and `result.py` define typed import use-case boundaries.
- `use_case.py`, `zip_extraction.py`, `copying.py`, `pipeline.py`, and `rendering.py`
  isolate orchestration, archive handling, file copy, full-pipeline callbacks, and output.

`finjuice.pipeline.cli.commands.template_cmd` follows the same pattern for template analysis:

- `__init__.py` keeps the stable Typer command group and legacy helper imports.
- `options.py` and `result.py` define typed list/show/run boundaries.
- `registry.py`, `param_coercion.py`, `execution.py`, and `rendering.py` separate template
  lookup, parameter normalization, SQL execution, and output assembly.

`finjuice.pipeline.cli.commands.status` and `finjuice.pipeline.cli.commands.checkup` now use
diagnostic-focused package splits:

- `__init__.py` keeps the stable Typer wrapper and legacy helper import paths.
- `compute.py` collects status facts or checkup bundle facts without rendering.
- `detector.py` owns health/summary decisions and next-action signals.
- `rendering.py` owns JSON payload assembly and human output.

`finjuice.pipeline.goals` and `finjuice.pipeline.forecast` keep their stable public import
paths while focused validation contracts live in sibling modules:

- `goals_validators.py` owns `GoalsValidationProblem`, `ValidationProblems`, goals payload
  dataclasses, and section-level validators.
- `forecast_validators.py` owns scenarios config validation contracts and lifecycle-event
  shape validators.

## Rebasing baseline paths after a refactor

Two baseline files key findings on file path:

- `tools/ruff_complexity_baseline.json` — Ruff complexity debt, keyed on
  `(code, path, symbol)`.
- `security/bandit-baseline.json` — accepted Bandit findings, keyed on
  `(test_id, filename, function)`.

When a refactor moves an already-baselined function to a new module, both gates see the
old path disappear and the new path appear, and flag the move as *new debt* even though
nothing got worse. Fixing that by hand means a CI-fail / manual-edit / CI-pass loop.

Instead, after a pure code move, run:

```bash
just rebase-baselines
```

This invokes both scripts in `--rebase-paths` mode. Each one re-points baseline entries
whose finding identity is unchanged (same complexity value, or same Bandit severity) but
whose path moved, while still failing on genuinely new or worsened debt. Bandit
`rationale` notes are preserved across the move. Review the resulting path-only diff and
commit it with the refactor.

The individual scripts also accept `--rebase-paths` directly
(`scripts/check_complexity_ratchet.py`, `scripts/check_security_baselines.py`); see each
script's `--help`. CI never rebases automatically — a human always confirms the move.
