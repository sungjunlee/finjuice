"""Shared CSV fixtures for automation collector tests."""

from __future__ import annotations

from pathlib import Path

import polars as pl


def write_sample_transactions(data_dir: Path) -> None:
    """Create a minimal partition with untagged merchant pressure and one large expense."""
    partition_dir = data_dir / "transactions" / "2024" / "10"
    partition_dir.mkdir(parents=True, exist_ok=True)

    pl.DataFrame(
        {
            "row_hash": ["r1", "r2", "r3", "r4", "r5"],
            "date": ["2024-10-01", "2024-10-03", "2024-10-05", "2024-10-07", "2024-10-08"],
            "time": ["09:00", "09:15", "12:00", "20:10", "08:00"],
            "merchant_raw": ["스타벅스", "스타벅스", "넷플릭스", "항공사", "내계좌이체"],
            "memo_raw": ["아이스 아메리카노", "", "정기결제", "출장", ""],
            "amount": [-4500.0, -5200.0, -17000.0, -800000.0, -120000.0],
            "account": ["신한카드", "신한카드", "현대카드", "기업카드", "신한은행"],
            "major_raw": ["식비", "식비", "구독", "여행", "이체"],
            "minor_raw": ["카페", "카페", "동영상", "항공", "이체"],
            "category_final": ["", "", "구독", "", "이체"],
            "category_rule": ["", "", "구독", "", ""],
            "tags_final": ["[]", "[]", '["구독"]', "[]", "[]"],
            "is_transfer": [0, 0, 0, 0, 1],
        }
    ).write_csv(partition_dir / "transactions.csv")
