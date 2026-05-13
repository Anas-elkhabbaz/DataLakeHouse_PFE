-- Gold : table de données pour le pipeline V6 Hybrid RCA (Path 1)
-- Contrat de données figé — ne pas modifier les noms de colonnes sans mettre
-- à jour cortex/01_train_enriched.sql et apps/inference/inference_app.py

SELECT
    i.key,
    i.created_at,
    i.split,

    -- Cibles de classification
    i.issuetype,
    i.resolution,

    -- Texte nettoyé
    i.summary       AS summary_clean,
    i.description   AS description_clean,
    COALESCE(c.all_comments, '') AS comments_concat,

    -- Représentation NOCO (No Comments, No Labels) — entrée de l'embedding de récupération
    -- TYPE retiré : c'est une cible de classification → label leakage si inclus
    LEFT(
        CONCAT(
            'TICKET: ', COALESCE(i.summary, ''), '\n',
            'PRI: ', COALESCE(i.priority, ''), '\n',
            'STATUS: ', COALESCE(i.status, ''), '\n',
            'DESC: ', LEFT(COALESCE(i.description, ''), 1500)
        ),
        2000
    ) AS text_noco,

    -- Représentation RICH (avec commentaires) pour le dual-embedding V6
    LEFT(
        CONCAT(
            'TICKET: ', COALESCE(i.summary, ''), '\n',
            'PRIORITY: ', COALESCE(i.priority, 'Unknown'), '\n',
            'STATUS: ', COALESCE(i.status, 'Unknown'), '\n',
            'N_COMMENTS: ', COALESCE(TO_CHAR(COALESCE(c.n_comments, 0)), '0'), '\n',
            'DESCRIPTION: ', LEFT(COALESCE(i.description, ''), 2000), '\n',
            'DISCUSSION: ', LEFT(COALESCE(c.all_comments, ''), 2500)
        ),
        6000
    ) AS text_rich,

    -- Métadonnées pour le boost de récupération (§9.4 Step 3)
    i.priority,
    i.status,
    i.reporter,
    i.assignee,

    -- Features changelog (contribution originale du PFE)
    COALESCE(cl.n_total_changes,      0) AS n_total_changes,
    COALESCE(cl.n_status_changes,     0) AS n_status_changes,
    COALESCE(cl.n_priority_changes,   0) AS n_priority_changes,
    COALESCE(cl.n_assignee_changes,   0) AS n_assignee_changes,
    COALESCE(cl.n_resolution_changes, 0) AS n_resolution_changes,
    COALESCE(cl.was_escalated,        0) AS was_escalated,
    COALESCE(cl.was_deescalated,      0) AS was_deescalated,
    COALESCE(cl.n_people_involved,    0) AS n_people_involved,
    cl.first_assignee,

    -- Features de liens
    COALESCE(il.n_links_total,  0) AS n_links_total,
    COALESCE(il.n_duplicates,   0) AS n_duplicates,
    COALESCE(il.n_blocks,       0) AS n_blocks,
    COALESCE(il.n_blocked_by,   0) AS n_blocked_by,
    COALESCE(il.n_relates,      0) AS n_relates,

    -- Features commentaires
    COALESCE(c.n_comments,   0) AS n_comments,
    COALESCE(c.n_commenters, 0) AS n_commenters,

    -- Métriques de timing et de longueur
    i.resolution_days,
    i.summary_length,
    i.description_length

FROM {{ ref('int_issues_cleaned') }} i
LEFT JOIN {{ ref('int_comments_aggregated') }}  c  USING (key)
LEFT JOIN {{ ref('int_changelog_features') }}   cl USING (key)
LEFT JOIN {{ ref('int_issuelinks_features') }}  il USING (key)

-- On exclut uniquement les tickets 2024+ (tagués 'excluded') — train/validation/test tous inclus
WHERE i.split IN ('train', 'validation', 'test')
