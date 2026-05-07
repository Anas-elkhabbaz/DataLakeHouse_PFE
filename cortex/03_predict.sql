-- =============================================================================
-- V6 Hybrid RCA — Étape 3 : Inférence sur le jeu de validation (§9.4)
--
-- Pipeline complet par ticket de validation :
--   Step 1  : Embed text_noco de validation
--   Step 2  : CROSS JOIN avec TRAIN_EMBEDDINGS + cosinus sur embedding_noco
--   Step 3  : Boost métadonnées → fused_score
--   Step 4  : TOP-15 par ticket de validation
--   Step 5  : Agrégation des scores par label (issuetype + resolution)
--   Step 6  : Conf / margin / div → gate DIRECT vs LLM
--   Step 7  : Arbitrage LLM (mistral-large2) si nécessaire
--   Step 8  : Normalisation du label via EDITDISTANCE
--   Step 9  : Génération fix_summary (llama3.1-70b)
--
-- IMPORTANT : Utiliser un warehouse LARGE pour ce script.
-- La jointure croisée 4 700 × 41 400 = ~194M comparaisons.
-- Durée estimée : 30–90 min selon le warehouse.
-- =============================================================================

USE DATABASE PFE_SPARK;
USE SCHEMA CORTEX;
USE WAREHOUSE PFE_WH;

ALTER WAREHOUSE PFE_WH SET WAREHOUSE_SIZE = 'LARGE';

-- Table de destination
CREATE OR REPLACE TABLE CORTEX.MART_PREDICTIONS (
    key                   VARCHAR NOT NULL,
    predicted_issuetype   VARCHAR,
    predicted_resolution  VARCHAR,
    fix_summary           VARCHAR,
    method_issuetype      VARCHAR,  -- 'DIRECT' ou 'LLM'
    method_resolution     VARCHAR   -- 'DIRECT' ou 'LLM'
)
COMMENT = 'Prédictions V6 Hybrid RCA sur le jeu de validation';

INSERT INTO CORTEX.MART_PREDICTIONS

WITH

-- -------------------------------------------------------------------------
-- Step 1 : Embedding des tickets de validation (NOCO uniquement)
-- -------------------------------------------------------------------------
val_embeddings AS (
    SELECT
        m.key,
        m.issuetype        AS true_issuetype,
        m.resolution       AS true_resolution,
        m.priority         AS val_priority,
        m.status           AS val_status,
        m.reporter         AS val_reporter,
        m.text_noco        AS val_text_noco,
        SNOWFLAKE.CORTEX.EMBED_TEXT_1024(
            'voyage-multilingual-2',
            LEFT(m.text_noco, 1000)
        ) AS emb
    FROM PFE_SPARK.MARTS_ML.MART_ML m
    WHERE m.split = 'validation'
),

-- -------------------------------------------------------------------------
-- Step 2 + 3 : Similarité cosinus + boost métadonnées
-- -------------------------------------------------------------------------
raw_sim AS (
    SELECT
        v.key              AS val_key,
        v.true_issuetype,
        v.true_resolution,
        v.val_priority,
        v.val_status,
        v.val_reporter,
        v.val_text_noco,
        t.key              AS train_key,
        t.issuetype        AS train_issuetype,
        t.resolution       AS train_resolution,
        t.priority         AS train_priority,
        t.status           AS train_status,
        t.reporter         AS train_reporter,
        t.text_rich        AS train_text_rich,
        VECTOR_COSINE_SIMILARITY(t.embedding_noco, v.emb) AS cosine_sim,
        -- Boost métadonnées (§9.4 Step 3)
        VECTOR_COSINE_SIMILARITY(t.embedding_noco, v.emb)
            + IFF(v.val_priority = t.priority, 0.10, 0.0)
            + IFF(v.val_status   = t.status,   0.08, 0.0)
            + IFF(v.val_reporter = t.reporter,  0.05, 0.0)  AS fused_score
    FROM val_embeddings v
    CROSS JOIN CORTEX.TRAIN_EMBEDDINGS t
),

-- -------------------------------------------------------------------------
-- Step 4 : TOP-15 voisins par ticket de validation
-- -------------------------------------------------------------------------
ranked AS (
    SELECT *,
        ROW_NUMBER() OVER (PARTITION BY val_key ORDER BY fused_score DESC) AS rk
    FROM raw_sim
),

