# Architecture de la plateforme — PFE Spark Triage (V6 Hybrid RCA)

## Vue d'ensemble

La plateforme adopte une **architecture en médaillon** (Bronze → Argent → Or) hébergée sur
Snowflake, orchestrée par dbt-snowflake, et exposée via deux applications Streamlit conteneurisées
avec Docker. Le pipeline d'inférence implémente l'architecture **V6 Hybrid RCA** : embeddings
duaux (NOCO + RICH), fusion Reciprocal Rank Fusion (RRF), ré-ranking changelog, gate de
confiance, et arbitrage LLM optionnel (Ollama ou Anthropic).

---

## Schéma d'architecture

```
Fichiers CSV source (Kaggle, mars 2025)
  issues.csv (1,9 GB) · comments.csv (4 GB) · changelog.csv (2,7 GB) · issuelinks.csv
        │
        ▼  python load/run_phase1.py  →  Snowflake: PFE_SPARK database + 6 schemas + PFE_WH
        ▼  python load/03_put_files.py  →  PUT vers @RAW.CSV_STAGE
        ▼  python load/run_phase4.py   →  COPY INTO tables brutes
┌───────────────────────────────────────────────────────────────────────────────────┐
│ Snowflake — PFE_SPARK                                                             │
│                                                                                   │
│  BRONZE (RAW)                                                                     │
│  RAW.ISSUES (1 149 321) · RAW.COMMENTS (5 047 714)                               │
│  RAW.CHANGELOG (9 653 526) · RAW.ISSUELINKS (390 063)                            │
│  Tout en VARCHAR — aucune transformation de type                                  │
│       │                                                                           │
│       ▼  dbt run — staging/ (vues)                                                │
│  ARGENT — STAGING                                                                 │
│  STG_ISSUES (49 832 tickets SPARK) · STG_COMMENTS · STG_CHANGELOG · STG_ISSUELINKS│
│  Filtre project_key='SPARK', renommage, cast TIMESTAMP_TZ, QUALIFY déduplication │
│       │                                                                           │
│       ▼  dbt run — intermediate/ (tables)                                         │
│  ARGENT — INTERMEDIATE                                                            │
│  INT_ISSUES_CLEANED  (45 043) — NLP 6 étapes, mapping labels, split 3-way        │
│  INT_COMMENTS_AGGREGATED (41 986) — first-5+last-3 strategy, 400 chars/comment   │
│  INT_CHANGELOG_FEATURES  (29 937) — escalade, déescalade, transitions, n_people  │
│  INT_ISSUELINKS_FEATURES (11 179) — doublons, blocages, relations                │
│       │                                                                           │
│       ▼  dbt run — marts/ (tables)                                                │
│  OR                                                                               │
│  MARTS_ML.MART_ML (42 083)  ──────────────────────────────────────┐             │
│  MARTS_ANALYTICS.MART_ANALYTICS_OPS (1 352 lignes mois×type)      │             │
│  MARTS_ANALYTICS.MART_ANALYTICS_WORKLOAD (flat assignataires)      │             │
│  MARTS_ANALYTICS.MART_ANALYTICS_LINKS (flat liens)                 │             │
└────────────────────────────────────────────────────────────────────┼─────────────┘
        │                                    │
        ▼ Chemin 2                           ▼ Chemin 1
  Dashboard analytique               Pipeline ML Python (V6 Hybrid RCA)
        │                            python load/run_ml_pipeline.py --phase tune
        │
        │              ┌──────────────────────────────────────────────────────────┐
        │              │  V6 Hybrid RCA — load/run_ml_pipeline.py                 │
        │              │                                                           │
        │              │  1. Fetch MART_ML depuis Snowflake                        │
        │              │  2. Embeddings duaux (BAAI/bge-large-en-v1.5, 1024d)    │
        │              │     · text_noco → embeddings_noco.npz                    │
        │              │     · text_rich → embeddings_rich.npz                    │
        │              │  3. Par ticket query :                                    │
        │              │     ┌─────────────────────────────────────────────┐      │
        │              │     │ query_emb_noco  ──────────────────────┐     │      │
        │              │     │ query_emb_rich  ──────────────────────┤     │      │
        │              │     │                                        ▼     │      │
        │              │     │          RRF (k=60, top-30)                  │      │
        │              │     │                 │                            │      │
        │              │     │                 ▼                            │      │
        │              │     │    Metadata boost (priority/status/reporter) │      │
        │              │     │    + Changelog re-rank (L2 standardisé)     │      │
        │              │     │                 │                            │      │
        │              │     │                 ▼ top-15 voisins             │      │
        │              │     │    Vote pondéré → issuetype + résolution     │      │
        │              │     │                 │                            │      │
        │              │     │          l0_conf ≥ 0.65 AND margin ≥ 0.10? │      │
        │              │     │           ┌─────┴─────┐                     │      │
        │              │     │           ▼           ▼                     │      │
        │              │     │        DIRECT    LLM_REQUIRED               │      │
        │              │     │           │           │                     │      │
        │              │     │           │      Anthropic/Ollama           │      │
        │              │     │           │      arbitrage contraint        │      │
        │              │     │           │      rapidfuzz normalization    │      │
        │              │     └───────────┴───────────────────────────────┘       │
        │              │                                                           │
        │              │  4. Évaluation : accuracy + macro-F1 + CI bootstrap      │
        │              │  5. Confusion matrices → results/confusion_*.png         │
        │              │  6. Upload → CORTEX.MART_PREDICTIONS                     │
        │              │     (routing_issuetype, l0_conf, margin colonnes)        │
        │              └──────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────┐  ┌──────────────────────────────────────────┐
│  analytics_app  │  │  inference_app                            │
│  5 pages        │  │  V6 temps réel sur 1 ticket              │
│  plotly.express │  │  · validation input (≥10 / ≥20 chars)   │
│  @cache_data    │  │  · dual embed → RRF → changelog sim      │
│  port 8502      │  │  · routing badge (DIRECT / LLM_REQUIRED) │
│                 │  │  · l0_conf + margin métriques            │
│  Page 5 :       │  │  · top-5 similar + fix_summary           │
│  Anomalies      │  │  · latency metric (ms)                   │
│  changelog      │  │  · LLM analysis (Anthropic/Ollama)       │
└─────────────────┘  │  port 8501                               │
                     └──────────────────────────────────────────┘
```

