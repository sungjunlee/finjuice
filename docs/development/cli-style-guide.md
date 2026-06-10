# CLI Output Style Guide

> **Status**: Active
> **Created**: 2025-12-14
> **Issue**: #89

This guide establishes consistent CLI output formatting standards for finjuice.

---

## Overview

All CLI output should use the semantic output helpers from `finjuice.pipeline.cli.output` module. This ensures:

- **Consistency**: Same visual style across all commands
- **Accessibility**: Proper color usage for different message types
- **Maintainability**: Centralized styling that's easy to update
- **Testability**: Mockable console output for testing

---

## Output Module API

### Import

```python
from finjuice.pipeline.cli.output import (
    console,      # Global Rich Console instance
    success,      # Success messages (green + checkmark)
    info,         # Informational messages (blue)
    warning,      # Warning messages (yellow)
    error,        # Error messages (red)
    error_with_ai_hint,  # Error with AI troubleshooting prompt
    step,         # Numbered step indicators
    section,      # Section headers with separators
    panel_info,   # Bordered panels for important info
    table_summary,  # Key-value summary tables
    bullet_list,  # Bulleted lists
    progress_indicator,  # Progress percentage
    newline,      # Blank line spacing
    hr,           # Horizontal rule
)
```

---

## Message Types

### Success Messages

Use for completed operations and positive confirmations.

```python
# Good: Use success() helper
success("Validation complete!")
# Output: [green]✅ Validation complete![/green]

success("3 transactions imported", prefix="")  # Custom prefix
# Output: [green]3 transactions imported[/green]

# Bad: Direct console.print with inline styling
console.print("[green]✅ Validation complete![/green]")  # Don't do this
```

### Informational Messages

Use for status updates and neutral information.

```python
# Good: Use info() helper
info("Processing 150 transactions...")
# Output: [blue]ℹ️  Processing 150 transactions...[/blue]

# Bad: Direct styling
console.print("[blue]ℹ️  Processing...[/blue]")  # Don't do this
```

### Warning Messages

Use for non-critical issues that don't stop execution.

```python
# Good: Use warning() helper
warning("No rules matched this transaction")
# Output: [yellow]⚠️  No rules matched this transaction[/yellow]

# Bad: Direct styling
console.print("[yellow]⚠️  Warning...[/yellow]")  # Don't do this
```

### Error Messages

Use for errors that prevent successful completion.

```python
# Good: Use error() helper
error("Failed to load rules.yaml")
# Output: [red]❌ Failed to load rules.yaml[/red]

# With AI troubleshooting hint
error_with_ai_hint(
    "No XLSX files found in imports/",
    "뱅크샐러드에서 파일을 어떻게 내보내고 어디에 넣어야 하지?"
)
# Output:
# ❌ No XLSX files found in imports/
#
# 💡 AI에게 물어보기:
# ╭─ Claude/ChatGPT 프롬프트 ─────╮
# │ 뱅크샐러드에서 파일을...       │
# ╰──────────────────────────────╯

# Bad: Direct styling
console.print("[red]❌ Error message[/red]")  # Don't do this
```

---

## Structured Output

### Section Headers

Use for major command sections.

```python
section("Validation Results")
# Output:
#
# ════════════════════════════════════════
# Validation Results
# ════════════════════════════════════════
#
```

### Numbered Steps

Use for multi-step processes.

```python
step(1, "Validating rules...")
step(2, "Checking imports...")
step(3, "Processing transactions...")
# Output:
# [cyan][1][/cyan] Validating rules...
# [cyan][2][/cyan] Checking imports...
# [cyan][3][/cyan] Processing transactions...
```

### Panels

Use for important information blocks.

```python
panel_info(
    "Next steps:\n1. Edit rules.yaml\n2. Run finjuice tag",
    title="Next Steps"
)
# Output:
# ╭─ Next Steps ─────────────────────╮
# │ Next steps:                      │
# │ 1. Edit rules.yaml               │
# │ 2. Run finjuice tag              │
# ╰──────────────────────────────────╯
```

### Summary Tables

Use for key-value summaries.

```python
table_summary(
    "Validation Summary",
    [
        ("Total Rules", "15"),
        ("Passed", "12"),
        ("Warnings", "3"),
    ]
)
# Output:
# ┏━━━━━━━━━━━━━┳━━━━━━━┓
# ┃ Item        ┃ Value ┃
# ┡━━━━━━━━━━━━━╇━━━━━━━┩
# │ Total Rules │ 15    │
# │ Passed      │ 12    │
# │ Warnings    │ 3     │
# └─────────────┴───────┘
```

### Bullet Lists

Use for feature lists and options.

```python
bullet_list(["Option A", "Option B", "Option C"])
# Output:
# • Option A
# • Option B
# • Option C
```

### Progress Indicators

Use for long-running operations.

```python
progress_indicator(7, 10, "Processing files")
# Output: [cyan][70%] Processing files (7/10)[/cyan]
```

