WITH candidates AS (
    SELECT
        merchant_raw,
        abs(amount) AS amount_krw,
        COUNT(*) AS occurrences,
        MIN(date) AS first_seen,
        MAX(date) AS last_seen,
        lower(
            COALESCE(CAST(merchant_raw AS VARCHAR), '') || ' ' ||
            string_agg(COALESCE(CAST(major_raw AS VARCHAR), ''), ' ') || ' ' ||
            string_agg(COALESCE(CAST(minor_raw AS VARCHAR), ''), ' ') || ' ' ||
            string_agg(COALESCE(CAST(category_final AS VARCHAR), ''), ' ') || ' ' ||
            string_agg(COALESCE(CAST(memo_raw AS VARCHAR), ''), ' ') || ' ' ||
            string_agg(COALESCE(CAST(tags_final AS VARCHAR), ''), ' ')
        ) AS intent_text
    FROM transactions
    WHERE amount < 0
      AND is_transfer_bool = FALSE
    GROUP BY merchant_raw, amount
    HAVING COUNT(*) >= {{min_occurrences}}
       AND abs(amount) >= {{min_amount}}
)
SELECT
    merchant_raw,
    amount_krw,
    occurrences,
    first_seen,
    last_seen,
    CASE
        WHEN regexp_matches(intent_text, '(적금|예금|저축|savings?|deposit|isa|연금|펀드)')
            THEN 'savings'
        WHEN regexp_matches(intent_text, '(대출|이자|상환|loan|interest|mortgage)')
            THEN 'loan_or_interest'
        WHEN regexp_matches(
            intent_text,
            '(구독|정기지출|통신|보험|렌탈|관리비|월세|subscription|netflix|spotify|disney|gym|membership|멤버십)'
        )
            THEN 'spending'
        ELSE 'unknown'
    END AS intent,
    CASE
        WHEN regexp_matches(intent_text, '(적금|예금|저축|savings?|deposit|isa|연금|펀드)')
            THEN 0.9
        WHEN regexp_matches(intent_text, '(대출|이자|상환|loan|interest|mortgage)')
            THEN 0.9
        WHEN regexp_matches(
            intent_text,
            '(구독|정기지출|통신|보험|렌탈|관리비|월세|subscription|netflix|spotify|disney|gym|membership|멤버십)'
        )
            THEN 0.75
        ELSE 0.0
    END AS intent_confidence
FROM candidates
ORDER BY occurrences DESC, amount_krw DESC
LIMIT {{top_n}}
