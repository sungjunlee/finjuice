WITH base_rows AS (
{{base_rows_sql}}
),
bucketed_rows AS (
    SELECT
        row_key,
        {{bucket_case_sql}} AS column_bucket,
        metric_value
    FROM base_rows
)
SELECT
    row_key AS {{row_alias}}{{pivot_columns_sql}}
FROM bucketed_rows
GROUP BY row_key
ORDER BY row_key ASC
