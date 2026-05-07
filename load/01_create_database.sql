-- =============================================================================
-- Création de la base de données PFE_SPARK, des schémas et du warehouse
-- Exécuter en tant que SYSADMIN ou ACCOUNTADMIN
-- =============================================================================

USE ROLE SYSADMIN;

-- Base de données principale
CREATE DATABASE IF NOT EXISTS PFE_SPARK
    COMMENT = 'PFE Spark Triage Platform - UIR 2026';

-- Schémas par couche (architecture en médaillon)
CREATE SCHEMA IF NOT EXISTS PFE_SPARK.RAW
    COMMENT = 'Bronze : données brutes 1:1 avec les sources CSV';

CREATE SCHEMA IF NOT EXISTS PFE_SPARK.STAGING
    COMMENT = 'Silver : vues dbt stg_* (renommage, cast, filtre SPARK)';

CREATE SCHEMA IF NOT EXISTS PFE_SPARK.INTERMEDIATE
    COMMENT = 'Silver : tables dbt int_* (nettoyage NLP, agrégations, features)';

CREATE SCHEMA IF NOT EXISTS PFE_SPARK.MARTS_ML
    COMMENT = 'Or : mart_ml — contrat de données pour le pipeline V6 Hybrid RCA';

CREATE SCHEMA IF NOT EXISTS PFE_SPARK.MARTS_ANALYTICS
    COMMENT = 'Or : mart_analytics_* — agrégats pour le tableau de bord';

CREATE SCHEMA IF NOT EXISTS PFE_SPARK.CORTEX
    COMMENT = 'Pipeline V6 Hybrid RCA : embeddings, prédictions, évaluations';

-- Warehouse dédié au projet
CREATE WAREHOUSE IF NOT EXISTS PFE_WH
    WAREHOUSE_SIZE    = 'X-SMALL'
    AUTO_SUSPEND      = 60
    AUTO_RESUME       = TRUE
    INITIALLY_SUSPENDED = TRUE
    COMMENT = 'Warehouse PFE — passer en MEDIUM pour les scripts Cortex';

-- Vérification
SHOW SCHEMAS IN DATABASE PFE_SPARK;
