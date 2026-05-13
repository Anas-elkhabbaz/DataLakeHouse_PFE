-- Gold : charge de travail par assignataire (Path 2 — tableau de bord)
-- Remplace la section 'assignee' de l'ancien mart_analytics_deps (VARIANT)

SELECT
    assignee,
    COUNT(*)                                                         AS n_assigned,
    COUNT(CASE WHEN resolution = 'Fixed' THEN 1 END)                 AS n_fixed,
    ROUND(AVG(CASE WHEN resolved_at IS NOT NULL
                   THEN resolution_days END), 1)                      AS avg_resolution_days,
    MODE(issuetype)                                                   AS top_issuetype,
    COUNT(DISTINCT issuetype)                                         AS n_distinct_issuetypes
FROM {{ ref('int_issues_cleaned') }}
WHERE assignee IS NOT NULL
  AND assignee != 'Unassigned'
GROUP BY assignee
