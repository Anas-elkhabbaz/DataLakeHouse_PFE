# Architecture de la plateforme — PFE Spark Triage

## Vue d'ensemble

La plateforme adopte une **architecture en médaillon** (Bronze → Argent → Or) hébergée sur
Snowflake, orchestrée par dbt-snowflake, et exposée via deux applications Streamlit conteneurisées
avec Docker. Le pipeline d'inférence utilise des embeddings de phrases locaux (sentence-transformers)
en raison des restrictions du compte Snowflake trial — les scripts Cortex SQL sont fournis pour
déploiement sur un compte payant.

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
│  INT_ISSUES_CLEANED  (45 043) — NLP 6 étapes, mapping labels, split temporel    │
│  INT_COMMENTS_AGGREGATED (41 986) — LISTAGG, nettoyage, métriques               │
│  INT_CHANGELOG_FEATURES  (29 937) — escalade, transitions, n_people             │
│  INT_ISSUELINKS_FEATURES (11 179) — doublons, blocages, relations               │
│       │                                                                           │
│       ▼  dbt run — marts/ (tables)                                                │
│  OR                                                                               │
│  MARTS_ML.MART_ML (42 083)  ──────────────────────────────────────┐             │
│  MARTS_ANALYTICS.MART_ANALYTICS_OPS (1 352 lignes mois×type)      │             │
│  MARTS_ANALYTICS.MART_ANALYTICS_DEPS (13 968 lignes assignataire)  │             │
└────────────────────────────────────────────────────────────────────┼─────────────┘
        │                                    │                       │
        ▼ Chemin 2                           ▼ Chemin 1              │
  Dashboard analytique               Pipeline ML (Python)            │
        │                            python load/run_ml_pipeline.py  │
        │                                    │                       │
        │              ┌─────────────────────┘                       │
        │              │  1. Fetch MART_ML depuis Snowflake           │
        │              │  2. Embed text_noco                          │
        │              │     → all-MiniLM-L6-v2 (384d)               │
        │              │     → results/embeddings_cache.npz (57 MB)  │
        │              │  3. Cosine KNN (k=15) + metadata boost       │
        │              │  4. Vote pondéré → prédictions               │
        │              │  5. Évaluation + export résultats            │
        │              │  6. Upload → CORTEX.MART_PREDICTIONS (3 809) │
        │              │                                              │
        ▼              ▼                                              │
┌─────────────────┐  ┌──────────────────────────────────────────┐   │
│  analytics_app  │  │  inference_app                            │   │
│  5 pages        │  │  KNN temps réel sur 1 ticket             │   │
│  plotly.express │  │  → issuetype + résolution + analyse      │   │
│  port 8502      │  │  → optionnel : LLM via Anthropic API     │   │
└─────────────────┘  │  port 8501                               │   │
        │             └──────────────────────────────────────────┘   │
        │                           │                                 │
        ▼                           ▼                                 │
