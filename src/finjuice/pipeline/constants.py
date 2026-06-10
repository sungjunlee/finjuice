"""
Global constants for finjuice.

This module defines all magic numbers used throughout the codebase
with documentation of their rationale and design trade-offs.

See Also:
    - templates/schema.yaml: Schema version and column definitions
    - CLAUDE.md: Project design decisions
"""

from typing import Final

# ==============================================================================
# Hash & Deduplication
# ==============================================================================

HASH_LENGTH_CHARS: Final = 16
"""Length of truncated SHA256 hash for row deduplication (characters).

Hash space: 16^16 = 18,446,744,073,709,551,616 (18.4 quintillion combinations)

Collision Probability Analysis:
- Birthday paradox: 50% collision at sqrt(16^16) ≈ 4.3 billion transactions
- At 10,000 transactions: ~0.00000003% collision probability
- At 100,000 transactions: ~0.000003% collision probability
- At 1,000,000 transactions: ~0.0003% collision probability
- At 10,000,000 transactions: ~0.03% collision probability

Design Choice (updated from 10 → 16 chars):
- Previous: 10 chars had ~0.5% collision risk at 100K transactions
- Current: 16 chars reduces collision risk by factor of 1,000,000
- Token cost: Additional 6 chars per row (~1.5K tokens for 2,269 rows)
- Trade-off: Negligible collision risk with minimal token overhead

Migration:
- Existing 10-char hashes are backward-compatible (read-only)
- New hashes generated with 16 chars
- Migration script: scripts/migrate_hash_length.py

See Also:
    - templates/schema.yaml: Hash design rationale and migration history
    - src/finjuice/pipeline/ingest/deduplication.py: Implementation
    - scripts/migrate_hash_length.py: Migration tool (10 → 16 chars)
"""

FILE_ID_LENGTH_CHARS: Final = 8
"""Length of file_id identifier (characters).

Format: YYMMDD_N (e.g., "241027_1")
- 6 chars for date (YYMMDD)
- 1 char for underscore separator
- 1+ chars for sequence number

For non-standard filenames, uses 8-char SHA256 prefix.

Rationale:
- Human-readable for standard Banksalad exports
- Short enough for token efficiency
- Unique within personal finance context (daily imports rare)

See Also:
    - src/finjuice/pipeline/metadata/import_history.py: generate_file_id()
    - templates/schema.yaml: file_id field definition
"""

ASSET_DERIVED_ID_HASH_LENGTH_CHARS: Final = 12
"""Length of SHA256 prefix for derived asset identifiers.

Used when account_id/instrument_id is missing in asset snapshot sheets.
Final ID format:
    - account: acc_<12hex>
    - instrument: ins_<12hex>
"""

ASSET_ACCOUNT_ID_PREFIX: Final = "acc"
"""Prefix for derived account identifiers in asset snapshots."""

ASSET_INSTRUMENT_ID_PREFIX: Final = "ins"
"""Prefix for derived instrument identifiers in asset snapshots."""

# ==============================================================================
# Transfer Detection
# ==============================================================================

DEFAULT_TRANSFER_TIME_WINDOW_MINUTES: Final = 5
"""Time window for matching transfer pairs (minutes).

Rationale:
- Based on observed Banksalad export behavior
- Typical bank processing delays: 1-5 minutes
- Allows for slight timestamp discrepancies between debit/credit
- Trade-off: Wider window increases false positive rate

Real-world observations:
- Credit card payments: usually within 1-3 minutes
- Inter-bank transfers: can be up to 5 minutes
- Internal account transfers: typically instant (0-1 minute)

Tuning guidance:
- Increase (e.g., 10) if legitimate transfers are missed
- Decrease (e.g., 3) if too many false matches occur
- Depends on bank's processing speed and timestamp precision

See Also:
    - src/finjuice/pipeline/transfer/detection.py: detect_transfer_pairs()
"""

