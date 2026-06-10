"""Tests for the DuckDB-backed merchant context suggestion engine."""

from pathlib import Path

import polars as pl

from finjuice.pipeline.storage import csv_partition
from finjuice.pipeline.tagging.suggestions import (
    _deduplicate_rule_name,
    _escape_regex_special_chars,
    _generate_match_pattern,
    _merchant_similarity_score,
    _normalize_merchant_for_similarity,
    _sanitize_rule_name,
    apply_suggestion_to_rules,
    build_rule_dict_from_suggestion,
    build_suggested_rule_field,
    classify_merchant_kind,
    format_rules_as_banksalad_guide,
    format_rules_as_markdown,
    format_suggestions_report,
    generate_merchant_context,
    get_banksalad_category,
    get_suggested_rule_name,
    get_suggestion_coverage_stats,
)


def create_test_transactions(data_dir: Path, transactions: list[dict[str, object]]) -> None:
    """Write transactions into CSV partitions under a test data directory."""
    csv_partition.append_transactions(
        data_dir / "transactions",
        pl.DataFrame(transactions),
        deduplicate=False,
    )


def _transaction(
    row_hash: str,
    date: str,
    merchant_raw: str,
    amount: float,
    *,
    time: str = "10:00:00",
    memo_raw: str = "",
    tags_final: list[str] | None = None,
    major_raw: str | None = "정기지출",
    minor_raw: str | None = "구독",
    category_rule: str = "",
    account: str = "신한카드",
    source_row: int = 1,
) -> dict[str, object]:
    """Create a transaction row with the fields used by DuckDB suggest queries."""
    return {
        "date": date,
        "time": time,
        "datetime": f"{date}T{time}",
        "type_raw": "지출",
        "type_norm": "expense",
        "major_raw": major_raw,
        "minor_raw": minor_raw,
        "merchant_raw": merchant_raw,
        "memo_raw": memo_raw,
        "amount": amount,
        "account": account,
        "currency": "KRW",
        "row_hash": row_hash,
        "source_file_path": "test.xlsx",
        "source_row": source_row,
        "category_rule": category_rule,
        "category_final": category_rule or minor_raw or major_raw or "미분류",
        "tags_rule": [],
        "tags_ai": [],
        "tags_manual": [],
        "tags_final": tags_final,
        "confidence": None,
        "needs_review": 0,
        "is_transfer": 0,
        "transfer_group_id": "",
        "file_id": "file_1",
        "counterparty": "",
    }


def _sample_suggestion(
    *,
    is_recurring: bool = True,
    suggested_rule: dict[str, object] | None = None,
) -> dict[str, object]:
    """Create a representative merchant context suggestion."""
    result: dict[str, object] = {
        "merchant": "Netflix",
        "transaction_count": 3,
        "total_amount": 51000.0,
        "avg_amount": 17000.0,
        "amount_stddev": 0.0,
        "active_months": ["2024-10"],
        "is_recurring": is_recurring,
        "banksalad_category": {"major": "정기지출", "minor": "구독"},
        "payment_method": "신한카드",
        "time_patterns": {"weekday_pct": 0.67, "lunch_pct": 0.0},
        "similar_merchants": [
            {"merchant": "Disney+", "category": "구독", "avg_amount": 9900.0},
        ],
        "pattern": "Netflix",
        "sample_memos": ["Monthly plan"],
    }
    if suggested_rule is not None:
        result["suggested_rule"] = suggested_rule
    else:
        result["suggested_rule"] = build_suggested_rule_field(result, set())
    return result


class TestCoverageStats:
    """Tests for DuckDB-based coverage stats."""

    def test_returns_zero_for_empty_transactions_dir(self, tmp_path: Path) -> None:
        """An empty transactions dir should not raise."""
        data_dir = tmp_path / "data"
        (data_dir / "transactions").mkdir(parents=True)

        stats = get_suggestion_coverage_stats(data_dir)

        assert stats == {
            "total_count": 0,
            "untagged_count": 0,
            "suggestable_total_count": 0,
            "suggestable_untagged_count": 0,
            "transfer_excluded_count": 0,
            "transfer_excluded_untagged_count": 0,
            "coverage_before_pct": 0.0,
            "suggestable_coverage_before_pct": 0.0,
        }