top15 AS (
    SELECT * FROM ranked WHERE rk <= 15
),

-- -------------------------------------------------------------------------
-- Step 5a : Agrégation des scores par issuetype
-- -------------------------------------------------------------------------
issuetype_label_scores AS (
    SELECT val_key, train_issuetype AS label, SUM(fused_score) AS label_score
    FROM top15
    GROUP BY val_key, train_issuetype
),

issuetype_total AS (
    SELECT val_key,
           SUM(label_score)          AS total_score,
           COUNT(DISTINCT label)     AS div
    FROM issuetype_label_scores
    GROUP BY val_key
),

issuetype_ranked AS (
    SELECT val_key, label, label_score,
           ROW_NUMBER() OVER (PARTITION BY val_key ORDER BY label_score DESC) AS rnk
    FROM issuetype_label_scores
),

issuetype_top2 AS (
    SELECT
        r1.val_key,
        r1.label                          AS top1,
        r1.label_score                    AS top1_score,
        COALESCE(r2.label_score, 0.0)     AS top2_score,
        t.total_score,
        t.div
    FROM issuetype_ranked r1
    LEFT JOIN issuetype_ranked r2
        ON r1.val_key = r2.val_key AND r2.rnk = 2
    JOIN issuetype_total t ON r1.val_key = t.val_key
    WHERE r1.rnk = 1
),

-- Confidence gate issuetype (§9.4 Step 5)
issuetype_decision AS (
    SELECT
        val_key,
        top1  AS pred_issuetype_raw,
        top1_score / NULLIF(total_score, 0)                          AS conf,
        (top1_score - top2_score) / NULLIF(top1_score, 0)           AS margin,
        div,
        CASE
            WHEN top1_score / NULLIF(total_score, 0) >= 0.55
             AND div <= 4
             AND (top1_score - top2_score) / NULLIF(top1_score, 0) >= 0.20
            THEN 'DIRECT'
            ELSE 'LLM'
        END AS method_issuetype
    FROM issuetype_top2
),

-- -------------------------------------------------------------------------
-- Step 5b : Agrégation des scores par resolution (même top15)
-- -------------------------------------------------------------------------
resolution_label_scores AS (
    SELECT val_key, train_resolution AS label, SUM(fused_score) AS label_score
    FROM top15
    GROUP BY val_key, train_resolution
),

resolution_total AS (
    SELECT val_key,
           SUM(label_score)          AS total_score,
           COUNT(DISTINCT label)     AS div
    FROM resolution_label_scores
    GROUP BY val_key
),

resolution_ranked AS (
    SELECT val_key, label, label_score,
           ROW_NUMBER() OVER (PARTITION BY val_key ORDER BY label_score DESC) AS rnk
    FROM resolution_label_scores
),

resolution_top2 AS (
    SELECT
        r1.val_key,
        r1.label                          AS top1,
        r1.label_score                    AS top1_score,
        COALESCE(r2.label_score, 0.0)     AS top2_score,
        t.total_score,
        t.div
    FROM resolution_ranked r1
    LEFT JOIN resolution_ranked r2
        ON r1.val_key = r2.val_key AND r2.rnk = 2
    JOIN resolution_total t ON r1.val_key = t.val_key
    WHERE r1.rnk = 1
),

-- Confidence gate resolution (seuils assouplis — Fixed domine §9.4 Step 5)
resolution_decision AS (
    SELECT
        val_key,
        top1  AS pred_resolution_raw,
        top1_score / NULLIF(total_score, 0)                        AS conf,
        (top1_score - top2_score) / NULLIF(top1_score, 0)         AS margin,
        div,
        CASE
            WHEN top1_score / NULLIF(total_score, 0) >= 0.50
             AND div <= 4
             AND (top1_score - top2_score) / NULLIF(top1_score, 0) >= 0.15
            THEN 'DIRECT'
            ELSE 'LLM'
        END AS method_resolution
    FROM resolution_top2
),

-- -------------------------------------------------------------------------
-- Step 6 : Décisions combinées
-- -------------------------------------------------------------------------
decisions AS (
    SELECT
        id.val_key,
        id.pred_issuetype_raw,
        id.method_issuetype,
        rd.pred_resolution_raw,
        rd.method_resolution
    FROM issuetype_decision id
    JOIN resolution_decision rd ON id.val_key = rd.val_key
),

