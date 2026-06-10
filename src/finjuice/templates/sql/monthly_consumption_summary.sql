WITH candidate_rows AS (
    SELECT
        substr(CAST(date AS VARCHAR), 1, 7) AS month,
        ABS(amount) AS spend_amount,
        regexp_matches(
            lower(
                concat_ws(
                    ' ',
                    coalesce(CAST(category_final AS VARCHAR), ''),
                    coalesce(CAST(major_raw AS VARCHAR), ''),
                    coalesce(CAST(minor_raw AS VARCHAR), ''),
                    coalesce(array_to_string(tags_list, ' '), '')
                )
            ),
            '(카드대금|카드결제|결제대금|상환|이체|송금|투자|증권|주식|펀드|isa|irp|연금|저축|적금|예금|savings?|investment)'
        ) AS is_non_consumption
    FROM transactions
    WHERE amount < 0
      AND type_norm = 'expense'
      AND is_transfer_bool = FALSE
      AND ({{since}} IS NULL OR substr(CAST(date AS VARCHAR), 1, 7) >= {{since}})
      AND ({{until}} IS NULL OR substr(CAST(date AS VARCHAR), 1, 7) <= {{until}})
)
SELECT
    month,
    COUNT(*) FILTER (WHERE NOT is_non_consumption) AS transaction_count,
    CAST(COALESCE(SUM(spend_amount) FILTER (WHERE NOT is_non_consumption), 0) AS BIGINT)
        AS consumption_spend,
    CAST(COALESCE(SUM(spend_amount) FILTER (WHERE is_non_consumption), 0) AS BIGINT)
        AS excluded_non_consumption_spend
FROM candidate_rows
GROUP BY month
ORDER BY month DESC