---

## Couche Bronze (RAW)

**Rôle :** Ingestion fidèle des CSV Kaggle. Zéro transformation métier.

- Tables entièrement en VARCHAR pour absorber toute variation de format CSV
- Chargement via `COPY INTO` avec mapping positionnel `$N` documenté dans `load/04_copy_into_raw.sql`
- Script `inspect_headers.py` affiche les en-têtes réels pour vérifier le mapping avant chargement
- `run_phase4.py` exécute le COPY INTO et vérifie les comptes attendus (≥ seuils minimum)

**Comptes réels chargés :**

| Table | Lignes chargées |
|-------|----------------|
| RAW.ISSUES | 1 149 321 |
| RAW.COMMENTS | 5 047 714 |
| RAW.CHANGELOG | 9 653 526 |
| RAW.ISSUELINKS | 390 063 |
| dont issues SPARK | 49 832 |

---

## Couche Argent (STAGING + INTERMEDIATE)

### Staging — vues dbt

Transformations mécaniques uniquement, sans logique métier :

- Filtre `project_key = 'SPARK'` (STG_ISSUES)
- Renommage des colonnes (ex. `issuetype_name` → `issuetype_raw`)
- Cast des horodatages en `TIMESTAMP_TZ` via `TRY_TO_TIMESTAMP_TZ`
- `QUALIFY ROW_NUMBER() OVER (PARTITION BY key ORDER BY id) = 1` pour dédupliquer 4 clés en double
- Filtre `stg_changelog` : uniquement les champs `('STATUS', 'PRIORITY', 'RESOLUTION', 'ASSIGNEE', 'ISSUETYPE')`

### Intermediate — tables dbt

Logique métier et feature engineering :

**INT_ISSUES_CLEANED (45 043 lignes)**
- Nettoyage NLP en 6 étapes via macro `clean_jira_text` :
  HTML, blocs `{code}`, blocs `{noformat}`, mentions `[~user]`, URLs, espaces multiples