class TestGenerateMerchantContext:
    """Tests for rich merchant context generation."""

    def test_generates_rich_context(self, tmp_path: Path) -> None:
        """Returns the expected merchant context fields."""
        data_dir = tmp_path / "data"
        create_test_transactions(
            data_dir,
            [
                _transaction(
                    "untagged_1",
                    "2024-10-01",
                    "Netflix",
                    -17000.0,
                    memo_raw="Monthly plan",
                    tags_final=[],
                    time="12:30:00",
                ),
                _transaction(
                    "untagged_2",
                    "2024-11-01",
                    "Netflix",
                    -17000.0,
                    memo_raw="Monthly plan",
                    tags_final=[],
                    time="12:45:00",
                    source_row=2,
                ),
                _transaction(
                    "tagged_1",
                    "2024-10-03",
                    "Disney+",
                    -9900.0,
                    memo_raw="Streaming",
                    tags_final=["구독"],
                    category_rule="구독",
                    source_row=3,
                ),
                _transaction(
                    "tagged_2",
                    "2024-11-03",
                    "Disney+",
                    -9900.0,
                    memo_raw="Streaming",
                    tags_final=["구독"],
                    category_rule="구독",
                    source_row=4,
                ),
            ],
        )

        suggestions = generate_merchant_context(data_dir, top_n=3, min_count=2)

        assert len(suggestions) == 1
        suggestion = suggestions[0]
        assert suggestion["merchant"] == "Netflix"
        assert suggestion["transaction_count"] == 2
        assert suggestion["total_amount"] == 34000.0
        assert suggestion["avg_amount"] == 17000.0
        assert suggestion["amount_stddev"] == 0.0
        assert suggestion["active_months"] == ["2024-10", "2024-11"]
        assert suggestion["is_recurring"] is True
        assert suggestion["banksalad_category"] == {"major": "정기지출", "minor": "구독"}
        assert suggestion["payment_method"] == "신한카드"
        assert suggestion["time_patterns"] == {"weekday_pct": 1.0, "lunch_pct": 1.0}
        assert suggestion["similar_merchants"] == [
            {
                "merchant": "Disney+",
                "category": "구독",
                "avg_amount": 9900.0,
                "transaction_count": 2,
            }
        ]
        assert suggestion["pattern"] == "Netflix"
        assert suggestion["sample_memos"] == ["Monthly plan"]
        # suggested_rule must be present
        rule = suggestion["suggested_rule"]
        assert rule["name"] == "suggested_netflix"
        assert rule["match"] == "Netflix"
        assert rule["category"] == "구독"
        assert rule["tags"] == ["구독", "정기지출"]
        # recurring merchant gets priority boost
        assert rule["priority"] == 85

    def test_respects_top_n_and_min_count(self, tmp_path: Path) -> None:
        """Applies min-count filtering and top-N limiting."""
        data_dir = tmp_path / "data"
        transactions: list[dict[str, object]] = []
        for merchant_index in range(5):
            for occurrence in range(merchant_index + 1):
                transactions.append(
                    _transaction(
                        f"hash_{merchant_index}_{occurrence}",
                        "2024-10-01",
                        f"Merchant {merchant_index}",
                        -1000.0 * (merchant_index + 1),
                        tags_final=[],
                        source_row=merchant_index * 10 + occurrence + 1,
                    )
                )
        create_test_transactions(data_dir, transactions)

        suggestions = generate_merchant_context(data_dir, top_n=2, min_count=3)

        assert len(suggestions) == 2
        assert [suggestion["merchant"] for suggestion in suggestions] == [
            "Merchant 4",
            "Merchant 3",
        ]

    def test_flags_known_payment_gateway_merchants_as_ambiguous(self, tmp_path: Path) -> None:
        """Known PG processors should remain visible but default to skip_rule."""
        data_dir = tmp_path / "data"
        create_test_transactions(
            data_dir,
            [
                _transaction("pg_1", "2024-10-01", "케이지이니시스", -10000.0, tags_final=[]),
                _transaction("pg_2", "2024-10-02", "케이지이니시스", -12000.0, tags_final=[]),
                _transaction("ali_1", "2024-10-03", "ALIPAY CONNECT", -30000.0, tags_final=[]),
                _transaction("ali_2", "2024-10-04", "ALIPAY CONNECT", -31000.0, tags_final=[]),
            ],
        )

        suggestions = generate_merchant_context(data_dir, top_n=10, min_count=2)

        by_merchant = {suggestion["merchant"]: suggestion for suggestion in suggestions}
        assert by_merchant["케이지이니시스"]["merchant_kind"] == "payment_gateway"
        assert by_merchant["케이지이니시스"]["ambiguous_reason"] == "payment_gateway"
        assert by_merchant["케이지이니시스"]["default_action"] == "skip_rule"
        assert by_merchant["케이지이니시스"]["auto_apply_eligible"] is False
        assert by_merchant["ALIPAY CONNECT"]["merchant_kind"] == "payment_gateway"
        assert by_merchant["ALIPAY CONNECT"]["default_action"] == "skip_rule"

    def test_payment_gateway_detection_is_conservative_for_similar_substrings(self) -> None:
        """Ordinary merchants with similar text should not be marked as PGs."""
        assert classify_merchant_kind("KCPARK CAFE") == {
            "merchant_kind": "merchant",
            "ambiguous_reason": None,
            "default_action": "create_rule",
        }
        assert classify_merchant_kind("STRIPE CAFE") == {
            "merchant_kind": "merchant",
            "ambiguous_reason": None,
            "default_action": "create_rule",
        }

    def test_file_id_filter_limits_suggestions_to_one_import(self, tmp_path: Path) -> None:
        """rules suggest engine should support import-scoped curation."""
        data_dir = tmp_path / "data"
        create_test_transactions(
            data_dir,
            [
                {
                    **_transaction(
                        "new_1",
                        "2024-10-01",
                        "New Import Merchant",
                        -1000.0,
                        tags_final=[],
                    ),
                    "file_id": "250607_1",
                },
                {
                    **_transaction(
                        "new_2",
                        "2024-10-02",
                        "New Import Merchant",
                        -1000.0,
                        tags_final=[],
                    ),
                    "file_id": "250607_1",
                    "source_row": 2,
                },
                {
                    **_transaction("old_1", "2024-10-03", "Old Merchant", -1000.0, tags_final=[]),
                    "file_id": "250606_1",
                    "source_row": 3,
                },
                {
                    **_transaction("old_2", "2024-10-04", "Old Merchant", -1000.0, tags_final=[]),
                    "file_id": "250606_1",
                    "source_row": 4,
                },
            ],
        )

        suggestions = generate_merchant_context(
            data_dir,
            top_n=10,
            min_count=2,
            file_id="250607_1",
        )

        assert [suggestion["merchant"] for suggestion in suggestions] == ["New Import Merchant"]

    def test_skips_existing_rules(self, tmp_path: Path) -> None:
        """Avoids suggesting merchants already covered by rules.yaml."""
        data_dir = tmp_path / "data"
        create_test_transactions(
            data_dir,
            [
                _transaction("hash_1", "2024-10-01", "Netflix", -17000.0, tags_final=[]),
                _transaction("hash_2", "2024-10-02", "Netflix", -17000.0, tags_final=[]),
                _transaction("hash_3", "2024-10-03", "New Merchant", -3000.0, tags_final=[]),
                _transaction("hash_4", "2024-10-04", "New Merchant", -3000.0, tags_final=[]),
            ],
        )
        rules_file = data_dir / "rules.yaml"
        rules_file.write_text(
            """
version: 1
rules:
  - name: netflix
    match: "Netflix"
    fields: [merchant_raw]
    tags: ["구독"]
    priority: 80
""",
            encoding="utf-8",
        )

        suggestions = generate_merchant_context(data_dir, rules_file=rules_file, min_count=2)

        assert len(suggestions) == 1
        assert suggestions[0]["merchant"] == "New Merchant"

    def test_includes_fuzzy_cluster_for_korean_spacing_variants(self, tmp_path: Path) -> None:
        """Korean spacing variants should be surfaced as suggestion-only clusters."""
        data_dir = tmp_path / "data"
        create_test_transactions(
            data_dir,
            [
                _transaction("starbucks_1", "2024-10-01", "스타벅스", -5000.0, tags_final=[]),
                _transaction("starbucks_2", "2024-10-02", "스타 벅스", -5100.0, tags_final=[]),
            ],
        )

        suggestions = generate_merchant_context(data_dir, top_n=2, min_count=1)

        assert {suggestion["merchant"] for suggestion in suggestions} == {"스타벅스", "스타 벅스"}
        for suggestion in suggestions:
            cluster = suggestion["merchant_cluster"]
            assert cluster["reason"] == "normalized_merchant_match"
            assert cluster["confidence"] == 1.0
            member_merchants = {member["merchant"] for member in cluster["members"]}
            assert member_merchants == {"스타벅스", "스타 벅스"}