DEFAULT_TRANSFER_AMOUNT_TOLERANCE: Final = 0.01
"""Amount tolerance for transfer matching (relative).

Set to 1% to handle:
- Rounding errors in currency conversion
- Floating-point arithmetic imprecision
- Minor bank processing fees (rare in internal transfers)

Formula: abs(amount1 - amount2) / max(abs(amount1), abs(amount2)) <= tolerance

Examples:
- 100,000 KRW: accepts ±1,000 KRW (1%)
- 1,000,000 KRW: accepts ±10,000 KRW (1%)
- 10,000,000 KRW: accepts ±100,000 KRW (1%)

Rationale:
- Most internal transfers are exact (0% diff)
- 1% tolerance catches edge cases without excessive false positives
- Typical bank fees (if any) are <1% for personal accounts

Tuning guidance:
- Increase (e.g., 0.02) if legitimate transfers have small fees
- Decrease (e.g., 0.001) for stricter matching
- Consider absolute tolerance (e.g., ±100 KRW) for small amounts

See Also:
    - src/finjuice/pipeline/transfer/detection.py: detect_transfer_pairs()
"""

# ==============================================================================
# Tagging Rules
# ==============================================================================

MIN_RULE_PRIORITY: Final = 0
"""Minimum priority value for tagging rules.

Lower priority rules are evaluated after higher priority ones.
Priority 0 is lowest (fallback/catch-all rules).
"""

MAX_RULE_PRIORITY: Final = 100
"""Maximum priority value for tagging rules.

Higher priority rules are evaluated first.
Priority 100 is highest (exact match/overrides).

Common priority ranges:
- 90-100: Exact matches (e.g., specific account numbers)
- 70-89: Strong patterns (e.g., merchant names)
- 50-69: General categories (e.g., keywords)
- 0-49: Fallback/catch-all rules
"""

DEFAULT_RULE_PRIORITY: Final = 50
"""Default priority for rules without explicit priority.

Set to middle value to allow both higher and lower overrides.
"""

DEFAULT_RULE_CONFIDENCE: Final = 1.0
"""Default confidence for manual rules.

Manual rules (from rules.yaml) are assumed 100% confident.
AI-generated rules may have lower confidence values.
"""

DEFAULT_TAG_CONFIDENCE_THRESHOLD: Final = 0.7
"""Minimum confidence for auto-applying AI tags (70%).

Tags with confidence below this threshold are flagged for review.

Rationale:
- 70% balances automation vs accuracy
- Based on typical AI classification thresholds
- Higher threshold = more manual review, higher accuracy
- Lower threshold = more automation, more errors

Tuning guidance:
- Increase (e.g., 0.8) if too many incorrect auto-tags
- Decrease (e.g., 0.6) if too many transactions need manual review

Note: Currently not used (AI tagging is Phase 2 feature).
"""

# ==============================================================================
# CSV Schema
# ==============================================================================

SCHEMA_VERSION: Final = 4
"""Current data directory schema version.

Version history:
- v1: Initial schema with full source metadata
- v2: Optimized schema with file_id system (89% metadata reduction)
- v3: Category columns plus transfer candidate/confirmed state

See Also:
    - templates/schema.yaml: Full schema definition and migration history
"""

CSV_SCHEMA_VERSION: Final = SCHEMA_VERSION
"""Backward-compatible alias for the current CSV partition schema version."""

# ==============================================================================
# Amount Validation (Not yet implemented - placeholder for future)
# ==============================================================================

MAX_REASONABLE_AMOUNT_KRW: Final = 999_000_000
"""Maximum reasonable transaction amount (Korean Won).

Set to 999 million KRW (~750K USD) as upper bound for personal finance.

Rationale:
- Catches data entry errors (e.g., missing decimal point)
- Catches corrupted XLSX exports
- Prevents floating-point overflow issues
- Personal finance context: rare to have >999M single transaction

Real-world examples within bounds:
- Apartment purchase: ~500M KRW (within limit)
- Monthly salary transfer: ~10M KRW (within limit)
- Investment transfer: ~100M KRW (within limit)

Examples that should be rejected:
- 999,999,999,999 KRW (likely corrupted data)

If legitimate transaction exceeds limit:
- User can adjust via config
- Consider increasing to 9,999,000,000 (9.9B) for corporate use

Note: Currently not enforced. Add validation in _normalize_amount() if needed.
"""

