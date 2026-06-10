WITH bounds AS (
    SELECT MAX(CAST(date AS DATE)) AS max_date
    FROM transactions
    WHERE date IS NOT NULL
),
normalized_transactions AS (
    SELECT
        CAST(date AS DATE) AS txn_date,
        category_final,
        amount,
        is_transfer_bool
    FROM transactions
    WHERE date IS NOT NULL
),
current_period AS (
    SELECT category_final, SUM(amount) AS total
    FROM normalized_transactions
    CROSS JOIN bounds
    WHERE amount < 0
      AND is_transfer_bool = FALSE
      AND txn_date > max_date - {{period_days}} * INTERVAL '1' DAY
      AND txn_date <= max_date
    GROUP BY category_final
),
prior_period AS (
    SELECT category_final, SUM(amount) AS total
    FROM normalized_transactions
    CROSS JOIN bounds
    WHERE amount < 0
      AND is_transfer_bool = FALSE
      AND txn_date > max_date - {{period_days}} * 2 * INTERVAL '1' DAY
      AND txn_date <= max_date - {{period_days}} * INTERVAL '1' DAY
    GROUP BY category_final
),
compared AS (
    SELECT
        COALESCE(c.category_final, p.category_final) AS category,
        abs(COALESCE(c.total, 0)) AS current_spend,
        abs(COALESCE(p.total, 0)) AS prior_spend,
        CASE
            WHEN c.total IS NULL AND p.total IS NOT NULL THEN 'gone'
            WHEN p.total IS NULL AND c.total IS NOT NULL THEN 'new'
            WHEN p.total IS NULL AND c.total IS NULL THEN NULL
            ELSE 'changed'
        END AS change_type,
        CASE
            WHEN p.total IS NULL OR c.total IS NULL THEN NULL
            ELSE ROUND((abs(c.total) - abs(p.total)) / NULLIF(abs(p.total), 0) * 100, 1)
        END AS change_pct
    FROM current_period c
    FULL OUTER JOIN prior_period p ON c.category_final = p.category_final
)
SELECT * FROM compared
WHERE ABS(change_pct) > {{threshold_pct}}
   OR change_type IN ('new', 'gone')
ORDER BY abs(current_spend - prior_spend) DESC