class TestFormatHelpers:
    """Tests for remaining formatting and regex helpers."""

    def test_format_suggestions_report(self) -> None:
        """The report should expose the new context fields."""
        report = format_suggestions_report([_sample_suggestion()])

        assert "Merchant Context for Rules Suggest" in report
        assert "Netflix" in report
        assert "정기지출 / 구독" in report
        assert "Monthly plan" in report
        assert "자동 적용 태그: 구독, 정기지출" in report

    def test_escape_regex_special_chars(self) -> None:
        """Escapes characters with regex meaning."""
        assert _escape_regex_special_chars("(주)이마트") == r"\(주\)이마트"
        assert _escape_regex_special_chars("test.com") == r"test\.com"
        assert _escape_regex_special_chars("C++") == r"C\+\+"

    def test_generate_match_pattern(self) -> None:
        """Generates regex-safe patterns from merchant names."""
        assert _generate_match_pattern("스타벅스 강남점") == "스타벅스|스타벅스 강남점"
        pattern = _generate_match_pattern("지에스(GS)25")
        assert r"\(" in pattern

    def test_sanitize_rule_name(self) -> None:
        """Normalizes merchant names for persisted rule ids."""
        assert _sanitize_rule_name("스타벅스 강남점") == "스타벅스_강남점"
        assert _sanitize_rule_name("(주)카카오") == "주_카카오"
        assert get_suggested_rule_name("GS25") == "suggested_gs25"

    def test_merchant_similarity_score_covers_spacing_punctuation_and_case(self) -> None:
        """Similarity scoring should be deterministic and conservative."""
        assert _normalize_merchant_for_similarity("스타 벅스") == "스타벅스"
        assert _merchant_similarity_score("스타 벅스", "스타벅스") == 1.0
        assert _merchant_similarity_score("GS-25", "gs 25") == 1.0
        assert _merchant_similarity_score("스타벅스", "이디야커피") < 0.5


