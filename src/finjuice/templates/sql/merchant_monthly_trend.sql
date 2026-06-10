WITH max_bounds AS (
    SELECT
        strftime(date_trunc('month', max(CAST(date AS DATE))), '%Y-%m') AS data_max_month
    FROM transactions
    WHERE amount < 0
      AND is_transfer_bool = FALSE
),
bounds AS (
    SELECT
        COALESCE({{until}}, data_max_month) AS until_month,
        COALESCE(
            {{since}},
            strftime(
                date_trunc(
                    'month',
                    CAST((COALESCE({{until}}, data_max_month) || '-01') AS DATE)
                ) - INTERVAL 11 MONTH,
                '%Y-%m'
            )
        ) AS since_month
    FROM max_bounds
)
SELECT
    substr(CAST(t.date AS VARCHAR), 1, 7) AS month,
    COUNT(*) AS transaction_count,
    abs(SUM(t.amount)) AS total_spend,
    round(abs(AVG(t.amount)), 0) AS avg_spend
FROM transactions AS t
CROSS JOIN bounds AS b
WHERE t.amount < 0
  AND t.is_transfer_bool = FALSE
  AND t.merchant_raw ILIKE '%' || {{merchant}} || '%'
  AND substr(CAST(t.date AS VARCHAR), 1, 7) >= b.since_month
  AND substr(CAST(t.date AS VARCHAR), 1, 7) <= b.until_month
GROUP BY month
ORDER BY month DESC
LIMIT {{top_n}}
