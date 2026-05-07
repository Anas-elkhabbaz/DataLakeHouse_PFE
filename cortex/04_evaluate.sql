-- =============================================================================
-- V6 Hybrid RCA — Étape 4 : Évaluation sur le jeu de validation (§9.6)
--
-- Métriques :
--   - Top-1 accuracy par cible
--   - Macro-F1 par cible (gère le déséquilibre de classes)
--   - Matrice de confusion par cible
--   - Répartition DIRECT vs LLM par cible
-- =============================================================================

USE DATABASE PFE_SPARK;
USE SCHEMA CORTEX;
USE WAREHOUSE PFE_WH;

-- ---------------------------------------------------------------------------
-- 1. Jointure prédictions + vérité terrain
-- ---------------------------------------------------------------------------
WITH ground_truth AS (
    SELECT key, issuetype AS true_issuetype, resolution AS true_resolution
    FROM PFE_SPARK.MARTS_ML.MART_ML
    WHERE split = 'validation'
),

joined AS (
    SELECT
        p.key,
        p.predicted_issuetype,
        p.predicted_resolution,
        p.method_issuetype,
        p.method_resolution,
        gt.true_issuetype,
        gt.true_resolution,
        IFF(p.predicted_issuetype = gt.true_issuetype, 1, 0) AS correct_issuetype,
        IFF(p.predicted_resolution = gt.true_resolution, 1, 0) AS correct_resolution
    FROM CORTEX.MART_PREDICTIONS p
    JOIN ground_truth gt USING (key)
),

-- ---------------------------------------------------------------------------
-- 2. Top-1 Accuracy
-- ---------------------------------------------------------------------------
accuracy AS (
    SELECT
        ROUND(AVG(correct_issuetype) * 100, 2)  AS accuracy_issuetype_pct,
        ROUND(AVG(correct_resolution) * 100, 2) AS accuracy_resolution_pct,
        COUNT(*)                                 AS n_total
    FROM joined
),

-- ---------------------------------------------------------------------------
-- 3. Macro-F1 issuetype (per-class precision + recall → average)
-- ---------------------------------------------------------------------------
issuetype_classes AS (
    SELECT DISTINCT true_issuetype AS label FROM joined
),

issuetype_per_class AS (
    SELECT
        c.label,
        COUNT(CASE WHEN j.predicted_issuetype = c.label AND j.true_issuetype = c.label THEN 1 END) AS tp,
        COUNT(CASE WHEN j.predicted_issuetype = c.label AND j.true_issuetype != c.label THEN 1 END) AS fp,
        COUNT(CASE WHEN j.predicted_issuetype != c.label AND j.true_issuetype = c.label THEN 1 END) AS fn,
        COUNT(CASE WHEN j.true_issuetype = c.label THEN 1 END) AS support
    FROM issuetype_classes c
    CROSS JOIN joined j
    GROUP BY c.label
),

issuetype_f1 AS (
    SELECT
        label,
        tp, fp, fn, support,
        ROUND(tp / NULLIF(tp + fp, 0), 4)                                       AS precision_val,
        ROUND(tp / NULLIF(tp + fn, 0), 4)                                       AS recall_val,
        ROUND(2.0 * (tp / NULLIF(tp + fp, 0)) * (tp / NULLIF(tp + fn, 0))
              / NULLIF((tp / NULLIF(tp + fp, 0)) + (tp / NULLIF(tp + fn, 0)), 0), 4) AS f1
    FROM issuetype_per_class
),

macro_f1_issuetype AS (
    SELECT ROUND(AVG(f1), 4) AS macro_f1_issuetype
    FROM issuetype_f1
),

-- ---------------------------------------------------------------------------
-- 4. Macro-F1 resolution
-- ---------------------------------------------------------------------------
resolution_classes AS (
    SELECT DISTINCT true_resolution AS label FROM joined
),

resolution_per_class AS (
    SELECT
        c.label,
        COUNT(CASE WHEN j.predicted_resolution = c.label AND j.true_resolution = c.label THEN 1 END) AS tp,
        COUNT(CASE WHEN j.predicted_resolution = c.label AND j.true_resolution != c.label THEN 1 END) AS fp,
        COUNT(CASE WHEN j.predicted_resolution != c.label AND j.true_resolution = c.label THEN 1 END) AS fn,
        COUNT(CASE WHEN j.true_resolution = c.label THEN 1 END) AS support
    FROM resolution_classes c
    CROSS JOIN joined j
    GROUP BY c.label
),

resolution_f1 AS (
    SELECT
        label,
        tp, fp, fn, support,
        ROUND(tp / NULLIF(tp + fp, 0), 4)                                       AS precision_val,
        ROUND(tp / NULLIF(tp + fn, 0), 4)                                       AS recall_val,
        ROUND(2.0 * (tp / NULLIF(tp + fp, 0)) * (tp / NULLIF(tp + fn, 0))
              / NULLIF((tp / NULLIF(tp + fp, 0)) + (tp / NULLIF(tp + fn, 0)), 0), 4) AS f1
    FROM resolution_per_class
),

macro_f1_resolution AS (
    SELECT ROUND(AVG(f1), 4) AS macro_f1_resolution
    FROM resolution_f1
)

-- ---------------------------------------------------------------------------
-- 5. Résumé global
-- ---------------------------------------------------------------------------
SELECT
    a.accuracy_issuetype_pct,
    mi.macro_f1_issuetype,
    a.accuracy_resolution_pct,
    mr.macro_f1_resolution,
    a.n_total,
    -- Cibles : >70% accuracy issuetype, >75% accuracy resolution
    IFF(a.accuracy_issuetype_pct >= 70, 'OK', 'SOUS-CIBLE') AS issuetype_target_status,
    IFF(a.accuracy_resolution_pct >= 75, 'OK', 'SOUS-CIBLE') AS resolution_target_status
FROM accuracy a
CROSS JOIN macro_f1_issuetype mi
CROSS JOIN macro_f1_resolution mr;

-- ---------------------------------------------------------------------------
-- 6. F1 par classe — issuetype
-- ---------------------------------------------------------------------------
SELECT 'ISSUETYPE' AS target, label, precision_val, recall_val, f1, support
FROM issuetype_f1
ORDER BY support DESC;

-- ---------------------------------------------------------------------------
-- 7. F1 par classe — resolution
-- ---------------------------------------------------------------------------
SELECT 'RESOLUTION' AS target, label, precision_val, recall_val, f1, support
FROM resolution_f1
ORDER BY support DESC;

-- ---------------------------------------------------------------------------
-- 8. Matrice de confusion — issuetype
-- ---------------------------------------------------------------------------
SELECT
    true_issuetype,
    predicted_issuetype,
    COUNT(*) AS n
FROM (
    SELECT true_issuetype, predicted_issuetype
    FROM CORTEX.MART_PREDICTIONS p
    JOIN (SELECT key, issuetype AS true_issuetype FROM PFE_SPARK.MARTS_ML.MART_ML WHERE split='validation') gt
    USING (key)
)
GROUP BY true_issuetype, predicted_issuetype
ORDER BY true_issuetype, n DESC;

-- ---------------------------------------------------------------------------
-- 9. Répartition DIRECT vs LLM (shape du coût §9.5)
-- ---------------------------------------------------------------------------
SELECT
    method_issuetype,
    method_resolution,
    COUNT(*)                                       AS n_tickets,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER(), 1) AS pct
FROM CORTEX.MART_PREDICTIONS
GROUP BY method_issuetype, method_resolution
ORDER BY n_tickets DESC;
