-- Gold : agrégats de liens entre tickets (Path 2 — tableau de bord)
-- Remplace la section 'issue_links' de l'ancien mart_analytics_deps (VARIANT)

SELECT
    key,
    n_links_total,
    n_duplicates,
    n_blocks,
    n_blocked_by,
    n_relates,
    n_duplicates + n_blocks + n_blocked_by AS n_outgoing_plus_incoming
FROM {{ ref('int_issuelinks_features') }}
WHERE n_links_total > 0