-- -------------------------------------------------------------------------
-- Step 7a : Contexte pour l'arbitrage LLM — top-5 candidats issuetype
-- -------------------------------------------------------------------------
issuetype_top5_ctx AS (
    SELECT val_key,
           LISTAGG(CONCAT(LPAD(rnk::VARCHAR, 2), '. ', label, ' (score: ', ROUND(label_score, 4), ')'), '\n')
               WITHIN GROUP (ORDER BY rnk) AS candidates
    FROM issuetype_ranked
    WHERE rnk <= 5
    GROUP BY val_key
),

resolution_top5_ctx AS (
    SELECT val_key,
           LISTAGG(CONCAT(LPAD(rnk::VARCHAR, 2), '. ', label, ' (score: ', ROUND(label_score, 4), ')'), '\n')
               WITHIN GROUP (ORDER BY rnk) AS candidates
    FROM resolution_ranked
    WHERE rnk <= 5
    GROUP BY val_key
),

-- Contexte voisins (top-5 text_rich)
neighbor_ctx AS (
    SELECT val_key,
           LISTAGG(
               CONCAT('[', train_issuetype, '/', train_resolution, ']\n',
                      LEFT(train_text_rich, 250)),
               '\n---\n'
           ) WITHIN GROUP (ORDER BY rk) AS ctx
    FROM top15
    WHERE rk <= 5
    GROUP BY val_key
),

-- -------------------------------------------------------------------------
-- Step 7b : Arbitrage LLM issuetype (uniquement si method = 'LLM')
-- -------------------------------------------------------------------------
issuetype_llm AS (
    SELECT
        d.val_key,
        CASE
            WHEN d.method_issuetype = 'DIRECT' THEN d.pred_issuetype_raw
            ELSE SNOWFLAKE.CORTEX.COMPLETE(
                'mistral-large2',
                CONCAT(
                    'You are an Apache Spark issue classifier. Given the candidate labels ranked by ',
                    'retrieval evidence and the ticket context, pick the BEST label.\n\n',
                    'CANDIDATE LABELS (ranked by evidence score):\n', ic.candidates, '\n\n',
                    'SIMILAR TICKET EVIDENCE (top-5 retrieved tickets):\n',
                    LEFT(nc.ctx, 1200), '\n\n',
                    'TICKET TO CLASSIFY:\n', LEFT(v.val_text_noco, 1500), '\n\n',
                    'IMPORTANT: The top-ranked candidate is usually correct. ',
                    'Only override if the ticket clearly does not match.\n',
                    'Pick from the candidate labels above. Respond with ONLY the label. No explanation.'
                )
            )
        END AS predicted_issuetype_raw
    FROM decisions d
    JOIN issuetype_top5_ctx ic ON d.val_key = ic.val_key
    JOIN neighbor_ctx nc       ON d.val_key = nc.val_key
    JOIN val_embeddings v      ON d.val_key = v.key
),

-- Step 7c : Arbitrage LLM resolution
resolution_llm AS (
    SELECT
        d.val_key,
        CASE
            WHEN d.method_resolution = 'DIRECT' THEN d.pred_resolution_raw
            ELSE SNOWFLAKE.CORTEX.COMPLETE(
                'mistral-large2',
                CONCAT(
                    'You are an Apache Spark issue resolution predictor. ',
                    'Pick the most likely resolution outcome for this ticket.\n\n',
                    'CANDIDATE RESOLUTIONS (ranked by evidence score):\n', rc.candidates, '\n\n',
                    'SIMILAR TICKET EVIDENCE (top-5 retrieved tickets):\n',
                    LEFT(nc.ctx, 1200), '\n\n',
                    'TICKET:\n', LEFT(v.val_text_noco, 1500), '\n\n',
                    'IMPORTANT: The top-ranked candidate is usually correct. ',
                    'Only override if there is clear evidence otherwise.\n',
                    'Respond with ONLY the resolution label. No explanation.'
                )
            )
        END AS predicted_resolution_raw
    FROM decisions d
    JOIN resolution_top5_ctx rc ON d.val_key = rc.val_key
    JOIN neighbor_ctx nc        ON d.val_key = nc.val_key
    JOIN val_embeddings v       ON d.val_key = v.key
),

