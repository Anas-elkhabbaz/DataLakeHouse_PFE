-- Staging : changelog filtré sur les issues SPARK et les champs utiles au pipeline V6
-- Champs retenus : ceux consommés par int_changelog_features uniquement
-- Résultat attendu : plusieurs millions de lignes

WITH spark_keys AS (
    SELECT key FROM {{ ref('stg_issues') }}
),

source AS (
    SELECT * FROM {{ source('raw', 'changelog') }}
    WHERE key IN (SELECT key FROM spark_keys)
      AND UPPER(field) IN ('STATUS', 'PRIORITY', 'RESOLUTION', 'ASSIGNEE', 'ISSUETYPE')
)

SELECT
    key,
    author,
    TRY_TO_TIMESTAMP_TZ(created) AS created,
    field,
    fromstring AS from_string,
    tostring   AS to_string

FROM source
