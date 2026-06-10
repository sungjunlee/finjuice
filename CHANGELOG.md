# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Added

- `finjuice version` subcommand — shows software version + data schema version,
  with `--json` support for machine-readable output (#806).
- `get_version()` centralized in `src/finjuice/__init__.py` for consistent version
  retrieval across all modules (#808).
- `just bump-version` recipe and `scripts/bump_version.py` — automated version
  bump across all 5 version locations with `--dry-run` preview (#804).
- `ensure_finjuice_cli.sh` tag-based install: when `--require-version X.Y.Z` is
  provided, install pins to `@vX.Y.Z` git tag instead of HEAD (#807).
- Pagination support for `query`, `show`, `template run`: new
  `--limit/--cursor/--max-bytes` options and `pagination` envelope.
  Additive — `show --limit` default of 20 preserved; new commands
  default to `--limit 100`.
- Additive `_meta` envelopes for list-style JSON outputs: `journal list` now returns
  `entries` plus `count`, `rules list --json` is available as an enveloped alias for
  rule listing, and dict-typed outputs require no consumer migration.
- Documented the release process and version surfaces for CLI, JSON metadata, doctor,
  changelog, and git tags.
- Added `finjuice --version` so users and agents can verify the installed CLI version
  without requiring a configured data directory.
- Added Dependabot automation and review guidance for Python and GitHub Actions
  dependency updates (#643).
- Documented GitHub Actions least-privilege permissions and `main` branch
  protection expectations (#646).

### Changed

- Hardened GitHub Actions workflow tokens with top-level read defaults and
  job-level write permissions only where audit, release, or Claude actions need
  them (#646).

### Fixed

- `finjuice doctor` now reports the installed `finjuice` package version instead of the
  legacy `banksalad-tools` package name fallback.

---

## [0.6.2] - 2026-04-13

### Fixed

- CI: pin `COLUMNS=120`, `NO_COLOR=1`, `TERM=dumb` for CLI help rendering in both pytest (session-scope autouse fixture in `tests/conftest.py`) and docs generator (`scripts/generate_cli_docs.py`) to eliminate environment-dependent drift in Rich/Typer help output — ANSI styling was breaking substring assertions on self-hosted Linux CI while passing locally on macOS non-TTY (#416)
- CI: align Python version labels with the actual runner. `ci.yml` baseline gate is now `Test (Python 3.13)` (matches `.python-version`), and `ci-full.yml` matrix sets `UV_PYTHON` per cell so 3.10/3.11/3.12/3.13 each run their declared interpreter instead of all collapsing to `.python-version` (#418)

---

## [0.6.1] - 2026-04-13

### Highlights

Patch release hardening the v0.6.0 Conditional Rule Engine. Four UX/bug gaps and one new read-only CLI, all sourced from the 2026-04-12 conditions engine validation pass (`docs/plans/discussions/2026-04-v060-conditions-followup.md`). Sprint execution log: `docs/plans/execution/sprint-2026-04-v061-conditions-hardening.md`.

### Added

- **`finjuice rules test <name>`**: Single-rule dry-run CLI reporting match count, sample rows, month distribution, and cross-tags overlap (from `tags_rule`, legacy-rule overlap only). Supports `--limit`, `--month`, and `--json` ([#409](https://github.com/sungjunlee/finjuice/issues/409), [PR #414](https://github.com/sungjunlee/finjuice/pull/414))
- **Conditions operator reference** (`docs/reference/rules-conditions.md`): Full semantics for all 9 operators (`contains`, `not_contains`, `is`, `is_not`, `starts_with`, `regex`, `less_than`, `greater_than`, `between`), field × operator matrix, `logic: all`/`any` precedence, `conditions` vs legacy `match`/`fields` precedence, and `case_sensitive` roadmap note ([#408](https://github.com/sungjunlee/finjuice/issues/408), [PR #413](https://github.com/sungjunlee/finjuice/pull/413))
- **`between` operator accepts YAML list format**: `value: [-50000, -10000]` now works alongside the existing `value: "-50000,-10000"` CSV string form. Error messages include both accepted formats with examples ([#407](https://github.com/sungjunlee/finjuice/issues/407), [PR #410](https://github.com/sungjunlee/finjuice/pull/410))

### Changed

- **`finjuice rules validate` batch error reporting**: Collects all validation errors in a single pass instead of fail-fast. Each error carries rule index and name. `--strict` flag preserves legacy fail-fast semantics. Operator typos receive `difflib`-based Did-you-mean suggestions ([#406](https://github.com/sungjunlee/finjuice/issues/406), [PR #411](https://github.com/sungjunlee/finjuice/pull/411))
  - Absorbed Deferred: D2 (error framing), D7 (Did-you-mean for operators)

### Fixed

- **`finjuice show --tag/--untagged/--merchant` partition scope**: Previously limited to the latest month, now scans all partitions when `--month` is omitted. Exact tag matching handles brackets, spaces, and Hangul+ASCII mixes (e.g. `--tag "[테스트]LLM서비스"`) ([#405](https://github.com/sungjunlee/finjuice/issues/405), [PR #412](https://github.com/sungjunlee/finjuice/pull/412))

### Developer & CI

- **Sprint regression protocol**: Tagging-result diff is only meaningful as pre-patch vs post-patch within a single tagging run. The `_baseline_snapshot` artifact carries unrelated Phase-2 drift and must not be used as a regression oracle
- **Admin merge policy clarified**: Pre-existing CI failures (12 help-text/pipeline tests red since v0.6.0) do not block merges when the local 3-gate (`pytest`, `ruff`, `mypy`) passes and static regression analysis shows no tagging impact
- **Deferred tracking**: D3/D4/D5 absorbed into #413 docs; D2/D7 absorbed into #411. Remaining deferred (D1, D6, D8) plus new FU09/FU10/FU11 tracked in sprint retrospective

### Upgrade Notes

- No breaking changes. Existing `match`/`fields` rules and `conditions`-based rules continue to work
- `between` rules using the legacy CSV string format remain valid; migrate to YAML list at your discretion
- LLM agents authoring rules should prefer the YAML list form for `between` and consult `docs/reference/rules-conditions.md` for operator selection

---

## [0.6.0] - 2026-04-12

### Highlights

Major feature release spanning two months of development. **153 commits** since v0.5.0 across four themes:

1. **Conditional Rule Engine** — Multi-condition tagging rules with 9 operators and AND/OR logic (#400-#402)
2. **Asset Support** — Separated asset ingest pipeline and snapshot-first SSOT (#218-#226)
3. **CLI as Structured Data API** — ADR-0007 realized: JSON output everywhere, structured error codes, machine-readable tool schema for agent consumption
4. **CLI Reorganization** — Four command groups (Core/Analysis/Admin/Rules), per-command modules, legacy surfaces removed

### Added

#### Conditional Rule Engine (NEW)
- **Conditions-based tagging**: `conditions` field in rules.yaml with 9 operators and AND/OR logic ([#400](https://github.com/sungjunlee/finjuice/issues/400))
  - Text operators: `contains`, `not_contains`, `is`, `is_not`, `starts_with`, `regex` ([#401](https://github.com/sungjunlee/finjuice/pull/403))
  - Numeric operators: `less_than`, `greater_than`, `between` ([#402](https://github.com/sungjunlee/finjuice/pull/404))
  - Extended fields: `type_norm`, `amount`, `account` in addition to text fields
  - `logic: all` (AND, default) and `logic: any` (OR) combining
  - 100% backward compatible with legacy `match/fields` rules
  - YAML int/float coercion for natural numeric syntax

#### Asset Support (NEW)
- **Asset snapshot schema v0**: Snapshot-first SSOT separated from transaction domain ([#223](https://github.com/sungjunlee/finjuice/issues/223))
- **Separated asset ingest path**: Dedicated pipeline for asset sheets ([#224](https://github.com/sungjunlee/finjuice/issues/224))
- **Snapshot writer with idempotent dedup**: Daily grain with deterministic derived IDs ([#225](https://github.com/sungjunlee/finjuice/issues/225))
- **Asset templates + ask context**: Curated queries and agent context expansion ([#226](https://github.com/sungjunlee/finjuice/issues/226))
- **`finjuice assets` CLI commands**: `assets status` and `assets show` for portfolio inspection

#### CLI Structured Data API (ADR-0007)
- **`_meta` envelope injection** across JSON outputs ([#284](https://github.com/sungjunlee/finjuice/issues/284), [#285](https://github.com/sungjunlee/finjuice/issues/285))
- **Structured error codes + semantic exit codes** ([#282](https://github.com/sungjunlee/finjuice/issues/282), [#286](https://github.com/sungjunlee/finjuice/issues/286))
- **Machine-readable tool schema** for agent validation ([#287](https://github.com/sungjunlee/finjuice/issues/287))
- **JSON output everywhere**: rules, templates, import, audit log/stats, read commands, and remaining CLI surfaces ([#260](https://github.com/sungjunlee/finjuice/pull/260), [#277](https://github.com/sungjunlee/finjuice/pull/277), [#288](https://github.com/sungjunlee/finjuice/pull/288), [#353](https://github.com/sungjunlee/finjuice/pull/353), [#390](https://github.com/sungjunlee/finjuice/pull/390), [#391](https://github.com/sungjunlee/finjuice/pull/391), [#392](https://github.com/sungjunlee/finjuice/pull/392))
- **Unified emit() contract** for all CLI commands ([#267](https://github.com/sungjunlee/finjuice/issues/267), [#270](https://github.com/sungjunlee/finjuice/issues/270))
- **JSON schema reference** in docs for AI consumers ([#264](https://github.com/sungjunlee/finjuice/pull/264))
- **ADR-0007**: CLI as Structured Data API for AI Agents

#### Rules Management
- **`rules add`, `rules remove` CLI commands** ([#364](https://github.com/sungjunlee/finjuice/pull/364))
- **`rules suggest` preview and `--dry-run`** flags ([#344](https://github.com/sungjunlee/finjuice/pull/344))
- **`rules suggest` rewrite** with merchant context ([#359](https://github.com/sungjunlee/finjuice/issues/359))
- **`suggested_rule` field** in `rules suggest --json` output ([#374](https://github.com/sungjunlee/finjuice/issues/374))

#### Manual Tagging & Review
- **`finjuice review` command**: Inspect review queue ([#338](https://github.com/sungjunlee/finjuice/issues/338))
- **Manual tag editing** with `tags_manual` persistence ([#339](https://github.com/sungjunlee/finjuice/issues/339))
- **`needs_review` flag** and review queue polish

#### Insights & Templates
- **Recurring payment / subscription report** in `finjuice insights` ([#340](https://github.com/sungjunlee/finjuice/issues/340))
- **Weekly review SQL templates** + skill workflow ([#381](https://github.com/sungjunlee/finjuice/pull/381))
- **Template query coverage**: 12-of-12 pilot queries complete
- **Template run audit instrumentation** and reporting
- **4-week pilot kickoff**: template CLI + sync guardrails + execution docs ([#210](https://github.com/sungjunlee/finjuice/pull/210))

#### Data Directory & Config
- **Auto-init data directory** on first import ([#314](https://github.com/sungjunlee/finjuice/pull/314))
- **Legacy data migration path** via `finjuice migrate` ([#306](https://github.com/sungjunlee/finjuice/issues/306))
- **Data directory schema version tracking** ([#305](https://github.com/sungjunlee/finjuice/issues/305))
- **`finjuice refresh`** command (alias for `all`) ([#307](https://github.com/sungjunlee/finjuice/issues/307))
- **Consolidated default data directory** to `~/.finjuice/` ([#304](https://github.com/sungjunlee/finjuice/issues/304))

#### Developer Experience
- **Non-interactive import** with explicit `--file` option ([#255](https://github.com/sungjunlee/finjuice/issues/255))
- **Ingest and export `--dry-run` previews** ([#258](https://github.com/sungjunlee/finjuice/issues/258))
- **`--yes` flag** to bypass interactive prompts ([#393](https://github.com/sungjunlee/finjuice/pull/393))
- **Pre-commit hooks** in dev extras

### Changed

- **CLI restructured into 4 groups**: Core, Analysis, Admin, Rules ([#272](https://github.com/sungjunlee/finjuice/issues/272))
- **`pipeline.py` split** into per-command modules ([#269](https://github.com/sungjunlee/finjuice/issues/269))
- **Environment variables renamed**: `BSALAD_*` → `FINJUICE_*` ([#316](https://github.com/sungjunlee/finjuice/issues/316), [#317](https://github.com/sungjunlee/finjuice/issues/317))
- **CLI output migrated** from local `Console()` to shared output module ([#265](https://github.com/sungjunlee/finjuice/issues/265))
- **`rules suggest` flag renamed**: `--auto` → `--yes` ([#388](https://github.com/sungjunlee/finjuice/issues/388))
- **CSV v3 column SSOT** unified across writers ([#219](https://github.com/sungjunlee/finjuice/issues/219))

### Removed

- **Legacy interactive CLI** retired ([#268](https://github.com/sungjunlee/finjuice/issues/268))
- **Quickstart command** removed — `import` handles setup automatically ([#254](https://github.com/sungjunlee/finjuice/issues/254))
- **Deprecated analysis commands** cleaned up ([#360](https://github.com/sungjunlee/finjuice/issues/360))
- **Legacy JSONL DuckDB query path** retired ([#248](https://github.com/sungjunlee/finjuice/issues/248))
- **Deprecated skill CLI** removed ([#296](https://github.com/sungjunlee/finjuice/issues/296))

### Fixed

- **Transfer flag normalization**: All `type_raw="이체"` rows marked `is_transfer=1` ([#356](https://github.com/sungjunlee/finjuice/pull/356))
- **Non-transfer `is_transfer` normalization** ([#369](https://github.com/sungjunlee/finjuice/issues/369))
- **Review command restored** after accidental deletion ([#395](https://github.com/sungjunlee/finjuice/pull/395))
- **JSON output isolation**: Rich console output suppressed in `--json` mode ([#363](https://github.com/sungjunlee/finjuice/pull/363), [#328](https://github.com/sungjunlee/finjuice/pull/328), [#329](https://github.com/sungjunlee/finjuice/issues/329))
- **JSON envelope consistency**: `_meta`, error codes, schema headings standardized ([#326](https://github.com/sungjunlee/finjuice/issues/326), [#370](https://github.com/sungjunlee/finjuice/issues/370), [#373](https://github.com/sungjunlee/finjuice/issues/373))
- **DuckDB analytics contract alignment** ([#246](https://github.com/sungjunlee/finjuice/issues/246), [#346](https://github.com/sungjunlee/finjuice/issues/346))
- **Category fallback**: Blank `category_rule` falls through to minor/major raw ([#219](https://github.com/sungjunlee/finjuice/issues/219))
- **Status `--json`** numeric precision and untagged merchants cap ([#372](https://github.com/sungjunlee/finjuice/issues/372))
- **Query JSON wrap** ([#347](https://github.com/sungjunlee/finjuice/issues/347))
- **Template hour parsing** for non-padded values
- **Query restricted keyword** false positives
- **Audit log resilience**: Invalid durations ignored, proper retry attribution ([#229](https://github.com/sungjunlee/finjuice/issues/229))

### Developer & CI

- **CI lean gate**: Smoke tests on self-hosted + scheduled full CI ([#243](https://github.com/sungjunlee/finjuice/issues/243))
- **Finjuice skill split** into 4 specialized skills ([#399](https://github.com/sungjunlee/finjuice/pull/399))
- **Cold-start onboarding documentation** ([#361](https://github.com/sungjunlee/finjuice/issues/361))
- **Distributable finjuice skill** ([#295](https://github.com/sungjunlee/finjuice/issues/295))
- **Template-driven LLM issue registration workflow**
- **Transaction + asset agent workflow** documented ([#228](https://github.com/sungjunlee/finjuice/issues/228))
- **E2E regression baseline** locked ([#230](https://github.com/sungjunlee/finjuice/issues/230))
- **DuckDB benchmark re-baseline** ([#247](https://github.com/sungjunlee/finjuice/issues/247))

### Upgrade Notes

- **Env var rename**: Update any scripts using `BSALAD_*` → `FINJUICE_*`
- **Interactive CLI retired**: Replace `finjuice interactive` / `quickstart` with direct commands (`import`, `refresh`, `status`)
- **Rules format unchanged**: Existing `match/fields` rules work without modification; opt in to `conditions` per rule
- **Default data dir**: `~/.finjuice/` is canonical; run `finjuice migrate` if migrating from legacy locations

---

## [0.4.0] - 2025-12-16

### Highlights

Major feature release with interactive import flow, multi-format export (HTML/Markdown), and AI analysis enhancements. **22 commits** since v0.3.4.

### Added

#### New Commands & Features
- **Interactive Import Flow**: `finjuice import` now shows file browser for selecting XLSX files ([#138](https://github.com/sungjunlee/finjuice/pull/138))
- **Multi-format Export**: Generate HTML reports with Plotly charts and Markdown reports ([#117](https://github.com/sungjunlee/finjuice/issues/117), [#123](https://github.com/sungjunlee/finjuice/pull/123))
- **Quickstart Command**: `finjuice quickstart` guides first-time users through setup ([#126](https://github.com/sungjunlee/finjuice/pull/126))
- **AI-First Analysis**: Enhanced AI analysis with `finjuice insights` command ([#116](https://github.com/sungjunlee/finjuice/issues/116), [#119](https://github.com/sungjunlee/finjuice/pull/119))
- **Interactive Ask Selection**: `finjuice ask` without arguments shows numbered suggestion list ([#139](https://github.com/sungjunlee/finjuice/pull/139))

#### CLI Improvements
- `--save-config` option to persist data directory to config file ([#132](https://github.com/sungjunlee/finjuice/pull/132))
- `--detailed` flag for `finjuice status` command ([#127](https://github.com/sungjunlee/finjuice/pull/127))
- `--overwrite` option for `finjuice workspace sync` command ([#125](https://github.com/sungjunlee/finjuice/pull/125))
- Warning logs for unusual transaction amounts (>₩10M or <₩100) ([#122](https://github.com/sungjunlee/finjuice/pull/122))
- Subprocess timeout constants for better reliability ([#139](https://github.com/sungjunlee/finjuice/pull/139))

#### Developer Experience
- Claude Code auto-format hooks for consistent code style
- Comprehensive tests for AI commands (ai.py, insights.py) ([#121](https://github.com/sungjunlee/finjuice/pull/121))
- Synthetic E2E test data generator for realistic testing
- CLI output style guide documentation ([#131](https://github.com/sungjunlee/finjuice/pull/131))

### Changed

- **CLI Output Language**: Unified to Korean (한국어 통일) ([#124](https://github.com/sungjunlee/finjuice/pull/124))
- **Import Command**: Now runs full pipeline automatically (ingest → tag → transfer → export) ([#134](https://github.com/sungjunlee/finjuice/pull/134))
- **Context-aware Error Messages**: Suggests 'init' or 'ingest' based on directory state ([#139](https://github.com/sungjunlee/finjuice/pull/139))
- Simplified import workflow: single command replaces multi-step process

### Fixed

- DataState enum now distinguishes between init and empty states
- Schema registry default path unified with Config ([#129](https://github.com/sungjunlee/finjuice/pull/129))
- 8 mypy type errors across 3 files ([#136](https://github.com/sungjunlee/finjuice/pull/136))
- Transfer command bug fix ([#135](https://github.com/sungjunlee/finjuice/pull/135))
- Complete `bsalad` → `finjuice` migration in all files ([#133](https://github.com/sungjunlee/finjuice/pull/133))
- Documentation references updated for row_hash 10→16 chars ([#128](https://github.com/sungjunlee/finjuice/pull/128))
- Deprecation warnings cleanup

### Testing

- Edge case tests for validate_rules ([#130](https://github.com/sungjunlee/finjuice/pull/130))
- 6 new E2E tests enabled with synthetic test data
- Test coverage maintained at 83%+
- AI command comprehensive test suite ([#121](https://github.com/sungjunlee/finjuice/pull/121))
- **1193 tests passing** (up from 967 in v0.3.0)

### Verified

- ✅ All 1193 tests passing (100% pass rate)
- ✅ Test coverage: 83.47% (exceeds 80% requirement)
- ✅ Zero linting errors (ruff)
- ✅ Zero type errors (mypy)
- ✅ Full backward compatibility with v0.3 workflows

---

## [0.3.0] - 2025-12-10

### ✨ Highlights

Zero-config first-run experience with persistent configuration. **No breaking changes** - full backward compatibility with v0.2.

### Added

- **Config file infrastructure** ([#101](https://github.com/sungjunlee/finjuice/issues/101))
  - TOML-based configuration at `~/.config/finjuice/config.toml`
  - 4-tier precedence: CLI arg > ENV var > Config file > OS default
  - Automatic config file creation and validation
  - No more repeating `--data-dir` on every command

- **Enhanced first-run UX** ([#102](https://github.com/sungjunlee/finjuice/issues/102))
  - Welcome wizard for new users
  - Interactive data directory selection
  - Smart routing for `finjuice` command
  - Automatic directory initialization
  - Post-setup guidance (next steps display)

- **CLI command refinement** ([#103](https://github.com/sungjunlee/finjuice/issues/103))
  - `finjuice` as primary entry point (auto-init for first run)
  - `finjuice all` for regular workflow (unchanged)
  - `finjuice init` for advanced setup only (updated help text)
  - Improved command descriptions and examples

### Changed

- App directory renamed from `banksalad-tools` to `finjuice` in OS defaults
- Interactive mode now triggered automatically on first run
- `finjuice init` help text clarified as advanced option
- Main entry point (`finjuice`) now features smart routing based on data state

### Fixed

- Added missing `metadata_dir` property to Config class
- Improved TOCTOU (time-of-check-time-of-use) protection for config file creation
- Fixed `initialize_data_directory` helper function extraction for code reuse
- Improved error messages for uninitialized data directories

### Security

- Config file validation prevents symlink attacks
- Atomic write operations for config file updates
- Path traversal prevention in config file paths
- Environment variable sanitization in precedence system

### Documentation

- Added comprehensive [first-run user guide](docs/guides/first-run-guide.md)
- Added [migration guide](docs/guides/migration-to-v0.3.md) for v0.2 → v0.3 upgrade
- Updated CLI reference with new command roles
- Enhanced help text across all commands

### Testing

- Added 13 E2E test scenarios for first-run workflow
- Added security tests for config file validation
- Added integration tests for welcome wizard flow
- Test coverage maintained at 80%+

### Verified

- ✅ All 967 tests passing (100% pass rate)
- ✅ Test coverage: 81%+ (exceeds 80% requirement)
- ✅ Zero linting errors (ruff)
- ✅ Full backward compatibility with v0.2 workflows
- ✅ Security audit passed (no critical vulnerabilities)

---

## [0.2.0] - 2025-12-09

### ⚠️ BREAKING CHANGES

- **CLI command renamed**: `finectl` → `finjuice`
- **Package name changed**: `bsalad` → `finjuice`
- **Python imports changed**: `from bsalad.*` → `from finjuice.*`

### Migration

**Quick upgrade**:

```bash
# Homebrew users
brew uninstall finectl
brew untap sungjunlee/banksalad  # Remove old tap (if exists)
brew tap sungjunlee/finjuice
brew install finjuice

# Or direct URL install
brew install https://raw.githubusercontent.com/sungjunlee/finjuice/main/Formula/finjuice.rb

# uv users
uv tool uninstall finectl
uv tool install finjuice

# pip users
pip uninstall bsalad finectl
pip install finjuice
```

**Data compatibility**: Your existing `data/` directory works without changes. Environment variable `BSALAD_DATA_DIR` is still supported for backward compatibility.

### Changed

- **Rebrand to finjuice**: 214 files renamed across the entire codebase ([#100](https://github.com/sungjunlee/finjuice/pull/100))
  - Renamed directory: `src/bsalad/` → `src/finjuice/`
  - Updated all Python imports (242 statements)
  - Updated all documentation (771 references)
  - Updated Homebrew formula
  - Updated test suite (169 references)
  - Updated slash commands for Claude Code CLI

- **Simplified Homebrew installation**: Integrated Formula into main repository
  - Moved `Formula/finjuice.rb` from separate `homebrew-banksalad` repository to main repo
  - Supports both tap-based and direct URL installation
  - Removed need for separate tap repository maintenance
  - New tap name: `sungjunlee/finjuice` (was `sungjunlee/banksalad`)

### Fixed

- Improved naming clarity: "finjuice" (finance + juice) is more intuitive than "finectl"
- Consistent branding across all user-facing interfaces
- Fixed remaining `src/bsalad` reference in README.md

### Verified

- ✅ All 954 tests passing (100% pass rate)
- ✅ Test coverage: 81.17% (exceeds 80% requirement)
- ✅ Zero linting errors (ruff)
- ✅ CLI fully functional with new name

---

## [0.1.0] - 2025-11-XX

### Added

- **Core Features**:
  - XLSX import from Banksalad exports
  - CSV partition storage (year/month structure)
  - Rule-based tagging with YAML configuration
  - Internal transfer detection and pairing
  - Master file and report exports

- **CLI Commands**:
  - `finectl all` - Full pipeline execution
  - `finectl ingest` - Import XLSX files
  - `finectl tag` - Apply tagging rules
  - `finectl export` - Generate reports
  - `finectl init` - Initialize data directory
  - `finectl status` - Show data overview

- **Data Management**:
  - Deduplication via SHA256 row hashing
  - Import history tracking with file_id system
  - CSV partition schema v2 (89% metadata reduction)
  - Support for multiple data directories

- **Testing & Quality**:
  - 954 unit and integration tests
  - 81%+ code coverage
  - Type hints with mypy
  - Linting with ruff

- **Documentation**:
  - User guides for setup and usage
  - Schema reference (auto-generated)
  - CLI reference (auto-generated)
  - Troubleshooting guides
  - Rule editing workflow

### Technical Details

- **Stack**: Python 3.10+, Polars, Typer CLI, uv package manager
- **Storage**: CSV partitions with Apache Arrow/Parquet optimization
- **Schema**: v2 with 24 columns (see templates/schema.yaml)
- **Platforms**: macOS, Linux, Windows (via WSL)

## Release Links

- [v0.4.0](https://github.com/sungjunlee/finjuice/releases/tag/v0.4.0) - Interactive import, multi-format export, AI enhancements
- [v0.3.0](https://github.com/sungjunlee/finjuice/releases/tag/v0.3.0) - Zero-config first-run experience
- [v0.2.0](https://github.com/sungjunlee/finjuice/releases/tag/v0.2.0) - Rebrand to finjuice
- [v0.1.0](https://github.com/sungjunlee/finjuice/releases/tag/v0.1.0) - Initial release

---

**Maintained by**: [@sungjunlee](https://github.com/sungjunlee)
**License**: MIT
