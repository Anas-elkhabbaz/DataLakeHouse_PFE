-- Gold : agrégats personnes + liens entre tickets (Path 2 — tableau de bord)
-- Deux sections : par assignataire et par issue (liens)

-- Section 1 : Charge par assignataire
WITH assignee_agg AS (
    SELECT
        assignee,
        COUNT(*)                                                        AS n_issues_assigned,
        COUNT(CASE WHEN resolution = 'Fixed' THEN 1 END)               AS n_issues_resolved_as_fixed,
        ROUND(AVG(CASE WHEN resolved_at IS NOT NULL
                       THEN resolution_days END), 1)                    AS avg_resolution_days,
        -- Type d'issue dominant (mode)
        MODE(issuetype)                                                 AS top_issuetype,
        COUNT(DISTINCT issuetype)                                       AS n_distinct_issuetypes
    FROM {{ ref('int_issues_cleaned') }}
    GROUP BY assignee
),

-- Section 2 : Agrégat des liens par issue
link_agg AS (
    SELECT
        key,
        n_links_total,
        n_duplicates,
        n_blocks,
        n_blocked_by,
        n_relates,
        -- Résumé des types de liens vus
        ARRAY_CONSTRUCT_COMPACT(
            IFF(n_duplicates   > 0, 'Duplicate',   NULL),
            IFF(n_blocks       > 0, 'Blocks',      NULL),
            IFF(n_blocked_by   > 0, 'Blocked By',  NULL),
            IFF(n_relates      > 0, 'Relates',     NULL)
        ) AS link_types_seen,
        n_duplicates + n_blocks + n_blocked_by AS n_outgoing_plus_incoming
    FROM {{ ref('int_issuelinks_features') }}
)

-- Exposer les deux sections dans des vues séparées serait idéal,
-- mais on les combine ici avec un flag pour simplifier l'API dbt.
-- Le tableau de bord interroge chaque section par filtre sur section_type.

SELECT
    'assignee' AS section_type,
    assignee   AS entity_key,
    TO_VARIANT(OBJECT_CONSTRUCT(
        'n_issues_assigned',         n_issues_assigned,
        'n_issues_resolved_as_fixed', n_issues_resolved_as_fixed,
        'avg_resolution_days',       avg_resolution_days,
        'top_issuetype',             top_issuetype,
        'n_distinct_issuetypes',     n_distinct_issuetypes
    )) AS metrics
FROM assignee_agg

UNION ALL

SELECT
    'issue_links' AS section_type,
    key           AS entity_key,
    TO_VARIANT(OBJECT_CONSTRUCT(
        'n_links_total',    n_links_total,
        'n_duplicates',     n_duplicates,
        'n_blocks',         n_blocks,
        'n_blocked_by',     n_blocked_by,
        'n_relates',        n_relates,
        'link_types_seen',  link_types_seen
    )) AS metrics
FROM link_agg
