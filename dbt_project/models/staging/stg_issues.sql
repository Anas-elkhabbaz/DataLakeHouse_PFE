-- Staging : issues JIRA filtrées sur le projet SPARK
-- 1:1 avec RAW.ISSUES — seuls renommage, cast et filtre projet ici.
-- Résultat attendu : ~49 833 lignes

WITH source AS (
    SELECT * FROM {{ source('raw', 'issues') }}
)

SELECT
    id                                              AS issue_id,
    key,
    summary,
    description,
    TRY_TO_TIMESTAMP_TZ(created)                   AS created_at,
    TRY_TO_TIMESTAMP_TZ(resolutiondate)             AS resolved_at,
    issuetype_name                                  AS issuetype_raw,
    resolution_name                                 AS resolution_raw,
    priority_name                                   AS priority,
    status_name                                     AS status,
    project_key                                     AS project,
    COALESCE(NULLIF(TRIM(assignee), ''), 'Unassigned') AS assignee,
    reporter,
    creator,
    TRY_TO_NUMBER(votes_votes)                      AS votes,
    TRY_TO_NUMBER(watches_watchcount)               AS watches

FROM source
WHERE project_key = 'SPARK'
QUALIFY ROW_NUMBER() OVER (PARTITION BY key ORDER BY id) = 1
