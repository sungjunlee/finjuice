"""Payment-gateway merchant-kind classification for `finjuice rules suggest`.

Owns conservative payment-gateway detection, the gateway constants it needs,
and auto-apply eligibility derived from ``default_action``. Merchant-context
assembly stays in :mod:`finjuice.pipeline.tagging.suggestion_scoring`, which
re-exports these names so existing callers can keep importing from that
module.
"""

from __future__ import annotations

import re
from typing import Any

from finjuice.pipeline.tagging.suggestion_similarity import _normalize_text

PAYMENT_GATEWAY_AMBIGUOUS_REASON = "payment_gateway"

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
}

_PAYMENT_GATEWAY_PREFIXES = (
    "PAYPAL*",
    "PAYPAL *",
    "STRIPE*",
    "STRIPE *",
)


def _normalize_payment_gateway_key(value: Any) -> str:
    """Normalize merchant text for conservative known-PG classification."""
    text = _normalize_text(value)
    if not text:
        return ""
    return re.sub(r"[^0-9A-Z가-힣]+", "", text.upper())


def classify_merchant_kind(merchant: Any) -> dict[str, str | None]:
    """Classify merchants that are known payment intermediaries.

    The detector is intentionally conservative. It marks well-known processor
    names and processor-style prefixes, but avoids broad substring matches so
    ordinary merchants with similar text remain eligible for normal curation.
    """
    text = _normalize_text(merchant) or ""
    key = _normalize_payment_gateway_key(text)
    upper_text = text.upper()
    is_gateway = key in _KNOWN_PAYMENT_GATEWAY_NORMALIZED or any(
        upper_text.startswith(prefix) for prefix in _PAYMENT_GATEWAY_PREFIXES
    )
    if not is_gateway:
        return {
            "merchant_kind": "merchant",
            "ambiguous_reason": None,
            "default_action": "create_rule",
        }
    return {
        "merchant_kind": "payment_gateway",
        "ambiguous_reason": PAYMENT_GATEWAY_AMBIGUOUS_REASON,
        "default_action": "skip_rule",
    }


def is_auto_apply_eligible(suggestion: dict[str, Any]) -> bool:
    """Return whether a suggestion is safe for headless rule auto-apply."""
    return suggestion.get("default_action") != "skip_rule"