-- -------------------------------------------------------------------------
-- Step 8 : Normalisation des labels via EDITDISTANCE (§9.4 Step 8)
-- -------------------------------------------------------------------------
valid_issuetypes AS (
    SELECT column1 AS label
    FROM (VALUES
        ('Bug'), ('Improvement'), ('Sub-task'), ('New Feature'),
        ('Task'), ('Test'), ('Documentation'), ('Question'), ('Other')
    )
),

valid_resolutions AS (
    SELECT column1 AS label
    FROM (VALUES
        ('Fixed'), ("Won't Fix"), ('Not A Problem'),
        ('Incomplete'), ('Duplicate'), ('Invalid'), ('Cannot Reproduce')
    )
),

issuetype_normalized AS (
    SELECT il.val_key, vi.label AS predicted_issuetype
    FROM issuetype_llm il
    CROSS JOIN valid_issuetypes vi
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY il.val_key
        ORDER BY
            CASE WHEN vi.label = il.predicted_issuetype_raw THEN 0
                 ELSE 1 + EDITDISTANCE(UPPER(il.predicted_issuetype_raw), UPPER(vi.label))
            END
    ) = 1
),

resolution_normalized AS (
    SELECT rl.val_key, vr.label AS predicted_resolution
    FROM resolution_llm rl
    CROSS JOIN valid_resolutions vr
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY rl.val_key
        ORDER BY
            CASE WHEN vr.label = rl.predicted_resolution_raw THEN 0
                 ELSE 1 + EDITDISTANCE(UPPER(rl.predicted_resolution_raw), UPPER(vr.label))
            END
    ) = 1
),

-- -------------------------------------------------------------------------
-- Step 9 : Génération fix_summary (llama3.1-70b, 1 appel/ticket)
-- -------------------------------------------------------------------------
neighbor_fixes AS (
    SELECT val_key,
           LEFT(
               LISTAGG(
                   CONCAT('[', train_issuetype, '/', train_resolution, ']\n',
                          LEFT(train_text_rich, 400)),
                   '\n---\n'
               ) WITHIN GROUP (ORDER BY rk),
               1500
           ) AS fixes_ctx
    FROM top15
    WHERE rk <= 3
    GROUP BY val_key
),

fix_summaries AS (
    SELECT
        in_.val_key,
        SNOWFLAKE.CORTEX.COMPLETE(
            'llama3.1-70b',
            CONCAT(
                'You are an Apache Spark engineer. Given this issue and similar resolved tickets, ',
                'write 1-2 concise sentences describing the likely fix.\n\n',
                'Predicted issuetype: ', in_.predicted_issuetype, '\n',
                'Predicted resolution: ', rn_.predicted_resolution, '\n\n',
                'Issue:\n', LEFT(v.val_text_noco, 1200), '\n\n',
                'Top-3 similar resolved tickets (with their fixes):\n',
                nf.fixes_ctx, '\n\n',
                'Respond with ONLY 1-2 sentences. Be specific and actionable. In English.'
            )
        ) AS fix_summary
    FROM issuetype_normalized in_
    JOIN resolution_normalized rn_ ON in_.val_key = rn_.val_key
    JOIN neighbor_fixes nf         ON in_.val_key = nf.val_key
    JOIN val_embeddings v          ON in_.val_key = v.key
),

-- -------------------------------------------------------------------------
-- Sortie finale
-- -------------------------------------------------------------------------
final AS (
    SELECT
        in_.val_key                   AS key,
        in_.predicted_issuetype,
        rn_.predicted_resolution,
        fs.fix_summary,
        d.method_issuetype,
        d.method_resolution
    FROM issuetype_normalized in_
    JOIN resolution_normalized rn_ ON in_.val_key = rn_.val_key
    JOIN fix_summaries fs           ON in_.val_key = fs.val_key
    JOIN decisions d                ON in_.val_key = d.val_key
)

SELECT key, predicted_issuetype, predicted_resolution, fix_summary,
       method_issuetype, method_resolution
FROM final;

ALTER WAREHOUSE PFE_WH SET WAREHOUSE_SIZE = 'X-SMALL';

SELECT COUNT(*) AS n_predictions FROM CORTEX.MART_PREDICTIONS;
SELECT method_issuetype, method_resolution, COUNT(*) AS n
FROM CORTEX.MART_PREDICTIONS
GROUP BY method_issuetype, method_resolution;