class TestRuleApplication:
    """Tests for building and applying rules from merchant context."""

    def test_build_rule_dict_uses_raw_banksalad_categories(self) -> None:
        """Auto-applied rules should use raw category values as tags/category."""
        rule_dict = build_rule_dict_from_suggestion(_sample_suggestion())

        assert rule_dict["name"] == "suggested_netflix"
        assert rule_dict["match"] == "Netflix"
        assert rule_dict["tags"] == ["구독", "정기지출"]
        assert rule_dict["category"] == "구독"
        assert rule_dict["priority"] == 80

    def test_apply_suggestion_to_rules(self, tmp_path: Path) -> None:
        """Appends a valid rule to rules.yaml."""
        rules_path = tmp_path / "rules.yaml"
        rules_path.write_text("version: 1\nrules: []\n", encoding="utf-8")

        result = apply_suggestion_to_rules(_sample_suggestion(), rules_path)

        assert result.name == "suggested_netflix"
        assert result.match == "Netflix"
        assert result.tags == ["구독", "정기지출"]
        assert result.category == "구독"

        content = rules_path.read_text(encoding="utf-8")
        assert "created_by: rules suggest" in content
        assert "Auto-suggested for Netflix" in content

    def test_apply_with_modified_tags(self, tmp_path: Path) -> None:
        """Modified tags should override the default raw category tags."""
        rules_path = tmp_path / "rules.yaml"
        rules_path.write_text("version: 1\nrules: []\n", encoding="utf-8")

        result = apply_suggestion_to_rules(
            _sample_suggestion(),
            rules_path,
            modified_tags=["구독", "디지털서비스"],
        )

        assert result.tags == ["구독", "디지털서비스"]


class TestBanksaladGuideFormatting:
    """Tests for unchanged Banksalad guide formatting helpers."""

    def test_get_banksalad_category(self) -> None:
        """Known tags should still map to a Banksalad guide category."""
        assert get_banksalad_category(["카페"]) == "식비:카페"
        assert get_banksalad_category(["알수없는태그"]) == "기타:기타"

    def test_format_rules_guides(self) -> None:
        """Guide formatters should still render existing rules."""
        from finjuice.pipeline.tagging.models import TagRule

        rules = [
            TagRule(
                name="cafe_starbucks",
                match="스타벅스",
                fields=["merchant_raw"],
                tags=["카페", "커피"],
                priority=80,
            ),
        ]

        guide = format_rules_as_banksalad_guide(rules)
        markdown = format_rules_as_markdown(rules)

        assert "뱅크샐러드 카테고리 매핑 가이드" in guide
        assert "식비:카페" in guide
        assert "| 규칙명 | 패턴 | 권장 카테고리 | 태그 |" in markdown


