-- =============================================================================
-- V6 Hybrid RCA — Étape 2 : Calcul des embeddings duaux (§9.1, §9.2)
--
-- Pour chaque ticket d'entraînement :
--   - embedding_noco : embed(text_noco, 1000 chars) — distribution de récupération
--   - embedding_rich : embed(text_rich, 2500 chars) — contexte LLM
--
-- Modèle : voyage-multilingual-2 → VECTOR(FLOAT, 1024)
-- Durée estimée : ~10–20 min sur MEDIUM warehouse (~82 000 appels embed)
-- =============================================================================

USE DATABASE PFE_SPARK;
USE SCHEMA CORTEX;
USE WAREHOUSE PFE_WH;

ALTER WAREHOUSE PFE_WH SET WAREHOUSE_SIZE = 'MEDIUM';

CREATE OR REPLACE TABLE CORTEX.TRAIN_EMBEDDINGS (
    key              VARCHAR        NOT NULL,
    issuetype        VARCHAR        NOT NULL,
    resolution       VARCHAR        NOT NULL,
    priority         VARCHAR,
    status           VARCHAR,
    reporter         VARCHAR,
    text_rich        VARCHAR,        -- Conservé pour le contexte LLM lors de l'inférence
    embedding_noco   VECTOR(FLOAT, 1024) NOT NULL,
    embedding_rich   VECTOR(FLOAT, 1024) NOT NULL
)
COMMENT = 'Embeddings duaux NOCO/RICH pour le pipeline V6 Hybrid RCA';

INSERT INTO CORTEX.TRAIN_EMBEDDINGS
SELECT
    key,
    issuetype,
    resolution,
    priority,
    status,
    reporter,
    text_rich,
    SNOWFLAKE.CORTEX.EMBED_TEXT_1024(
        'voyage-multilingual-2',
        LEFT(text_noco, 1000)   -- Tronqué à 1000 chars : correspond à la distribution validation
    ) AS embedding_noco,
    SNOWFLAKE.CORTEX.EMBED_TEXT_1024(
        'voyage-multilingual-2',
        LEFT(text_rich, 2500)   -- Tronqué à 2500 chars : représentation enrichie complète
    ) AS embedding_rich
FROM CORTEX.TRAIN_ENRICHED;

ALTER WAREHOUSE PFE_WH SET WAREHOUSE_SIZE = 'X-SMALL';

-- Vérification
SELECT COUNT(*) AS n_embeddings FROM CORTEX.TRAIN_EMBEDDINGS;

-- Distribution des classes dans l'index
SELECT issuetype, COUNT(*) AS n
FROM CORTEX.TRAIN_EMBEDDINGS
GROUP BY issuetype
ORDER BY n DESC;
