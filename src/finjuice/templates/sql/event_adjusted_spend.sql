WITH event_tags AS (
    SELECT trim(tag) AS event_tag
    FROM UNNEST(str_split(COALESCE({{event_tags}}, ''), ',')) AS raw_tags(tag)
    WHERE trim(tag) <> ''
),
consumption_rows AS (
    SELECT
        ABS(amount) AS spend_amount,
        tags_list,
        EXISTS (
            SELECT 1
            FROM event_tags
            WHERE list_contains(tags_list, event_tag)
        ) AS is_event
    FROM transactions
    WHERE amount < 0
      AND type_norm = 'expense'
      AND is_transfer_bool = FALSE
      AND substr(CAST(date AS VARCHAR), 1, 7) = {{month}}
      AND NOT regexp_matches(
          lower(
              concat_ws(
                  ' ',
                  coalesce(CAST(category_final AS VARCHAR), ''),
                  coalesce(CAST(major_raw AS VARCHAR), ''),
                  coalesce(CAST(minor_raw AS VARCHAR), ''),
                  coalesce(array_to_string(tags_list, ' '), '')
              )
          ),
          '(카드대금|카드결제|결제대금|상환|이체|송금|투자|증권|주식|펀드|isa|irp|연금|저축|적금|예금|savings?|investment)'
      )
)
SELECT
    {{month}} AS month,
    COALESCE(
        (SELECT string_agg(event_tag, ', ' ORDER BY event_tag) FROM event_tags),
        ''
    ) AS event_tags,
    COUNT(*) AS transaction_count,
    COUNT(*) FILTER (WHERE is_event) AS event_transaction_count,
    CAST(COALESCE(SUM(spend_amount), 0) AS BIGINT) AS total_consumption_spend,
    CAST(COALESCE(SUM(spend_amount) FILTER (WHERE is_event), 0) AS BIGINT) AS event_spend,
    CAST(COALESCE(SUM(spend_amount) FILTER (WHERE NOT is_event), 0) AS BIGINT)
        AS adjusted_consumption_spend
FROM consumption_rows
