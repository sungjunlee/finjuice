# Security Policy

> **Last Updated**: 2026-05-24
> **Version**: 1.1
> **Status**: Active

---

## 🔒 Security Principles

**finjuice** processes highly sensitive financial data (PII - Personally Identifiable Information). This document defines security standards for handling financial transactions, merchant information, and user account data.

### Core Principles

1. **Privacy by Default**: Financial data stays local, never transmitted externally unless explicitly authorized
2. **Minimal Logging**: Log only what's necessary for debugging, never log PII
3. **Fail Securely**: Errors should not expose sensitive data in logs or error messages
4. **Audit Trail**: Track what rules were applied, not what the specific values were

---

## 🚨 What is Financial PII?

**NEVER log these fields in any form:**

| Field Type | Examples | Risk Level |
|------------|----------|------------|
| **Transaction Amounts** | `amount`, `balance`, `total` | 🔴 CRITICAL |
| **Merchant Names** | `merchant_raw`, `counterparty` | 🔴 CRITICAL |
| **Account Identifiers** | `account`, card names, account numbers | 🔴 CRITICAL |
| **Personal Notes** | `memo_raw`, user comments | 🔴 CRITICAL |
| **Derived Values** | Aggregated totals for specific merchants/accounts | 🟡 HIGH |
| **Transaction Metadata** | Full transaction dicts, row data | 🟡 HIGH |

**Rationale**: Logs can be:
- Accidentally committed to git repositories
- Sent to centralized log aggregators (Sentry, CloudWatch, etc.)
- Exposed in CI/CD pipelines
- Readable by anyone with file system access
- Subject to GDPR/CCPA data breach reporting if leaked

---

## ✅ Safe Logging Practices

### DO: Log Structural Information

```python
# ✅ GOOD: Transaction counts
logger.info(f"Imported {count} transactions from {file_count} files")

# ✅ GOOD: Coverage statistics
logger.info(f"Tagging coverage: {tagged_count}/{total_count} ({coverage:.1f}%)")

# ✅ GOOD: Row indices for debugging
logger.warning(f"Row {row_idx} has invalid amount format")

# ✅ GOOD: Generic error types
logger.error(f"Failed to parse date at row {idx}: expected YYYY-MM-DD format")

# ✅ GOOD: Path categories without raw paths
logger.warning("Export failed (%s)", type(exc).__name__)

# ✅ GOOD: Aggregation summaries (no specific values)
logger.info(f"Detected {pair_count} transfer pairs")

# ✅ GOOD: Time/matching metadata (no amounts)
logger.debug(f"Paired transfer {group_id}: time_diff={diff:.1f}min, amount_ratio={ratio:.3f}")
```

### DON'T: Log Specific Financial Data

```python
# ❌ BAD: Transaction amount
logger.warning(f"Unknown type: '{type_raw}', keeping amount={amount}")

# ❌ BAD: Merchant name
logger.info(f"Processing transaction from {merchant}")

# ❌ BAD: Account identifier
logger.debug(f"Account {account_name} has {txn_count} transactions")

# ❌ BAD: Multiple PII fields
logger.debug(f"Transfer: {from_account} ({amount}) -> {to_account}")

# ❌ BAD: Full transaction dict (contains all PII fields)
logger.debug(f"Transaction data: {transaction}")

# ❌ BAD: Aggregated amounts for specific entities
logger.info(f"Total spend at 스타벅스: {total}")

# ❌ BAD: Local filenames and paths can include names, dates, and institutions
logger.info("Imported %s", source_file_path)
logger.warning("Export failed for %s", output_path)
```

---

## 📤 Spreadsheet Export Boundary

CSV partitions under `transactions/YYYY/MM/` are the source of truth and must
preserve user-originated values exactly. Do not sanitize, escape, or otherwise
rewrite stored transaction data to address spreadsheet behavior.

Neutralization is applied only when generating spreadsheet-targeted artifacts,
including master XLSX exports and CSV reports. At that boundary, string cells
that start with `=`, `+`, `-`, or `@`, or that place one of those prefixes
immediately after leading tab/newline characters, are prefixed with an apostrophe
so spreadsheet apps treat them as text. Numeric cells remain numeric.

