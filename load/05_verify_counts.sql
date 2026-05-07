-- =============================================================================
-- Vérification des comptes de lignes après COPY INTO
-- Valeurs attendues selon le dataset Kaggle (mars 2025)
-- =============================================================================

USE DATABASE PFE_SPARK;
USE SCHEMA RAW;

SELECT 'RAW.ISSUES'     AS table_name, COUNT(*) AS row_count, 18552208 AS expected FROM RAW.ISSUES
UNION ALL
SELECT 'RAW.COMMENTS'   AS table_name, COUNT(*) AS row_count, 62356265 AS expected FROM RAW.COMMENTS
UNION ALL
SELECT 'RAW.CHANGELOG'  AS table_name, COUNT(*) AS row_count, 40490946 AS expected FROM RAW.CHANGELOG
UNION ALL
SELECT 'RAW.ISSUELINKS' AS table_name, COUNT(*) AS row_count, 390068   AS expected FROM RAW.ISSUELINKS;

-- Vérification du sous-ensemble SPARK
SELECT COUNT(*) AS spark_issues_count, 49833 AS expected
FROM RAW.ISSUES
WHERE project_key = 'SPARK';

-- Aperçu des valeurs issuetype pour validation du mapping
SELECT issuetype_name, COUNT(*) AS n
FROM RAW.ISSUES
WHERE project_key = 'SPARK'
GROUP BY issuetype_name
ORDER BY n DESC;

-- Aperçu des valeurs resolution pour validation du mapping
SELECT resolution_name, COUNT(*) AS n
FROM RAW.ISSUES
WHERE project_key = 'SPARK'
GROUP BY resolution_name
ORDER BY n DESC;