- Consolidation des labels : LEFT JOIN avec `seeds/issuetype_mapping.csv` (9 classes)
  et `seeds/resolution_mapping.csv` (7 classes) — les valeurs absentes du seed donnent NULL → filtrées
- Split temporel 3-way :
  - `train` : créé avant 2022-01-01
  - `validation` : 2022-01-01 ≤ créé < 2023-01-01
  - `test` : 2023-01-01 ≤ créé < 2024-01-01
  - `excluded` : ≥ 2024-01-01
- `resolution_days` DATEDIFF plafonné à 5000

**INT_COMMENTS_AGGREGATED (41 986 lignes)**
- Stratégie first-5 + last-3 : premiers 5 commentaires chronologiques + derniers 3 (si > 5 total)
- Chaque snippet tronqué à 400 caractères
- LISTAGG avec séparateur ` || ` (ORDER BY created_at)
- `n_comments` : nombre total de commentaires ; `n_commenters` : auteurs distincts

**INT_CHANGELOG_FEATURES (29 937 lignes)**
- Features d'escalade :
  - `was_escalated` : 1 si priorité a augmenté au moins une fois (Minor → Major, etc.)
  - `was_deescalated` : 1 si priorité a diminué au moins une fois
- Compteurs : n_total_changes, n_status_changes, n_priority_changes, n_assignee_changes
- `n_people_involved` : nombre d'auteurs distincts dans le changelog

**INT_ISSUELINKS_FEATURES (11 179 lignes)**
- Compteurs par type de lien : n_links_total, n_duplicates, n_blocks, n_blocked_by, n_relates

---

## Couche Or (MARTS)

### MARTS_ML.MART_ML — 42 083 lignes

Table de contrat pour le pipeline d'inférence. Jointure large des 4 tables intermédiaires.
Filtrée sur `split IN ('train', 'validation', 'test')` — les tickets 2024+ sont exclus.

| Partition | Lignes |
|-----------|--------|
| train | ~38 274 |
| validation | ~3 809 |
| test | ~3 700 |
| Total | 42 083 |

**Colonnes texte pour l'embedding dual :**

`text_noco` — sans commentaires, sans labels de classification :
```
TICKET: {summary}
PRI: {priority}
STATUS: {status}
DESC: {description[:1500]}
```
Tronquée à 2000 caractères. Sert à l'embedding de récupération et au corpus BM25.

`text_rich` — avec commentaires, sans labels de classification :
```
TICKET: {summary}
PRIORITY: {priority}
STATUS: {status}
N_COMMENTS: {n_comments}
DESCRIPTION: {description[:2000]}
DISCUSSION: {all_comments[:2500]}
```
Tronquée à 6000 caractères. Capture le contexte de discussion pour l'embedding sémantique.

### MARTS_ANALYTICS

- **MART_ANALYTICS_OPS** (1 352 lignes) : agrégats mensuels × issuetype
- **MART_ANALYTICS_WORKLOAD** : métriques par assignataire (n_assigned, n_fixed, avg_resolution_days, top_issuetype)
- **MART_ANALYTICS_LINKS** : métriques par ticket (n_duplicates, n_blocks, n_blocked_by, n_relates)

---

## Pipeline d'inférence — V6 Hybrid RCA

### Modèle d'embedding

| Propriété | Valeur |
|-----------|--------|
| Modèle | `BAAI/bge-large-en-v1.5` (sentence-transformers) |
| Dimensions | 1024 |
| Préfixe query | `"Represent this sentence for searching relevant passages: "` |
| Documents | Encodés sans préfixe |
| Normalisation | L2-normalisée → similarité cosinus = produit scalaire |
| Cache NOCO | `results/embeddings_noco.npz` |
| Cache RICH | `results/embeddings_rich.npz` |

### Algorithme de prédiction (par ticket query)

