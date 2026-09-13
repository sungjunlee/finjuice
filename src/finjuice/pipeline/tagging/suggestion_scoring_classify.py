"""Payment-gateway merchant-kind classification for `finjuice rules suggest`.

Owns conservative payment-gateway detection, easy-pay brand prefixes, masked
and generic ledger labels, the constants they need, and auto-apply eligibility
derived from ``default_action``. Merchant-context assembly stays in
:mod:`finjuice.pipeline.tagging.suggestion_scoring`, which re-exports these
names so existing callers can keep importing from that module.
"""

from __future__ import annotations

import re
from typing import Any

from finjuice.pipeline.tagging.suggestion_similarity import _normalize_text

PAYMENT_GATEWAY_AMBIGUOUS_REASON = "payment_gateway"
MASKED_LABEL_AMBIGUOUS_REASON = "masked_label"
GENERIC_LEDGER_AMBIGUOUS_REASON = "generic_ledger"

_KNOWN_PAYMENT_GATEWAY_NORMALIZED = {
    "KGINICIS",
    "이니시스",
    "케이지이니시스",
    "NHNKCP",
    "KCP",
    "엔에이치엔케이씨피",
    "토스페이먼츠",
    "TOSSPAYMENTS",
    "나이스페이먼츠",
    "NICEPAYMENTS",
    "KICC",
    "한국정보통신",
    "ALIPAY",
    "ALIPAYCONNECT",
    "ANOMALY",
    "네이버페이",
    "NAVERPAY",
    "카카오페이",
    "KAKAOPAY",
    "토스페이",
    "TOSSPAY",
    "페이코",
    "PAYCO",
    "삼성페이",
    "SAMSUNGPAY",
    "스마일페이",
    "SMILEPAY",
}

_EASY_PAY_NORMALIZED_PREFIXES = (
    "네이버페이 ",
    "NAVERPAY ",
    "카카오페이 ",
    "KAKAOPAY ",
    "토스페이 ",
    "TOSSPAY ",
    "삼성페이 ",
    "SAMSUNGPAY ",
    "스마일페이 ",
    "SMILEPAY ",
    "나이스페이 ",
    "NICEPAY ",
)

_PAYMENT_GATEWAY_PREFIXES = (
    "PAYPAL*",
    "PAYPAL *",
    "STRIPE*",
    "STRIPE *",
)

_GENERIC_LEDGER_NORMALIZED = {
    "송금내역",
    "출금내역",
    "자동결제",
}

_SKIP_RULE_CLASSIFICATION: dict[str, str | None] = {
    "merchant_kind": "payment_gateway",
    "ambiguous_reason": PAYMENT_GATEWAY_AMBIGUOUS_REASON,
    "default_action": "skip_rule",
}

_CREATE_RULE_CLASSIFICATION: dict[str, str | None] = {
    "merchant_kind": "merchant",
    "ambiguous_reason": None,
    "default_action": "create_rule",
}


def _normalize_payment_gateway_key(value: Any) -> str:
    """Normalize merchant text for conservative known-PG classification."""
    text = _normalize_text(value)
    if not text:
        return ""
    return re.sub(r"[^0-9A-Z가-힣]+", "", text.upper())


def _easy_pay_prefix_match(text: str, key: str) -> bool:
    """Return whether *text* is an easy-pay brand followed by store detail.

    ``카카오페이지``/``네이버페이지`` are ordinary merchants, so a bare prefix
    match is not enough: the brand must be the whole label or introduce a
    store name after the separator (e.g. ``네이버페이 파리바게뜨``).
    """
    for prefix in _EASY_PAY_NORMALIZED_PREFIXES:
        bare = prefix.rstrip()
        if key == bare:
            return True
        if text.startswith(prefix) and len(text) > len(prefix):
            return True
    return False


def _is_masked_merchant_label(text: str) -> bool:
    """Return whether *text* is an asterisk-filled masking label."""
    stripped = text.strip()
    if not stripped:
        return False
    compact = re.sub(r"[\s*＊]", "", stripped)
    return compact == "" and bool(re.search(r"[*＊]", stripped))


def _is_generic_ledger_label(key: str) -> bool:
    """Return whether the normalized key is a non-merchant ledger phrase."""
    return key in _GENERIC_LEDGER_NORMALIZED


def _non_merchant_classification(text: str, key: str) -> dict[str, str | None] | None:
    """Return skip_rule classification for masked or generic ledger labels."""
    if _is_masked_merchant_label(text):
        return {
            "merchant_kind": "non_merchant",
            "ambiguous_reason": MASKED_LABEL_AMBIGUOUS_REASON,
            "default_action": "skip_rule",
        }
    if _is_generic_ledger_label(key):
        return {
            "merchant_kind": "non_merchant",
            "ambiguous_reason": GENERIC_LEDGER_AMBIGUOUS_REASON,
            "default_action": "skip_rule",
        }
    return None


def _is_payment_gateway(text: str, key: str) -> bool:
    """Return whether *text* is a known processor or easy-pay brand."""
    upper_text = text.upper()
    return (
        key in _KNOWN_PAYMENT_GATEWAY_NORMALIZED
        or _easy_pay_prefix_match(text, key)
        or any(upper_text.startswith(prefix) for prefix in _PAYMENT_GATEWAY_PREFIXES)
    )


def classify_merchant_kind(merchant: Any) -> dict[str, str | None]:
    """Classify merchants that are known payment intermediaries or non-merchants.

    The detector is intentionally conservative. It marks well-known processor
    names, easy-pay brands, processor-style prefixes, masked labels, and generic
    ledger phrases, but avoids broad substring matches so ordinary merchants with
    similar text remain eligible for normal curation.
    """
    text = _normalize_text(merchant) or ""
    key = _normalize_payment_gateway_key(text)
    non_merchant = _non_merchant_classification(text, key)
    if non_merchant is not None:
        return non_merchant
    if not _is_payment_gateway(text, key):
        return dict(_CREATE_RULE_CLASSIFICATION)
    return dict(_SKIP_RULE_CLASSIFICATION)


def is_auto_apply_eligible(suggestion: dict[str, Any]) -> bool:
    """Return whether a suggestion is safe for headless rule auto-apply."""
    return suggestion.get("default_action") != "skip_rule"
