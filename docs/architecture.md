# Architecture de la plateforme — PFE Spark Triage

## Vue d'ensemble

La plateforme adopte une **architecture en médaillon** (Bronze → Argent → Or) hébergée
intégralement sur Snowflake, orchestrée par dbt, et exposée via deux applications Streamlit.

## Schéma d'architecture

```
Fichiers CSV statiques (Kaggle, mars 2025)
  issues.csv · comments.csv · changelog.csv · issuelinks.csv
        │
        ▼  PUT + COPY INTO (load/03_put_files.py + load/04_copy_into_raw.sql)
┌───────────────────────────────────────────────────────────────────────────┐
│ Snowflake — PFE_SPARK                                                     │
│                                                                           │
│   BRONZE   RAW.ISSUES · RAW.COMMENTS · RAW.CHANGELOG · RAW.ISSUELINKS    │
│   (1:1 avec les CSV source, tout en VARCHAR)                              │
│      │                                                                    │
│      ▼  dbt run (staging/)                                                │
│   ARGENT   STAGING.STG_ISSUES · STG_COMMENTS · STG_CHANGELOG             │
│            STG_ISSUELINKS  (filtre SPARK, renommage, cast)                │
│      │                                                                    │
│      ▼  dbt run (intermediate/)                                           │
│   ARGENT   INTERMEDIATE.INT_ISSUES_CLEANED  (NLP, labels, split)         │
│            INT_COMMENTS_AGGREGATED  (LISTAGG, métriques)                 │
│            INT_CHANGELOG_FEATURES   (escalade, n_changes — novel)        │
│            INT_ISSUELINKS_FEATURES  (liens, doublons, blocages)          │
│      │                                                                    │
│      ▼  dbt run (marts/)                                                  │
│   OR       MARTS_ML.MART_ML  ─────────────────────────────────┐          │
│            MARTS_ANALYTICS.MART_ANALYTICS_OPS                 │          │
│            MARTS_ANALYTICS.MART_ANALYTICS_DEPS                │          │
└───────────────────────────────────────────────────────────────┼──────────┘
        │                               │                       │
        ▼ Chemin 2                      ▼ Chemin 1              │
  Agrégations analytiques         Pipeline V6 Hybrid RCA        │
  (vues Snowflake)                (cortex/*.sql)                │
        │                               │           ┌───────────┘
        │                   01_train_enriched.sql   │ MART_ML WHERE split='train'
        │                   02_train_embeddings.sql │ → CORTEX.TRAIN_ENRICHED
        │                   03_predict.sql          │ → CORTEX.TRAIN_EMBEDDINGS
        │                   04_evaluate.sql         │ → CORTEX.MART_PREDICTIONS
        │                               │
        ▼                               ▼
┌──────────────────────┐  ┌──────────────────────────────────────┐
│ Tableau de bord       │  │ Application d'inférence               │
│ analytics_app.py     │  │ inference_app.py                      │
│ 4 pages Streamlit    │  │ Prédiction temps réel sur 1 ticket    │
│ plotly.express       │  │ issuetype + resolution + fix_summary  │
└──────────────────────┘  └──────────────────────────────────────┘
```

## Couche Bronze (RAW)

**Rôle :** Ingestion fidèle des CSV Kaggle. Aucune transformation métier.

- Tables en VARCHAR pour absorber toute variation de format CSV
- Chargement via `COPY INTO` avec mapping positionnel `$N`
- Script `03_put_files.py` inspecte les en-têtes et valide les positions

## Couche Argent (STAGING + INTERMEDIATE)

### Staging (vues dbt)
Transformations mécaniques uniquement :
- Filtre `project_key = 'SPARK'`
- Renommage des colonnes (ex. `issuetype_name` → `issuetype_raw`)
- Cast des horodatages en `TIMESTAMP_TZ`

### Intermediate (tables dbt)
Logique métier :
- **Nettoyage NLP** : 6 étapes REGEXP_REPLACE (HTML, blocs JIRA, mentions, URLs, espaces)
- **Consolidation des labels** : jointure avec les seeds `issuetype_mapping` et `resolution_mapping`
- **Split temporel** : train (<2023) / validation (2023) / excluded (≥2024)
- **Features changelog** (contribution originale) : escalade de priorité, changements de statut/assignataire
- **Features liens** : doublons, blocages, relations

## Couche Or (MARTS)

### MARTS_ML.MART_ML
Table de contrat pour le pipeline V6 Hybrid RCA. Colonnes clés :
- `text_noco` : représentation sans commentaires (distribution validation)
- `issuetype` + `resolution` : cibles de classification
- Features changelog + liens : contribution originale du PFE

### MARTS_ANALYTICS.*
Agrégats pré-calculés pour le tableau de bord :
- `MART_ANALYTICS_OPS` : granularité mois × issuetype
- `MART_ANALYTICS_DEPS` : par assignataire et par liens de tickets

## Pipeline V6 Hybrid RCA (CORTEX)

Architecture adaptée du hackathon interne SQLI. Quatre invariants préservés :

1. **Double représentation NOCO/RICH** — élimine le biais train/validation
2. **Pas de fuite de label** dans les prompts RCA — seuls les faits observables
3. **Routage par confiance** — vote pondéré si conf ≥ seuil, LLM sinon
4. **Arbitrage LLM contraint** — sélection parmi les top-5 candidats

Modèles Cortex utilisés :
| Rôle | Modèle |
|------|--------|
| Embeddings | `voyage-multilingual-2` (1024d) |
| Résumé RCA + arbitrage | `mistral-large2` |
| Génération fix_summary | `llama3.1-70b` |

## Tests dbt

Chaque couche est couverte par des tests automatisés :
- `unique` et `not_null` sur les clés primaires
- `accepted_values` sur les labels consolidés (9 classes issuetype, 7 classes resolution)
- `relationships` (FK) entre les tables intermédiaires
- Test de count sur `mart_ml` (40 000 – 50 000 lignes attendues)
