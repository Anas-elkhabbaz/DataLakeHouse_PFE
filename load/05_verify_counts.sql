-- =============================================================================
-- Vérification des comptes de lignes après COPY INTO
-- Valeurs attendues selon le dataset Kaggle (mars 2025)
-- =============================================================================

USE DATABASE PFE_SPARK;
USE SCHEMA RAW;

-- Seuils minimums basés sur les chargements réels (non des valeurs exactes)
SELECT
    'RAW.ISSUES'     AS table_name,
    COUNT(*)         AS row_count,
    1000000          AS min_expected,
    IFF(COUNT(*) >= 1000000, 'OK', 'BELOW THRESHOLD') AS status
FROM RAW.ISSUES
UNION ALL
SELECT 'RAW.COMMENTS', COUNT(*), 4500000,
    IFF(COUNT(*) >= 4500000, 'OK', 'BELOW THRESHOLD')
FROM RAW.COMMENTS
UNION ALL
SELECT 'RAW.CHANGELOG', COUNT(*), 9000000,
    IFF(COUNT(*) >= 9000000, 'OK', 'BELOW THRESHOLD')
FROM RAW.CHANGELOG
UNION ALL
SELECT 'RAW.ISSUELINKS', COUNT(*), 350000,
    IFF(COUNT(*) >= 350000, 'OK', 'BELOW THRESHOLD')
FROM RAW.ISSUELINKS;

-- Vérification du sous-ensemble SPARK
SELECT
    COUNT(*) AS spark_issues_count,
    49832    AS expected_approx,
    IFF(COUNT(*) BETWEEN 45000 AND 55000, 'OK', 'CHECK DATA') AS status
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
