"""Shared constants for Banksalad overview block parsers."""

from __future__ import annotations

import re

from ..schemas import normalize_sheet_name

_OVERVIEW_SHEET_NORMALIZED = normalize_sheet_name("뱅샐현황")
_ASSET_ANCHOR = normalize_sheet_name("자산")
_LIABILITY_ANCHOR = normalize_sheet_name("부채")
_BALANCE_BLOCK_ID = "balance_status"
_BALANCE_BLOCK_TITLE = "자산/부채"
_CASHFLOW_BLOCK_ID = "cashflow_monthly"
_CASHFLOW_BLOCK_TITLE = "현금흐름현황"
_CUSTOMER_BLOCK_ID = "customer_info"
_INSURANCE_BLOCK_ID = "insurance_status"
_INVESTMENT_BLOCK_ID = "investment_status"
_LOAN_BLOCK_ID = "loan_status"
_CASHFLOW_ANCHORS = {
    normalize_sheet_name(value)
    for value in ("현금흐름현황", "현금흐름", "월별현금흐름", "수입지출현황")
}
_SECTION_NUMBER_PREFIX_RE = re.compile(r"^\d+[\.)．。]?")
_NUMBERED_SECTION_RE = re.compile(r"^\s*\d+[\.)．。]?\s*(.+?)\s*$")
_CATEGORY_HEADERS = {
    normalize_sheet_name(value)
    for value in ("분류", "카테고리", "구분", "종류", "자산분류", "부채분류")
}
_ITEM_HEADERS = {
    normalize_sheet_name(value)
    for value in ("항목", "상품명", "계좌명", "계좌", "자산명", "부채명", "내용", "이름")
}
_AMOUNT_HEADERS = {
    normalize_sheet_name(value)
    for value in ("금액", "잔액", "평가금액", "현재금액", "합계", "총액")
}
_CASHFLOW_CATEGORY_HEADERS = {
    normalize_sheet_name(value) for value in ("분류", "카테고리", "항목", "구분")
}
_SNAPSHOT_DATE_LABELS = {
    normalize_sheet_name(value)
    for value in ("기준일", "조회일", "현황기준일", "자산기준일", "내보내기일")
}
_ROW_BREAK_ANCHORS = _CASHFLOW_ANCHORS | {
    normalize_sheet_name(value)
    for value in (
        "고객정보",
        "재무현황",
        "보험현황",
        "투자현황",
        "대출현황",
        "자산추이",
        "부채추이",
        "소비현황",
    )
}
_SECTION_BLOCKS = {
    normalize_sheet_name("고객정보"): (_CUSTOMER_BLOCK_ID, "고객정보"),
    normalize_sheet_name("현금흐름현황"): (_CASHFLOW_BLOCK_ID, _CASHFLOW_BLOCK_TITLE),
    normalize_sheet_name("재무현황"): (_BALANCE_BLOCK_ID, _BALANCE_BLOCK_TITLE),
    normalize_sheet_name("보험현황"): (_INSURANCE_BLOCK_ID, "보험현황"),
    normalize_sheet_name("투자현황"): (_INVESTMENT_BLOCK_ID, "투자현황"),
    normalize_sheet_name("대출현황"): (_LOAN_BLOCK_ID, "대출현황"),
}
_SUMMARY_LABELS = {normalize_sheet_name(value) for value in ("합계", "총계", "총자산", "총부채")}
_STRUCTURED_TABLE_HEADERS = {
    "insurance": {
        "institution": {normalize_sheet_name("금융사")},
        "policy_name": {normalize_sheet_name("보험명")},
        "contract_status": {normalize_sheet_name("계약상태")},
        "paid_amount": {normalize_sheet_name("총납입금")},
        "contract_date": {normalize_sheet_name("계약일자")},
        "maturity_date": {normalize_sheet_name("만기일자")},
    },
    "investments": {
        "product_type": {normalize_sheet_name("투자상품종류")},
        "institution": {normalize_sheet_name("금융사")},
        "product_name": {normalize_sheet_name("상품명")},
        "principal_amount": {normalize_sheet_name("투자원금")},
        "valuation_amount": {normalize_sheet_name("평가금액")},
        "return_rate": {normalize_sheet_name("수익률")},
        "start_date": {normalize_sheet_name("가입일자")},
        "maturity_date": {normalize_sheet_name("만기일자")},
    },
    "loans": {
        "loan_type": {normalize_sheet_name("대출종류")},
        "institution": {normalize_sheet_name("금융사")},
        "product_name": {normalize_sheet_name("상품명")},
        "principal_amount": {normalize_sheet_name("대출원금")},
        "balance_amount": {normalize_sheet_name("대출잔액")},
        "interest_rate": {normalize_sheet_name("대출금리")},
        "start_date": {normalize_sheet_name("대출신규일")},
        "maturity_date": {normalize_sheet_name("대출만기일"), normalize_sheet_name("만기일자")},
    },
}
