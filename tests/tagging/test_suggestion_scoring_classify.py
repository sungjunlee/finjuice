"""Unit tests for merchant-kind classification used by `rules suggest`."""

from __future__ import annotations

from finjuice.pipeline.tagging.suggestion_scoring_classify import (
    GENERIC_LEDGER_AMBIGUOUS_REASON,
    MASKED_LABEL_AMBIGUOUS_REASON,
    PAYMENT_GATEWAY_AMBIGUOUS_REASON,
    classify_merchant_kind,
    is_auto_apply_eligible,
)


def _skip_gateway() -> dict[str, str | None]:
    return {
        "merchant_kind": "payment_gateway",
        "ambiguous_reason": PAYMENT_GATEWAY_AMBIGUOUS_REASON,
        "default_action": "skip_rule",
    }


def _skip_non_merchant(reason: str) -> dict[str, str | None]:
    return {
        "merchant_kind": "non_merchant",
        "ambiguous_reason": reason,
        "default_action": "skip_rule",
    }


def test_classify_easy_pay_brands_as_payment_gateway() -> None:
    """Known easy-pay and PG brand names default to skip_rule."""
    merchants = (
        "네이버페이",
        "카카오페이",
        "토스페이",
        "나이스페이먼츠",
        "Naver Pay",
        "KakaoPay",
        "카카오페이 환급",
        "NHNKCP",
    )

    for merchant in merchants:
        result = classify_merchant_kind(merchant)

        assert result == _skip_gateway(), merchant
        assert is_auto_apply_eligible(result) is False


def test_classify_masked_and_generic_ledger_labels_as_non_merchant() -> None:
    """Asterisk-filled and generic ledger phrases are excluded from create_rule."""
    masked = _skip_non_merchant(MASKED_LABEL_AMBIGUOUS_REASON)
    ledger = _skip_non_merchant(GENERIC_LEDGER_AMBIGUOUS_REASON)

    assert classify_merchant_kind("*****") == masked
    assert classify_merchant_kind("＊＊＊") == masked
    assert classify_merchant_kind("송금 내역") == ledger
    assert classify_merchant_kind("출금 내역") == ledger
    assert classify_merchant_kind("자동결제") == ledger
    assert is_auto_apply_eligible(classify_merchant_kind("*****")) is False
    assert is_auto_apply_eligible(classify_merchant_kind("출금 내역")) is False


def test_classify_keeps_ordinary_merchants_as_create_rule() -> None:
    """Ordinary store names remain eligible for rule creation."""
    expected = {
        "merchant_kind": "merchant",
        "ambiguous_reason": None,
        "default_action": "create_rule",
    }

    assert classify_merchant_kind("롯데마트") == expected
    assert classify_merchant_kind("KCPARK CAFE") == expected
    assert classify_merchant_kind("Netflix") == expected
    # Easy-pay brand names embedded in a real merchant label must NOT
    # trigger the payment-gateway skip (regression guard for the
    # prefix-boundary fix).
    assert classify_merchant_kind("카카오페이지") == expected
    assert classify_merchant_kind("네이버페이지") == expected
    assert classify_merchant_kind("네이버페이지 웹툰") == expected
    assert classify_merchant_kind("KAKAOPAYMENT") == expected
    assert is_auto_apply_eligible(expected) is True


def test_classify_easy_pay_brand_with_store_detail_is_skipped() -> None:
    """A bare easy-pay brand, or brand + store detail, is still skipped."""
    skipped = {
        "merchant_kind": "payment_gateway",
        "default_action": "skip_rule",
    }

    for merchant in (
        "네이버페이",
        "카카오페이",
        "네이버페이 파리바게뜨",
        "카카오페이 교통",
        "스마일페이 지마켓",
    ):
        result = classify_merchant_kind(merchant)
        assert result["merchant_kind"] == skipped["merchant_kind"], merchant
        assert result["default_action"] == skipped["default_action"], merchant
        assert is_auto_apply_eligible(result) is False