1. Encoder `QUERY_PREFIX + text_noco` → `q_noco` (1024d)
2. Encoder `QUERY_PREFIX + text_rich` → `q_rich` (1024d)
3. Cosine scores NOCO : `s_noco = train_emb_noco @ q_noco` (n_train valeurs)
4. Cosine scores RICH : `s_rich = train_emb_rich @ q_rich`
5. **RRF (k=60)** : fusionner les listes de rang → top-30 candidats
6. **Metadata boost** sur les top-30 : +0.10 si même priorité, +0.08 si même statut, +0.05 si même reporter
7. **Changelog re-rank** : similarité L2 inverse dans l'espace changelog standardisé
8. Score final = 1.0×RRF + 0.15×meta_boost + 0.10×changelog_sim
9. Garder les 15 meilleures (k=15)
10. Vote pondéré → issuetype + résolution + l0_conf + margin
11. **Gate de confiance** : DIRECT si l0_conf ≥ 0.65 ET margin ≥ 0.10, sinon LLM_REQUIRED
12. Si LLM_REQUIRED : envoyer au LLM (Anthropic haiku / Ollama mistral) avec liste de labels contrainte

### Module partagé `load/retrieval.py`

Ce module est importé à la fois par `run_ml_pipeline.py` (batch) et `inference_app.py` (temps réel),
garantissant la cohérence exacte entre les deux chemins.

Fonctions exportées :
- `rrf_fuse(scores_noco, scores_rich, k=60, top_k=30)` → (indices, rrf_scores)
- `metadata_boost(...)` → boost array
- `build_scaler(train_df)` → StandardScaler ajusté sur les changelog features
- `changelog_sim(q_cl, cand_cl)` → 1/(1+L2) similarity
- `fuse_scores(rrf, meta, cl, alpha=1.0, beta=0.15, gamma=0.10)` → final scores
- `weighted_vote(labels, weights)` → (best_label, l0_conf, margin, scores_dict)
- `route(l0_conf, margin)` → "DIRECT" | "LLM_REQUIRED"

### LLM Layer (`cortex/`)

| Module | Rôle |
|--------|------|
| `llm_client.py` | Adapter backend-agnostic : Anthropic si API key présente, sinon Ollama |
| `arbitration.py` | Arbitrage contraint sur liste de labels valides, normalisation rapidfuzz |
| `fix_summary.py` | Résumé de correction lazy, cache JSON dans `results/fix_summaries.json` |

Si `LLMUnavailableError` est levé, les prédictions LLM_REQUIRED restent à la prédiction
KNN directe et sont signalées avec un badge rouge dans l'UI.

---

## Tests dbt

| Couche | Tests | Résultat |
|--------|-------|---------|
| Sources | not_null sur les 4 tables | PASS |
| Staging | unique/not_null keys, accepted_values project='SPARK' | PASS |
| Intermediate | unique/not_null, accepted_values labels + splits, range tests, FK | PASS |
| Marts ML | unique/not_null, accepted_values issuetype/resolution/split | PASS |
| Marts Analytics | unique sur assignee (workload) et key (links) | PASS |
| **Total** | **55 tests** | **PASS=55 WARN=0 ERROR=0** |

Tests dbt-utils utilisés :
- `dbt_utils.expression_is_true` : range tests sur resolution_days, was_escalated, was_deescalated
- `accepted_values` : validation de toutes les classes consolidées (y compris "Won''t Fix" avec apostrophe correctement échappée)

---

## Containerisation Docker

```
docker-compose up --build
```

| Service | Port | Image de base | Particularité |
|---------|------|---------------|---------------|
| spark-inference | 8501 | python:3.12-slim | Pré-charge BAAI/bge-large-en-v1.5, copie embeddings_noco.npz + embeddings_rich.npz |
| spark-analytics | 8502 | python:3.12-slim | Image légère, pas de modèle ML |

---

## Référence Cortex (compte payant)

Si le compte Snowflake dispose de Cortex, les scripts suivants remplacent `run_ml_pipeline.py` :

| Script | Rôle | Durée estimée |
|--------|------|---------------|
| `cortex/01_train_enriched.sql` | RCA via `COMPLETE('mistral-large2')` | ~20–40 min (MEDIUM WH) |
| `cortex/02_train_embeddings.sql` | Embeddings via `EMBED_TEXT_1024('voyage-multilingual-2')` | ~10–20 min |
| `cortex/03_predict.sql` | Cross-join 4 700 × 41 400 + LLM arbitrage | ~30–90 min (LARGE WH) |
| `cortex/04_evaluate.sql` | Accuracy, F1, matrice de confusion | < 1 min |
