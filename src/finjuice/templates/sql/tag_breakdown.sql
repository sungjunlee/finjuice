WITH filtered AS (
    SELECT amount, tags_list
    FROM transactions
    WHERE amount < 0
      AND is_transfer_bool = FALSE
      AND tags_list IS NOT NULL
      AND ({{since}} IS NULL OR substr(CAST(date AS VARCHAR), 1, 7) >= {{since}})
      AND ({{until}} IS NULL OR substr(CAST(date AS VARCHAR), 1, 7) <= {{until}})
)
SELECT
    tag,
    COUNT(*) AS transaction_count,
    abs(SUM(amount)) AS total_spend
FROM filtered, UNNEST(tags_list) AS t(tag)
GROUP BY tag
ORDER BY total_spend DESC
LIMIT {{top_n}}