---

## Logging vs Console Output

### Use `logger` for:

- Debug information (internal state, timing)
- Verbose mode details
- File operations auditing
- Error stack traces

```python
import logging
logger = logging.getLogger(__name__)

logger.debug(f"Processing partition: {partition_path}")
logger.info(f"Loaded {len(df)} transactions")
logger.warning(f"Skipped malformed row: {row}")
logger.error(f"Failed to read file: {e}", exc_info=True)
```

### Use `console` (via output helpers) for:

- User-facing messages
- Command results
- Progress updates
- Interactive prompts

```python
from finjuice.pipeline.cli.output import success, warning, info

info("Starting import...")
success("Import complete!")
warning("2 duplicate transactions skipped")
```

---

## Icon Reference

| Icon | Use Case | Helper Function |
|------|----------|-----------------|
| ✅ | Success/completion | `success()` |
| ℹ️ | Information | `info()` |
| ⚠️ | Warning/caution | `warning()` |
| ❌ | Error/failure | `error()` |
| 💡 | Tips/suggestions | (in `error_with_ai_hint()`) |
| 📊 | Statistics/data | (manual, in panels) |
| 📁 | File operations | (manual) |
| 🎉 | Celebration/first-run | (manual) |

---

## Color Reference

| Color | Semantic Meaning | Rich Markup |
|-------|------------------|-------------|
| Green | Success, positive | `[green]...[/green]` |
| Blue | Information, neutral | `[blue]...[/blue]` |
| Yellow | Warning, attention | `[yellow]...[/yellow]` |
| Red | Error, failure | `[red]...[/red]` |
| Cyan | Emphasis, highlight | `[cyan]...[/cyan]` |
| Dim | Secondary info | `[dim]...[/dim]` |
| Bold | Important | `[bold]...[/bold]` |

---

## Korean Language Support

For Korean messages, use the same helpers directly:

```python
from finjuice.pipeline.cli.output import success, warning, error, info

success("가져오기 완료!")
warning("태그되지 않은 거래 2건")
error("처리에 실패했습니다")
info("다음 단계를 확인하세요")
```

---

## Migration Guide

### Before (Legacy Pattern)

```python
from rich.console import Console
console = Console()

# Direct inline styling
console.print("[green]✅ Success![/green]")
console.print("[yellow]⚠️  Warning...[/yellow]")
console.print("[red]❌ Error![/red]")
```

### After (Recommended Pattern)

```python
from finjuice.pipeline.cli.output import success, warning, error

# Semantic helpers
success("Success!")
warning("Warning...")
error("Error!")
```

### Migration Steps

1. Replace local `console = Console()` with import from output module
2. Replace `console.print("[green]✅ ...` with `success("...")`
3. Replace `console.print("[yellow]⚠️ ...` with `warning("...")`
4. Replace `console.print("[red]❌ ...` with `error("...")`
5. Replace `console.print("[blue]ℹ️ ...` with `info("...")`

---

## Anti-Patterns

### Don't

```python
# Local Console instance (fragmented styling)
console = Console()

# Inline color markup (hard to maintain)
console.print("[green]✅ Done![/green]")

# print() function (not styled)
print("Processing...")

# typer.echo() (deprecated pattern)
typer.echo("Result: OK")

# Inconsistent icons
console.print("[green]OK Done![/green]")   # Wrong: should use ✅
console.print("[green]>>> Done![/green]")  # Wrong: inconsistent prefix
```

### Do

```python
# Import from output module
from finjuice.pipeline.cli.output import success, info, console

# Use semantic helpers
success("Done!")

# Use shared console for custom output
console.print(Table(...))  # Tables, complex layouts

# Log internal operations
logger.debug(f"Processing {file_path}")
```

---

## Testing

When testing CLI output, mock the console:

```python
from unittest.mock import patch
from io import StringIO

def test_success_output():
    with patch('finjuice.pipeline.cli.output.console') as mock_console:
        success("Test message")
        mock_console.print.assert_called_once()
```

---

## Command-Specific Guidelines

### `status` Command

- Use `table_summary()` for overview data
- Use `info()` for data directory source
- Use `warning()` for missing data alerts

### `stats` Command

- Use `panel_info()` for statistical summaries
- Use `table_summary()` for top tags/merchants
- Include period information in panel title

### `all` (Pipeline) Command

- Use `step()` for each pipeline phase
- Use `success()` for phase completion
- Use `section()` to separate major phases
- Show final summary in `panel_info()`

### `doctor` Command

- Use `success()` for passing checks
- Use `warning()` for non-critical issues
- Use `error()` for blocking problems
- Group checks with `section()`

---

## See Also

- [Source: output.py](../../src/finjuice/pipeline/cli/output.py)
- [Rich Documentation](https://rich.readthedocs.io/)
- [Typer Documentation](https://typer.tiangolo.com/)

---

**Note**: This guide documents the target state. Existing commands may use legacy patterns and should be migrated incrementally.
