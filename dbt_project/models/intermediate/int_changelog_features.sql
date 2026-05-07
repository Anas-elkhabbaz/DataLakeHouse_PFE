-- Intermédiaire : features dérivées du changelog par issue
-- Contribution originale du PFE : features changelog absentes du hackathon V6

WITH base AS (
    SELECT * FROM {{ ref('stg_changelog') }}
    -- Filtre redondant (déjà en staging) pour sécurité
    WHERE UPPER(field) IN (
        'STATUS', 'PRIORITY', 'ASSIGNEE', 'RESOLUTION',
        'FIX VERSION', 'FIX VERSION/S',
        'COMPONENT', 'COMPONENT/S', 'LABELS'
    )
),

-- Rang de priorité pour détecter l'escalade
priority_ranked AS (
    SELECT
        key,
        created,
        to_string AS priority_to,
        CASE UPPER(to_string)
            WHEN 'TRIVIAL'  THEN 1
            WHEN 'MINOR'    THEN 2
            WHEN 'MAJOR'    THEN 3
            WHEN 'CRITICAL' THEN 4
            WHEN 'BLOCKER'  THEN 5
            ELSE NULL
        END AS priority_rank,
        ROW_NUMBER() OVER (PARTITION BY key ORDER BY created) AS change_order
    FROM base
    WHERE UPPER(field) = 'PRIORITY'
),

-- Détection d'escalade : au moins un changement de priorité croissant
escalation_flags AS (
    SELECT
        p1.key,
        MAX(
            CASE WHEN p2.priority_rank > p1.priority_rank THEN 1 ELSE 0 END
        ) AS was_escalated
    FROM priority_ranked p1
    JOIN priority_ranked p2
        ON p1.key = p2.key
        AND p2.change_order = p1.change_order + 1
    GROUP BY p1.key
),

-- Premier assignataire (premier événement assignee, valeur toString)
first_assignee_events AS (
    SELECT
        key,
        to_string AS first_assignee,
        ROW_NUMBER() OVER (PARTITION BY key ORDER BY created) AS rk
    FROM base
    WHERE UPPER(field) = 'ASSIGNEE'
      AND to_string IS NOT NULL
),

aggregated AS (
    SELECT
        key,
        COUNT(*)                                                  AS n_total_changes,
        COUNT(CASE WHEN UPPER(field) = 'STATUS'     THEN 1 END)  AS n_status_changes,
        COUNT(CASE WHEN UPPER(field) = 'PRIORITY'   THEN 1 END)  AS n_priority_changes,
        COUNT(CASE WHEN UPPER(field) = 'ASSIGNEE'   THEN 1 END)  AS n_assignee_changes,
        COUNT(CASE WHEN UPPER(field) = 'RESOLUTION' THEN 1 END)  AS n_resolution_changes,
        COUNT(DISTINCT author)                                    AS n_people_involved
    FROM base
    GROUP BY key
)

SELECT
    a.key,
    a.n_total_changes,
    a.n_status_changes,
    a.n_priority_changes,
    a.n_assignee_changes,
    a.n_resolution_changes,
    a.n_people_involved,
    COALESCE(e.was_escalated, 0)    AS was_escalated,
    fa.first_assignee
FROM aggregated a
LEFT JOIN escalation_flags e    ON a.key = e.key
LEFT JOIN first_assignee_events fa ON a.key = fa.key AND fa.rk = 1
WHERE a.key IN (SELECT key FROM {{ ref('int_issues_cleaned') }})