This boundary keeps local data idempotent while preventing exported files from
being interpreted as formulas by spreadsheet applications.

---

## 📁 Path And Filename Privacy

Filenames and paths can contain real names, institutions, dates, cloud-drive
folder structures, or workspace names. Treat source filenames, source paths,
archive paths, export paths, import paths, and data directories as
privacy-sensitive.

Raw paths may remain in private local metadata and user-facing local CLI output
when they are needed for local operation. For example, `metadata/import_history.csv`
may preserve `original_filename`, `imported_from`, and `archived_path` so the user
can audit local imports.

Do not expose raw paths or filenames in debug logs, CI output, public issue
comments, or `--privacy compact` / `--privacy redacted` JSON. In those surfaces,
log structural context instead: counts, path kind, operation name, or exception
type.

---

## 🛡️ Implementation Guidelines

### 1. Amount Validation Logging

**Before (PII leak):**
```python
if amount > 0:
    logger.warning(f"Type='지출' but amount is positive ({amount})")
```

**After (Safe):**
```python
if amount > 0:
    logger.warning(f"Row {idx}: Type='지출' but amount is positive. May indicate refund.")
```

### 2. Transfer Pair Logging

**Before (PII leak):**
```python
logger.debug(f"Paired: {account_from} ({amount_from}) <-> {account_to} ({amount_to})")
```

**After (Safe):**
```python
logger.debug(
    f"Paired transfer {group_id}: "
    f"matched 2 transactions (time_diff={diff:.1f}min, amount_ratio={ratio:.3f})"
)
```

### 3. Error Handling

**Before (PII leak):**
```python
except ValueError as e:
    logger.error(f"Failed to process transaction: {transaction_dict}")
```

**After (Safe):**
```python
except ValueError as e:
    logger.error(f"Failed to process row {idx} in {file_name}: {e}")
```

### 4. Debug Mode

**CRITICAL**: Even with `--verbose` or `DEBUG` logging, PII must **never** be logged.

```python
# ❌ BAD: Debug mode exposes PII
logger.debug(f"Transaction details: {merchant}, {amount}, {account}")

# ✅ GOOD: Debug mode logs structural info only
logger.debug(f"Processing row {idx}: type={type_norm}, has_memo={bool(memo)}")
```

---

## 📋 Pre-Commit Checklist

Before committing code with logging:

- [ ] No `logger.*` calls contain `amount`, `merchant`, `account`, `memo` variables
- [ ] No `logger.*` calls contain source paths, filenames, archive paths, export
      paths, data directories, or path-bearing exception tracebacks
- [ ] Error messages use row indices (`row {idx}`) instead of row data
- [ ] Debug logs use boolean/count/type info, not specific values
- [ ] Run `uv run python scripts/check_pii_logging.py`

---

## 🔍 Code Review Guidelines

### Red Flags in Pull Requests

1. **Direct Variable Logging**
   ```python
   logger.info(f"Processing {merchant}")  # ❌ REJECT
   ```

2. **Dict/Object Logging**
   ```python
   logger.debug(f"Transaction: {transaction}")  # ❌ REJECT
   ```

3. **Conditional but Still PII**
   ```python
   if DEBUG:
       logger.info(f"Amount: {amount}")  # ❌ REJECT (debug is still logged!)
   ```

4. **Aggregations with Identifiers**
   ```python
   logger.info(f"Total for {merchant}: {total}")  # ❌ REJECT
   ```

5. **Raw Paths or Filenames**
   ```python
   logger.info("Imported %s", source_file_path)  # ❌ REJECT
   logger.warning("Could not parse %s: %s", file_path.name, exc)  # ❌ REJECT
   logger.exception("Failed to save config file")  # ❌ REJECT if exception may carry a path
   ```

### Approved Patterns

1. **Counts and Indices**
   ```python
   logger.info(f"Processed {count} rows")  # ✅ APPROVE
   logger.warning(f"Error at row {idx}")  # ✅ APPROVE
   ```

2. **Type/Category Info**
   ```python
   logger.debug(f"Type: {type_norm}, has_tags: {bool(tags)}")  # ✅ APPROVE
   ```

