WITH selected_months AS (
    SELECT 'baseline' AS period_name, month_value AS month
    FROM UNNEST(from_json({{baseline_months}}, '["VARCHAR"]')) AS month_list(month_value)

    UNION ALL

    SELECT 'current' AS period_name, month_value AS month
    FROM UNNEST(from_json({{current_months}}, '["VARCHAR"]')) AS month_list(month_value)
),
normalized_transactions AS (
    SELECT
        strftime(CAST(date AS DATE), '%Y-%m') AS month,
        COALESCE(NULLIF(TRIM(CAST({{group_by_expr}} AS VARCHAR)), ''), '(unknown)') AS group_key,
        abs(amount) AS metric_amount
    FROM transactions
    WHERE {{type_norm_filter}}
),
window_group_totals AS (
    SELECT
        s.period_name,
        n.group_key,
        SUM(n.metric_amount) AS total_amount
    FROM normalized_transactions AS n
    JOIN selected_months AS s
      ON n.month = s.month
    GROUP BY s.period_name, n.group_key
),
window_month_counts AS (
    SELECT
        s.period_name,
        COUNT(DISTINCT n.month) AS month_count
    FROM normalized_transactions AS n
    JOIN selected_months AS s
      ON n.month = s.month
    GROUP BY s.period_name
),
window_averages AS (
    SELECT
        g.period_name,
        g.group_key,
        g.total_amount / NULLIF(c.month_count, 0) AS monthly_avg
    FROM window_group_totals AS g
    JOIN window_month_counts AS c
      ON g.period_name = c.period_name
),
baseline AS (
    SELECT
        group_key,
        monthly_avg AS baseline_monthly_avg
    FROM window_averages
    WHERE period_name = 'baseline'
),
current AS (
    SELECT
        group_key,
        monthly_avg AS current_monthly_avg
    FROM window_averages
    WHERE period_name = 'current'
)
SELECT
    COALESCE(b.group_key, c.group_key) AS group_key,
    ROUND(COALESCE(b.baseline_monthly_avg, 0), 1) AS baseline_monthly_avg,
    ROUND(COALESCE(c.current_monthly_avg, 0), 1) AS current_monthly_avg,
    ROUND(COALESCE(c.current_monthly_avg, 0) - COALESCE(b.baseline_monthly_avg, 0), 1) AS diff,
    CASE
        WHEN COALESCE(b.baseline_monthly_avg, 0) = 0 THEN NULL
        ELSE ROUND(
            (COALESCE(c.current_monthly_avg, 0) - COALESCE(b.baseline_monthly_avg, 0))
            / NULLIF(COALESCE(b.baseline_monthly_avg, 0), 0)
            * 100,
            1
        )
    END AS pct_change
FROM baseline AS b
FULL OUTER JOIN current AS c
  ON b.group_key = c.group_key
ORDER BY ABS(diff) DESC NULLS LAST, group_key
