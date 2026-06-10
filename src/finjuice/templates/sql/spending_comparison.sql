WITH bounds AS (
    SELECT MAX(CAST(date AS DATE)) AS max_date
    FROM transactions
    WHERE date IS NOT NULL
),
normalized_transactions AS (
    SELECT
        CAST(date AS DATE) AS txn_date,
        amount,
        is_transfer_bool
    FROM transactions
    WHERE date IS NOT NULL
),
current_period AS (
    SELECT
        COUNT(*) AS transaction_count,
        COALESCE(abs(SUM(amount)), 0) AS total_spend
    FROM normalized_transactions
    CROSS JOIN bounds
    WHERE amount < 0
      AND is_transfer_bool = FALSE
      AND txn_date > max_date - {{period_days}} * INTERVAL '1' DAY
      AND txn_date <= max_date
),
prior_period AS (
    SELECT
        COUNT(*) AS transaction_count,
        COALESCE(abs(SUM(amount)), 0) AS total_spend
    FROM normalized_transactions
    CROSS JOIN bounds
    WHERE amount < 0
      AND is_transfer_bool = FALSE
      AND txn_date > max_date - {{period_days}} * 2 * INTERVAL '1' DAY
      AND txn_date <= max_date - {{period_days}} * INTERVAL '1' DAY
)
SELECT
    c.transaction_count AS current_txn_count,
    c.total_spend AS current_spend,
    p.transaction_count AS prior_txn_count,
    p.total_spend AS prior_spend,
    CASE
        WHEN p.total_spend = 0 AND c.total_spend = 0 THEN 0.0
        WHEN p.total_spend = 0 THEN NULL
        ELSE ROUND((c.total_spend - p.total_spend) / p.total_spend * 100, 1)
    END AS change_pct
FROM current_period c, prior_period p
