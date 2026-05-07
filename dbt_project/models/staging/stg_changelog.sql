-- Staging : changelog filtré sur les issues SPARK et les champs utiles
-- Champs utiles (insensible à la casse) : Status, Priority, Assignee, Resolution,
-- Fix Version, Fix Version/s, Component, Component/s, Labels
-- Résultat attendu : plusieurs millions de lignes

WITH spark_keys AS (
    SELECT key FROM {{ ref('stg_issues') }}
),

source AS (
    SELECT * FROM {{ source('raw', 'changelog') }}
    WHERE key IN (SELECT key FROM spark_keys)
      AND UPPER(field) IN (
          'STATUS', 'PRIORITY', 'ASSIGNEE', 'RESOLUTION',
          'FIX VERSION', 'FIX VERSION/S',
          'COMPONENT', 'COMPONENT/S', 'LABELS'
      )
)

SELECT
    key,
    author,
    TRY_TO_TIMESTAMP_TZ(created) AS created,
    field,
    fromstring AS from_string,
    tostring   AS to_string

FROM source
