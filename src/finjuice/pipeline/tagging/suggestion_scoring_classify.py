"""Merchant-kind classification for `finjuice rules suggest`.

Owns conservative payment-gateway / easy-pay detection, masked and generic
ledger-label skips, and auto-apply eligibility derived from ``default_action``.
Merchant-context assembly stays in
:mod:`finjuice.pipeline.tagging.suggestion_scoring`, which re-exports these
names so existing callers can keep importing from that module.
"""

from __future__ import annotations

import re
from typing import Any

from finjuice.pipeline.tagging.suggestion_similarity import _normalize_text

PAYMENT_GATEWAY_AMBIGUOUS_REASON = "payment_gateway"
MASKED_LABEL_AMBIGUOUS_REASON = "masked_label"
GENERIC_LABEL_AMBIGUOUS_REASON = "generic_label"

_KNOWN_PAYMENT_GATEWAY_NORMALIZED = {
    "KGINICIS",
    "이니시스",
    "케이지이니시스",
    "NHNKCP",
    "KCP",
    "엔에이치엔케이씨피",
    "NHN케이씨피",
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
}

_PAYMENT_GATEWAY_PREFIXES = (
    "PAYPAL*",
    "PAYPAL *",
    "STRIPE*",
    "STRIPE *",
)

_GENERIC_LEDGER_LABEL_NORMALIZED = {
    "송금내역",
    "출금내역",
    "입금내역",
    "이체내역",
    "자동결제",
    "자동이체",
    "이체",
    "송금",
    "출금",
}

_CREATE_RULE_CLASSIFICATION: dict[str, str | None] = {
    "merchant_kind": "merchant",
    "ambiguous_reason": None,
    "default_action": "create_rule",
}


_CORPORATE_SUFFIXES_NORMALIZED = ("주식회사", "INC", "LTD", "LLC", "COMPANY")


def _normalize_payment_gateway_key(value: Any) -> str:
    """Normalize merchant text for conservative known-PG classification."""
    text = _normalize_text(value)
    if not text:
        return ""
    key = re.sub(r"[^0-9A-Z가-힣]+", "", text.upper())
    # PG processor rows often carry a corporate suffix ("나이스페이먼츠 주식회사").
    for suffix in _CORPORATE_SUFFIXES_NORMALIZED:
        if key.endswith(suffix) and len(key) > len(suffix):
            key = key[: -len(suffix)]
            break
    return key


def _is_masked_ledger_label(text: str) -> bool:
    """Return True when *text* is an asterisk-filled mask, not a merchant name."""
    stripped = text.strip()
    if "*" not in stripped:
        return False
    visible = re.sub(r"[*\s._-]+", "", stripped)
    return visible == ""


def _skip_rule_classification(kind: str, reason: str) -> dict[str, str | None]:
    """Return the skip_rule payload for a classified non-curatable merchant."""
    return {
        "merchant_kind": kind,
        "ambiguous_reason": reason,
        "default_action": "skip_rule",
    }


def classify_merchant_kind(merchant: Any) -> dict[str, str | None]:
    """Classify merchants that should not become broad create_rule candidates.

    The detector is intentionally conservative. It marks well-known processor
    and easy-pay brand names, processor-style prefixes, masked ledger labels,
    and generic transfer labels, but avoids broad substring matches so ordinary
    merchants with similar text remain eligible for normal curation.
    """
    text = _normalize_text(merchant) or ""
    if not text:
        return dict(_CREATE_RULE_CLASSIFICATION)
    if _is_masked_ledger_label(text):
        return _skip_rule_classification("masked_label", MASKED_LABEL_AMBIGUOUS_REASON)

    key = _normalize_payment_gateway_key(text)
    if key in _GENERIC_LEDGER_LABEL_NORMALIZED:
        return _skip_rule_classification("generic_label", GENERIC_LABEL_AMBIGUOUS_REASON)

    upper_text = text.upper()
    is_gateway = key in _KNOWN_PAYMENT_GATEWAY_NORMALIZED or any(
        upper_text.startswith(prefix) for prefix in _PAYMENT_GATEWAY_PREFIXES
    )
    if is_gateway:
        return _skip_rule_classification(
            "payment_gateway",
            PAYMENT_GATEWAY_AMBIGUOUS_REASON,
        )
    return dict(_CREATE_RULE_CLASSIFICATION)


def is_auto_apply_eligible(suggestion: dict[str, Any]) -> bool:
    """Return whether a suggestion is safe for headless rule auto-apply."""
    return suggestion.get("default_action") != "skip_rule"