┌──────────────────────────────────────────────────────────────────┐ │
│  Docker                                                           │ │
│  docker-compose up --build                                        │ │
│  spark-analytics (python:3.12-slim, port 8502)                   │ │
│  spark-inference (python:3.12-slim + modèle pré-chargé, 8501)   │ │
└──────────────────────────────────────────────────────────────────┘ │
                                                                      │
              [cortex/*.sql — pour compte Snowflake payant] ──────────┘
```

---

## Couche Bronze (RAW)

**Rôle :** Ingestion fidèle des CSV Kaggle. Zéro transformation métier.

- Tables entièrement en VARCHAR pour absorber toute variation de format CSV
- Chargement via `COPY INTO` avec mapping positionnel `$N` documenté dans `load/04_copy_into_raw.sql`
- Script `inspect_headers.py` affiche les en-têtes réels pour vérifier le mapping avant chargement
- `run_phase4.py` exécute le COPY INTO et vérifie les comptes attendus

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
- `QUALIFY ROW_NUMBER() OVER (PARTITION BY key ORDER BY id) = 1` pour dédupliquer 4 clés en double dans la source

### Intermediate — tables dbt

Logique métier et feature engineering :

**INT_ISSUES_CLEANED (45 043 lignes)**
- Nettoyage NLP en 6 étapes via macro `clean_jira_text` :
  HTML, blocs `{code}`, blocs `{noformat}`, mentions `[~user]`, URLs, espaces multiples
- Consolidation des labels : LEFT JOIN avec `seeds/issuetype_mapping.csv` (9 classes)
  et `seeds/resolution_mapping.csv` (7 classes) — les valeurs absentes du seed donnent NULL → filtrées
- Split temporel : `train` (<2023-01-01) / `validation` (2023) / `excluded` (≥2024)
- `resolution_days` DATEDIFF plafonné à 5000

**INT_COMMENTS_AGGREGATED (41 986 lignes)**
- Nettoyage du corps de chaque commentaire (même macro NLP)
- Filtre : commentaires de longueur < 10 caractères supprimés
- LISTAGG par ticket (ORDER BY created_at), tronqué à 3 000 caractères

**INT_CHANGELOG_FEATURES (29 937 lignes)**
- Features d'escalade : `was_escalated` (1 si priorité a augmenté)
- Compteurs : n_total_changes, n_status_changes, n_priority_changes, n_assignee_changes
- `n_people_involved` : nombre d'auteurs distincts dans le changelog

**INT_ISSUELINKS_FEATURES (11 179 lignes)**
- Compteurs par type de lien : n_links_total, n_duplicates, n_blocks, n_blocked_by, n_relates

---

## Couche Or (MARTS)

### MARTS_ML.MART_ML — 42 083 lignes

Table de contrat pour le pipeline d'inférence. Jointure large des 4 tables intermédiaires.
Filtrée sur `split IN ('train', 'validation')` — les tickets 2024+ sont exclus.

| Partition | Lignes |
|-----------|--------|
| train | 38 274 |
| validation | 3 809 |
| Total | 42 083 |

Colonne clé : `text_noco` — représentation structurée du ticket sans commentaires :
```
TICKET: {summary}
TYPE: {issuetype} | PRI: {priority}
STATUS: {status}
DESC: {description[:800]}
```
Tronquée à 2000 caractères. Sert de base à l'embedding de récupération.

### MARTS_ANALYTICS

- **MART_ANALYTICS_OPS** (1 352 lignes) : agrégats mensuels × issuetype
  (total_issues, total_resolved, median_resolution_days, pct_fixed, pct_wontfix, ...)
- **MART_ANALYTICS_DEPS** (13 968 lignes) : métriques par assignataire + agrégats de liens

---

## Pipeline d'inférence — Python KNN

Le pipeline Snowflake Cortex (`cortex/*.sql`) est fourni comme implémentation de référence
mais requiert un compte Snowflake payant. L'implémentation effective utilise Python :

### Modèle d'embedding

| Propriété | Valeur |
|-----------|--------|
| Modèle | `all-MiniLM-L6-v2` (sentence-transformers) |
| Dimensions | 384 |
| Encodage | L2-normalisé → similarité cosinus = produit scalaire |
| Cache | `results/embeddings_cache.npz` (57 MB, versionné dans git) |

### Algorithme de prédiction

1. Embed le ticket d'entrée (text_noco, LEFT 2000 chars)
2. Produit scalaire contre les 38 274 embeddings d'entraînement
3. Boost de métadonnées : +0,10 si même priorité, +0,08 si même statut, +0,05 si même reporter
4. Garder les 15 plus proches voisins (k=15)
5. Vote pondéré par score de similarité → prédiction + confiance

### Résultats sur le jeu de validation (3 809 tickets)

| Cible | Accuracy | Macro-F1 |
|-------|----------|----------|
| issuetype | **75,32 %** | 33,77 % |
| résolution | **91,52 %** | 16,40 % |

F1 par classe (issuetype) :

| Classe | F1 |
|--------|----|
| Bug | 0,703 |
| Improvement | 0,769 |
| Sub-task | 0,885 |
| New Feature | 0,190 |
| Documentation | 0,200 |
| Test | 0,208 |
| Task | 0,051 |
| Other | 0,035 |
| Question | 0,000 |

> Le macro-F1 bas reflète le déséquilibre des classes : Bug + Improvement + Sub-task
> représentent ~75 % du dataset. Les classes rares ont peu de représentants en validation.

---

## Tests dbt

| Couche | Tests | Résultat |
|--------|-------|---------|
| Sources | not_null sur les 4 tables | PASS |
| Staging | unique/not_null keys, accepted_values project='SPARK' | PASS |
| Intermediate | unique/not_null keys, accepted_values labels, relationships FK | PASS + 2 WARN |
| Marts | unique/not_null keys, accepted_values split/issuetype | PASS |
| **Total** | **46 tests** | **PASS=44 WARN=2 ERROR=0** |

Les 2 WARN concernent les valeurs "Won't Fix" : l'apostrophe ne peut pas être placée dans
un test `accepted_values` SQL sans erreur de syntaxe. Le label est néanmoins présent et
correctement géré dans le pipeline.

---

## Containerisation Docker

```
docker-compose up --build
```

| Service | Port | Image de base | Taille approx. |
|---------|------|---------------|----------------|
| spark-inference | 8501 | python:3.12-slim | ~1,1 GB |
| spark-analytics | 8502 | python:3.12-slim | ~400 MB |

L'image d'inférence pré-charge le modèle `all-MiniLM-L6-v2` et copie
`results/embeddings_cache.npz` — le démarrage du container est instantané.

---

## Référence Cortex (compte payant)

Si le compte Snowflake dispose de Cortex, les scripts suivants remplacent `run_ml_pipeline.py` :

| Script | Rôle | Durée estimée |
|--------|------|---------------|
| `cortex/01_train_enriched.sql` | RCA via `COMPLETE('mistral-large2')` | ~20–40 min (MEDIUM WH) |
| `cortex/02_train_embeddings.sql` | Embeddings via `EMBED_TEXT_1024('voyage-multilingual-2')` | ~10–20 min |
| `cortex/03_predict.sql` | Cross-join 4 700 × 41 400 + LLM arbitrage | ~30–90 min (LARGE WH) |
| `cortex/04_evaluate.sql` | Accuracy, F1, matrice de confusion | < 1 min |
