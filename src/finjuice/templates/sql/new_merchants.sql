WITH bounds AS (
    SELECT MAX(CAST(date AS DATE)) AS max_date
    FROM transactions
    WHERE date IS NOT NULL
),
normalized_transactions AS (
    SELECT
        *,
        CAST(date AS DATE) AS txn_date
    FROM transactions
    WHERE date IS NOT NULL
)
SELECT
    merchant_raw,
    COUNT(*) AS transaction_count,
    abs(SUM(amount)) AS total_spend
FROM normalized_transactions
CROSS JOIN bounds
WHERE amount < 0
  AND is_transfer_bool = FALSE
  AND txn_date > max_date - {{days}} * INTERVAL '1' DAY
  AND txn_date <= max_date
  AND merchant_raw NOT IN (
      SELECT DISTINCT merchant_raw
      FROM normalized_transactions
      CROSS JOIN bounds
      WHERE txn_date <= max_date - {{days}} * INTERVAL '1' DAY
        AND merchant_raw IS NOT NULL
        AND is_transfer_bool = FALSE
  )
  AND merchant_raw IS NOT NULL
GROUP BY merchant_raw
ORDER BY total_spend DESC
