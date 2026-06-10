SELECT
    substr(CAST(date AS VARCHAR), 1, 7) AS month,
    COUNT(*) AS transaction_count,
    abs(SUM(amount)) AS total_spend
FROM transactions
WHERE amount < 0
  AND is_transfer_bool = FALSE
  AND ({{since}} IS NULL OR substr(CAST(date AS VARCHAR), 1, 7) >= {{since}})
  AND ({{until}} IS NULL OR substr(CAST(date AS VARCHAR), 1, 7) <= {{until}})
GROUP BY month
ORDER BY month DESC