3. **Relative/Ratio Values (no absolutes)**
   ```python
   logger.debug(f"Amount ratio: {ratio:.3f}")  # ✅ APPROVE (no absolute amounts)
   ```

4. **Path-Free Failure Context**
   ```python
   logger.warning("Could not parse report filters (%s)", type(exc).__name__)  # ✅ APPROVE
   logger.info("Archived source file")  # ✅ APPROVE
   ```

---

## 🧪 Testing for PII Leaks

### Automated Checks

`scripts/check_pii_logging.py` parses Python with `ast` and inspects only logger
call arguments. It catches risky values passed through f-strings, lazy logging
arguments, `row.get("memo_raw")`, `transaction["balance"]`, and raw row or
transaction dictionaries. It also catches common path and filename leaks such as
`source_file_path`, `archive_path.name`, `config.data_dir`, and path-bearing
exception tracebacks.

The check is wired into:

- `.pre-commit-config.yaml` as `check-pii-logging`
- `just pii-log-check` and `just qa`
- GitHub CI lint gates

The checker excludes private local data paths such as `data/` and `exports/`.
Failure output is sanitized to file, line, column, and reason only; it does not
echo source lines or raw financial rows.

False-positive escape hatch:

```python
# finjuice-pii-log-allow: synthetic benchmark value, not user data
logger.info("amount=%s", amount)
```

Use the escape hatch only for a single logger call with a concrete reason. Do
not use it for real user transaction, account, merchant, memo, balance, row,
transaction, filename, or path data.

### Manual Audit Commands

```bash
# Run the structured logger PII check
uv run python scripts/check_pii_logging.py

# Check test data for real values
grep -r "스타벅스\|GS25\|맥도날드" tests/fixtures/
grep -r "신한\|우리\|국민\|하나" tests/fixtures/
```

---

## 📚 Compliance References

### GDPR (General Data Protection Regulation)

- **Article 5(1)(f)**: Security of personal data
- **Article 32**: Security of processing
- **Article 33**: Data breach notification (logs are subject to this)

**Implication**: If logs containing financial PII are exposed, this constitutes a data breach requiring notification to authorities within 72 hours.

### CCPA (California Consumer Privacy Act)

- **Section 1798.150**: Private right of action for data breaches
- **Definition**: Financial information is "sensitive personal information"

### OWASP Logging Cheat Sheet

- **Principle 1**: Log only necessary information
- **Principle 2**: Never log PII/PHI/sensitive data
- **Principle 3**: Use correlation IDs (row indices) instead of data values

Reference: https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html

---

## 🚀 Incident Response

### If PII is Found in Logs

1. **Immediate**: Delete or redact log files containing PII
2. **Audit**: Search git history for commits containing PII
3. **Patch**: Fix the logging code to remove PII
4. **Review**: Audit all other logging statements for similar issues
5. **Document**: Record the incident and remediation steps

### Git History Cleanup

If PII was committed to git:

```bash
# WARNING: Rewrites git history - coordinate with team
git filter-branch --force --index-filter \
  'git rm --cached --ignore-unmatch logs/*.log' \
  --prune-empty --tag-name-filter cat -- --all

# Force push (DANGEROUS - requires team coordination)
git push origin --force --all
```

**Better approach**: Use `git-filter-repo` or BFG Repo-Cleaner for large repos.

---

## 📞 Reporting Security Issues

If you discover a security vulnerability (including PII leaks in logs):

1. **DO NOT** open a public GitHub issue
2. Use GitHub's private vulnerability reporting flow when available, or contact
   the maintainer through the repository profile.
3. Include:
   - Location of vulnerability (file:line)
   - Type of PII exposed
   - Suggested fix (if any)

**Responsible Disclosure**: We aim to respond within 48 hours and patch critical issues within 7 days.

---

## 📝 Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.2 | 2026-05-25 | Classified filenames and paths as privacy-sensitive log data |
| 1.1 | 2026-05-24 | Documented spreadsheet export formula neutralization boundary |
| 1.0 | 2025-11-08 | Initial security policy (Issue #68) |

---

**Remember**: When in doubt, don't log it. Structural information (counts, indices, types) is almost always sufficient for debugging without exposing PII.
