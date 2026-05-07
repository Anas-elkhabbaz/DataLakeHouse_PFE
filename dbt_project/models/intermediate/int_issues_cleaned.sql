-- Intermédiaire : nettoyage NLP, consolidation des labels, split temporel
-- Résultat attendu : ~45 000 lignes (49 833 - issues ouvertes sans résolution)

WITH base AS (
    SELECT * FROM {{ ref('stg_issues') }}
),

-- Jointure avec les seeds de mapping pour consolider les labels
with_labels AS (
    SELECT
        b.key,
        b.issue_id,
        b.created_at,
        b.resolved_at,
        b.priority,
        b.status,
        b.project,
        b.assignee,
        b.reporter,
        b.creator,
        b.votes,
        b.watches,
        b.issuetype_raw,
        b.resolution_raw,
        -- Consolidation issuetype : valeurs inconnues → Other
        COALESCE(im.issuetype, 'Other')  AS issuetype,
        -- Consolidation resolution : NULL si non trouvé dans le mapping
        rm.resolution                    AS resolution,
        -- Nettoyage NLP summary (6 étapes via macro)
        {{ clean_jira_text('b.summary') }}     AS summary,
        -- Nettoyage NLP description
        {{ clean_jira_text('b.description') }} AS description,
        -- Durée de résolution en jours, plafonnée à 5000
        LEAST(
            COALESCE(DATEDIFF('day', b.created_at, b.resolved_at), 0),
            5000
        ) AS resolution_days,
        LENGTH(COALESCE(b.summary, ''))     AS summary_length,
        LENGTH(COALESCE(b.description, '')) AS description_length,
        -- Split temporel §5.3
        CASE
            WHEN b.created_at < '2023-01-01' THEN 'train'
            WHEN b.created_at >= '2023-01-01' AND b.created_at < '2024-01-01' THEN 'validation'
            ELSE 'excluded'
        END AS split

    FROM base b
    LEFT JOIN {{ ref('issuetype_mapping') }} im ON b.issuetype_raw = im.issuetype_raw
    LEFT JOIN {{ ref('resolution_mapping') }} rm ON b.resolution_raw = rm.resolution_raw
)

SELECT *
FROM with_labels
-- Supprimer les issues sans résolution valide (ouvertes, Auto Closed, Workaround, etc.)
WHERE resolution IS NOT NULL
