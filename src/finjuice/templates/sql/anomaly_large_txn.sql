SELECT
    date,
    merchant_raw,
    account,
    category_final,
    abs(amount) AS amount_krw
FROM transactions
WHERE amount < 0
  AND is_transfer_bool = FALSE
  AND abs(amount) >= {{threshold}}
  AND ({{since}} IS NULL OR substr(CAST(date AS VARCHAR), 1, 7) >= {{since}})
  AND ({{until}} IS NULL OR substr(CAST(date AS VARCHAR), 1, 7) <= {{until}})
ORDER BY amount_krw DESC
LIMIT {{top_n}}