MIN_REASONABLE_AMOUNT_KRW: Final = 0.01
"""Minimum non-zero transaction amount (Korean Won).

Zero-amount transactions should be filtered as data errors.
Amounts below 0.01 KRW are impractical for personal finance.

Note: Currently not enforced. Add validation if needed.
"""

# ==============================================================================
# Performance & Storage (Not yet implemented - placeholder for future)
# ==============================================================================

DEFAULT_CHUNK_SIZE: Final = 1000
"""Default chunk size for batch processing operations.

Used for:
- Reading large CSV files in chunks
- Batch AI tagging requests
- Batch CSV partition writes

Rationale:
- Balance between memory usage and I/O efficiency
- 1000 rows ≈ 2-5MB of transaction data
- Typical personal finance: <10K transactions total

Note: Currently not used. Add chunking logic if memory becomes an issue.
"""

MAX_PARTITION_SIZE_ROWS: Final = 10_000
"""Soft limit for CSV partition size (informational warning if exceeded).

Monthly partitions with >10K rows may indicate:
- Data quality issues (duplicate imports)
- Business account usage (high transaction volume)
- Need for daily partitioning instead of monthly

Note: This is a warning threshold, not a hard limit.
CSV partitions can handle much larger sizes.
"""

# ==============================================================================
# Version Constraints
# ==============================================================================

RULES_YAML_VERSION: Final = 1
"""Current version of rules.yaml format.

Future versions may add new fields or change validation logic.
"""

# ==============================================================================
# Subprocess Timeouts
# ==============================================================================

SUBPROCESS_TIMEOUT_SHORT: Final = 5
"""Short timeout for quick subprocess operations (seconds).

Used for:
- Version checks (git --version, claude --version)
- Opening files in external apps (open, xdg-open)

Rationale:
- These operations should complete almost instantly
- 5 seconds allows for slow disk/network but catches hangs
"""

SUBPROCESS_TIMEOUT_MEDIUM: Final = 10
"""Medium timeout for typical subprocess operations (seconds).

Used for:
- Git operations (init, add, commit)
- File system operations

Rationale:
- Git operations may be slow on large repos or slow storage
- 10 seconds is generous for typical personal finance data
"""

SUBPROCESS_TIMEOUT_LONG: Final = 60
"""Long timeout for AI/network operations (seconds).

Used for:
- Claude Code CLI calls
- Network-dependent operations

Rationale:
- AI model responses can take 30-60 seconds for complex queries
- Network latency varies significantly
"""

# ==============================================================================
# Reporting & Export
# ==============================================================================

STANDARD_CSV_REPORTS: Final = (
    ("monthly_spend", "monthly_spend.csv"),
    ("by_category", "by_category.csv"),
    ("by_tag", "by_tag.csv"),
    ("by_account", "by_account.csv"),
    ("transfers", "transfers.csv"),
)
"""Standard CSV reports generated by generate_all_reports().

Each entry is ``(summary_key, filename)`` in generation order.
"""

REPORTS_COUNT: Final = len(STANDARD_CSV_REPORTS)
"""Expected number of standard CSV reports.

Reports:
1. monthly_spend.csv: Monthly spending summary
2. by_category.csv: Spending by category
3. by_tag.csv: Spending by tag
4. by_account.csv: Net spending by account
5. transfers.csv: Transfer audit log

Used for verification that all reports were generated successfully.

See Also:
    - src/finjuice/pipeline/export/reports.py: generate_all_reports()
"""
