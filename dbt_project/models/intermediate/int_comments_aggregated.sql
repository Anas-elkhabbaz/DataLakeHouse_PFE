-- Intermédiaire : agrégation des commentaires par issue
-- Nettoyage NLP du corps du commentaire, concaténation chronologique, métriques

WITH cleaned AS (
    SELECT
        key,
        comment_author,
        comment_created,
        {{ clean_jira_text('comment_body') }} AS comment_body_clean
    FROM {{ ref('stg_comments') }}
),

-- Supprimer les commentaires vides ou trop courts après nettoyage
filtered AS (
    SELECT *
    FROM cleaned
    WHERE LENGTH(COALESCE(comment_body_clean, '')) >= 10
),

aggregated AS (
    SELECT
        key,
        -- Concaténation chronologique, séparateur ' | ', tronquée à 3000 chars
        -- On conserve le début (énoncé du problème), pas la fin (bruit tardif)
        LEFT(
            LISTAGG(comment_body_clean, ' | ')
                WITHIN GROUP (ORDER BY comment_created),
            3000
        )                                   AS all_comments,
        COUNT(*)                            AS n_comments,
        COUNT(DISTINCT comment_author)      AS n_commenters,
        MIN(comment_created)                AS first_comment_at,
        MAX(comment_created)                AS last_comment_at
    FROM filtered
    GROUP BY key
)

SELECT
    a.key,
    a.all_comments,
    a.n_comments,
    a.n_commenters,
    a.first_comment_at,
    a.last_comment_at
FROM aggregated a
-- Conserver uniquement les issues présentes dans int_issues_cleaned
WHERE a.key IN (SELECT key FROM {{ ref('int_issues_cleaned') }})
