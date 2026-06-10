SELECT
    account,
    COUNT(*) AS transaction_count,
    abs(SUM(amount)) AS total_spend,
    round(abs(AVG(amount)), 0) AS avg_spend
FROM transactions
WHERE amount < 0
  AND is_transfer_bool = FALSE
  AND ({{since}} IS NULL OR substr(CAST(date AS VARCHAR), 1, 7) >= {{since}})
  AND ({{until}} IS NULL OR substr(CAST(date AS VARCHAR), 1, 7) <= {{until}})
GROUP BY account
ORDER BY total_spend DESC
LIMIT {{top_n}}
