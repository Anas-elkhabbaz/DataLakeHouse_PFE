-- Staging : commentaires filtrés sur les issues SPARK
-- Résultat attendu : ~500K–1M lignes

WITH spark_keys AS (
    SELECT key FROM {{ ref('stg_issues') }}
),

source AS (
    SELECT * FROM {{ source('raw', 'comments') }}
    WHERE key IN (SELECT key FROM spark_keys)
)

SELECT
    key,
    comment_id,
    comment_author,
    comment_body,
    TRY_TO_TIMESTAMP_TZ(comment_created) AS comment_created,
    TRY_TO_TIMESTAMP_TZ(comment_updated) AS comment_updated

FROM source
