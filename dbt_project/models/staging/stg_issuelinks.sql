-- Staging : liens entre issues filtrés sur les issues SPARK
-- Résultat attendu : quelques milliers de lignes

WITH spark_keys AS (
    SELECT key FROM {{ ref('stg_issues') }}
),

source AS (
    SELECT * FROM {{ source('raw', 'issuelinks') }}
    WHERE key IN (SELECT key FROM spark_keys)
)

SELECT
    key,
    type_name,
    inwardissue_key,
    outwardissue_key

FROM source
