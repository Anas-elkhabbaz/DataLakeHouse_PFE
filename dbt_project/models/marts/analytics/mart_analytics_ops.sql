-- Gold : agrégats mensuels orientés opérations (Path 2 — tableau de bord)
-- Granularité : mois × issuetype

WITH base AS (
    SELECT
        i.key,
        DATE_TRUNC('month', i.created_at)  AS month,
        i.issuetype,
        i.resolution,
        i.priority,
        i.resolution_days,
        i.summary_length,
        i.description_length,
        COALESCE(c.n_comments, 0)          AS n_comments,
        CASE WHEN i.resolved_at IS NOT NULL THEN 1 ELSE 0 END AS is_resolved
    FROM {{ ref('int_issues_cleaned') }} i
    LEFT JOIN {{ ref('int_comments_aggregated') }} c USING (key)
),

aggregated AS (
    SELECT
        month,
        issuetype,

        -- Volumes
        COUNT(*)                                               AS total_issues,
        SUM(is_resolved)                                       AS total_resolved,

        -- Dynamique de résolution
        MEDIAN(CASE WHEN is_resolved = 1 THEN resolution_days END) AS median_resolution_days,
        AVG(CASE WHEN is_resolved = 1 THEN resolution_days END)    AS avg_resolution_days,

        -- Répartition par résolution
        ROUND(
            100.0 * COUNT(CASE WHEN resolution = 'Fixed'            THEN 1 END) / NULLIF(COUNT(*), 0), 2
        ) AS pct_fixed,
        ROUND(
            100.0 * COUNT(CASE WHEN resolution = 'Won''t Fix'        THEN 1 END) / NULLIF(COUNT(*), 0), 2
        ) AS pct_wontfix,
        ROUND(
            100.0 * COUNT(CASE WHEN resolution = 'Duplicate'        THEN 1 END) / NULLIF(COUNT(*), 0), 2
        ) AS pct_duplicate,
        ROUND(
            100.0 * COUNT(CASE WHEN resolution = 'Cannot Reproduce' THEN 1 END) / NULLIF(COUNT(*), 0), 2
        ) AS pct_cannot_reproduce,

        -- Métriques de richesse du ticket
        ROUND(AVG(summary_length), 1)     AS avg_summary_length,
        ROUND(AVG(description_length), 1) AS avg_description_length,
        ROUND(AVG(n_comments), 2)         AS avg_n_comments

    FROM base
    GROUP BY month, issuetype
)

SELECT *
FROM aggregated
ORDER BY month, issuetype
