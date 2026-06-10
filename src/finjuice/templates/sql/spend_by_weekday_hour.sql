WITH filtered AS (
    SELECT
        CAST(date AS DATE) AS txn_date,
        CAST(split_part(CAST(time AS VARCHAR), ':', 1) AS INTEGER) AS txn_hour,
        amount
    FROM transactions
    WHERE amount < 0
      AND is_transfer_bool = FALSE
      AND ({{since}} IS NULL OR substr(CAST(date AS VARCHAR), 1, 7) >= {{since}})
      AND ({{until}} IS NULL OR substr(CAST(date AS VARCHAR), 1, 7) <= {{until}})
),
enriched AS (
    SELECT
        (CAST(strftime(txn_date, '%w') AS INTEGER) + 6) % 7 AS weekday_idx,
        txn_hour AS hour,
        amount
    FROM filtered
)
SELECT
    weekday_idx,
    CASE weekday_idx
        WHEN 0 THEN 'Mon'
        WHEN 1 THEN 'Tue'
        WHEN 2 THEN 'Wed'
        WHEN 3 THEN 'Thu'
        WHEN 4 THEN 'Fri'
        WHEN 5 THEN 'Sat'
        WHEN 6 THEN 'Sun'
    END AS weekday_name,
    hour,
    COUNT(*) AS transaction_count,
    abs(SUM(amount)) AS total_spend,
    round(abs(AVG(amount)), 0) AS avg_spend
FROM enriched
GROUP BY weekday_idx, weekday_name, hour
ORDER BY weekday_idx ASC, hour ASC
