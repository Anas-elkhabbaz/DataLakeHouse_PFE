-- =============================================================================
-- Création du stage interne Snowflake pour l'upload des CSV Kaggle
-- =============================================================================

USE DATABASE PFE_SPARK;
USE SCHEMA RAW;
USE WAREHOUSE PFE_WH;

CREATE STAGE IF NOT EXISTS RAW.CSV_STAGE
    FILE_FORMAT = (
        TYPE                        = CSV
        FIELD_OPTIONALLY_ENCLOSED_BY = '"'
        SKIP_HEADER                 = 1
        NULL_IF                     = ('', 'NULL', 'nan', 'NaN', 'none', 'None')
        ESCAPE_UNENCLOSED_FIELD     = NONE
        EMPTY_FIELD_AS_NULL         = TRUE
        FIELD_DELIMITER             = ','
        ENCODING                    = 'UTF-8'
    )
    COMMENT = 'Stage interne pour les 4 CSV du dataset Apache JIRA (Kaggle)';

-- Vérification
SHOW STAGES IN SCHEMA PFE_SPARK.RAW;
