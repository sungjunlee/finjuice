WITH consumption_rows AS (
    SELECT
        COALESCE(category_final, minor_raw, major_raw, '미분류') AS category,
        ABS(amount) AS spend_amount
    FROM transactions
    WHERE amount < 0
      AND type_norm = 'expense'
      AND is_transfer_bool = FALSE
      AND substr(CAST(date AS VARCHAR), 1, 7) = {{month}}
      AND NOT regexp_matches(
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
      )
)
SELECT
    category,
    COUNT(*) AS transaction_count,
    CAST(SUM(spend_amount) AS BIGINT) AS consumption_spend
FROM consumption_rows
GROUP BY category
ORDER BY consumption_spend DESC, category ASC
LIMIT {{top_n}}
