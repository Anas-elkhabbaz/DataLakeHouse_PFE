-- =============================================================================
-- V6 Hybrid RCA — Étape 1 : Génération des représentations enrichies (train)
--
-- Pour chaque ticket d'entraînement :
--   1. Construit le texte d'entrée pour le résumé RCA (sans labels — §9.3)
--   2. Appelle CORTEX.COMPLETE(mistral-large2) pour générer le résumé RCA structuré
--   3. Construit text_rich (TICKET + RCA + COMMENTS)
--
-- Durée estimée : ~20–40 min sur MEDIUM warehouse (~41 400 appels LLM)
-- Coût indicatif : ~$15–25 (mistral-large2, ~500 tokens/ticket)
-- =============================================================================

USE DATABASE PFE_SPARK;
USE SCHEMA CORTEX;
USE WAREHOUSE PFE_WH;  -- Passer en MEDIUM avant d'exécuter

-- Passer le warehouse en MEDIUM pour les appels Cortex
ALTER WAREHOUSE PFE_WH SET WAREHOUSE_SIZE = 'MEDIUM';

CREATE OR REPLACE TABLE CORTEX.TRAIN_ENRICHED AS

WITH base AS (
    SELECT
        key,
        issuetype,
        resolution,
        summary_clean,
        description_clean,
        comments_concat,
        priority,
        status,
        reporter,
        assignee,
        n_comments,
        n_commenters,
        text_noco,
        -- Texte d'entrée pour la génération RCA (§9.3) :
        -- NE PAS inclure issuetype ni resolution — pas de fuite de label
        LEFT(
            CONCAT(
                'Summary: ', COALESCE(summary_clean, ''), '\n',
                'Priority: ', COALESCE(priority, ''), '\n',
                'Status: ', COALESCE(status, ''), '\n',
                'Description: ', LEFT(COALESCE(description_clean, ''), 1500), '\n',
                'Comments: ', LEFT(COALESCE(comments_concat, ''), 1000)
            ),
            3500
        ) AS input_for_rca
    FROM PFE_SPARK.MARTS_ML.MART_ML
    WHERE split = 'train'
),

-- Génération du résumé RCA structuré (6 champs, sans labels)
with_rca AS (
    SELECT
        key,
        issuetype,
        resolution,
        summary_clean,
        description_clean,
        comments_concat,
        priority,
        status,
        reporter,
        assignee,
        n_comments,
        n_commenters,
        text_noco,
        input_for_rca,
        SNOWFLAKE.CORTEX.COMPLETE(
            'mistral-large2',
            CONCAT(
                'You are a software issue analyst. Given this Apache Spark ticket, produce a structured summary.\n',
                'Do NOT mention the issue type or resolution. Focus on observable facts.\n',
                'Format:\n',
                'CONTEXT: [1 sentence: which Spark component/feature is involved]\n',
                'SYMPTOMS: [1 sentence: what was reported, errors seen]\n',
                'TECHNICAL_DETAIL: [1 sentence: most likely technical cause based on evidence]\n',
                'AFFECTED_AREA: [pipeline/job/API/SQL/streaming/etc.]\n',
                'EVIDENCE: [key data points from description and comments]\n',
                'ACTION: [1-2 sentences: actionable next step or fix]\n\n',
                'Ticket data:\n', input_for_rca,
                '\n\nBe concise. Respond ONLY with the structured format.'
            )
        ) AS rca_summary
    FROM base
)

SELECT
    key,
    issuetype,
    resolution,
    summary_clean,
    description_clean,
    comments_concat,
    priority,
    status,
    reporter,
    assignee,
    n_comments,
    n_commenters,
    text_noco,
    rca_summary,
    -- Représentation RICH : TICKET + RCA + COMMENTS (§9.1)
    LEFT(
        CONCAT(
            'TICKET: ', COALESCE(summary_clean, ''), '\n',
            'TYPE: ', issuetype, ' | PRI: ', COALESCE(priority, ''), '\n',
            'STATUS: ', COALESCE(status, ''), '\n',
            'RCA: ', COALESCE(rca_summary, ''), '\n',
            'COMMENTS: ', LEFT(COALESCE(comments_concat, ''), 1500)
        ),
        2500
    ) AS text_rich

FROM with_rca;

-- Remettre le warehouse en XS après utilisation
ALTER WAREHOUSE PFE_WH SET WAREHOUSE_SIZE = 'X-SMALL';

-- Vérification
SELECT COUNT(*) AS n_enriched_tickets FROM CORTEX.TRAIN_ENRICHED;
SELECT COUNT(CASE WHEN rca_summary IS NULL THEN 1 END) AS n_missing_rca FROM CORTEX.TRAIN_ENRICHED;