class TestSuggestedRuleField:
    """Tests for the suggested_rule field in suggestions."""

    def test_suggested_rule_has_required_keys(self) -> None:
        """Every suggested_rule must contain name, match, category, tags, priority."""
        suggestion = _sample_suggestion()
        rule = suggestion["suggested_rule"]
        for key in ("name", "match", "category", "tags", "priority"):
            assert key in rule, f"Missing key: {key}"

    def test_suggested_rule_name_generation(self) -> None:
        """Rule name uses suggested_ prefix with sanitized merchant."""
        rule = build_suggested_rule_field(
            {
                "merchant": "GS25",
                "pattern": "GS25",
                "banksalad_category": {"major": "생활", "minor": None},
                "is_recurring": False,
            },
            set(),
        )
        assert rule["name"] == "suggested_gs25"

    def test_suggested_rule_category_fallback(self) -> None:
        """Category should fallback: minor -> major -> 미분류."""
        # minor present
        rule = build_suggested_rule_field(
            {
                "merchant": "M1",
                "pattern": "M1",
                "banksalad_category": {"major": "식비", "minor": "카페"},
                "is_recurring": False,
            },
            set(),
        )
        assert rule["category"] == "카페"

        # minor absent, major present
        rule = build_suggested_rule_field(
            {
                "merchant": "M2",
                "pattern": "M2",
                "banksalad_category": {"major": "식비", "minor": None},
                "is_recurring": False,
            },
            set(),
        )
        assert rule["category"] == "식비"

        # both absent
        rule = build_suggested_rule_field(
            {
                "merchant": "M3",
                "pattern": "M3",
                "banksalad_category": {"major": None, "minor": None},
                "is_recurring": False,
            },
            set(),
        )
        assert rule["category"] == "미분류"

    def test_suggested_rule_priority_recurring_boost(self) -> None:
        """Recurring merchants get priority 85, others get 80."""
        rule_recurring = build_suggested_rule_field(
            {
                "merchant": "Netflix",
                "pattern": "Netflix",
                "banksalad_category": {"major": "정기지출", "minor": "구독"},
                "is_recurring": True,
            },
            set(),
        )
        assert rule_recurring["priority"] == 85

        rule_normal = build_suggested_rule_field(
            {
                "merchant": "SomeShop",
                "pattern": "SomeShop",
                "banksalad_category": {"major": "생활", "minor": None},
                "is_recurring": False,
            },
            set(),
        )
        assert rule_normal["priority"] == 80

    def test_suggested_rule_name_conflict_detection(self) -> None:
        """Name conflicts get numeric suffix."""
        existing = {"suggested_netflix"}
        rule = build_suggested_rule_field(
            {
                "merchant": "Netflix",
                "pattern": "Netflix",
                "banksalad_category": {"major": "정기지출", "minor": "구독"},
                "is_recurring": False,
            },
            existing,
        )
        assert rule["name"] == "suggested_netflix_2"

    def test_deduplicate_rule_name_no_conflict(self) -> None:
        """No suffix when name is unique."""
        assert _deduplicate_rule_name("foo", set()) == "foo"

    def test_deduplicate_rule_name_multiple_conflicts(self) -> None:
        """Increments suffix past existing names."""
        existing = {"foo", "foo_2", "foo_3"}
        assert _deduplicate_rule_name("foo", existing) == "foo_4"

    def test_format_report_includes_suggested_rule(self) -> None:
        """Plain-text report should include suggested_rule info."""
        report = format_suggestions_report([_sample_suggestion()])
        assert "suggested_rule:" in report
        assert "suggested_netflix" in report

    def test_generate_context_avoids_batch_name_collisions(self, tmp_path: Path) -> None:
        """Multiple suggestions with the same sanitized name get distinct names."""
        data_dir = tmp_path / "data"
        # Create two merchants that sanitize to the same name
        create_test_transactions(
            data_dir,
            [
                _transaction("h1", "2024-10-01", "ABC DEF", -1000.0, tags_final=[]),
                _transaction(
                    "h2",
                    "2024-10-02",
                    "ABC DEF",
                    -1000.0,
                    tags_final=[],
                    source_row=2,
                ),
                _transaction(
                    "h3",
                    "2024-10-03",
                    "ABC_DEF",
                    -1000.0,
                    tags_final=[],
                    source_row=3,
                ),
                _transaction(
                    "h4",
                    "2024-10-04",
                    "ABC_DEF",
                    -1000.0,
                    tags_final=[],
                    source_row=4,
                ),
            ],
        )

        suggestions = generate_merchant_context(data_dir, top_n=10, min_count=2)

        names = [s["suggested_rule"]["name"] for s in suggestions]
        # All names should be unique
        assert len(names) == len(set(names))
