# Spark Issue Triage Platform

**Projet de Fin d'Études (PFE)** — Filière Big Data & IA, UIR Rabat  
**Étudiant :** Anas Elkhabbaz | **Encadrant entreprise :** SQLI Rabat  
**Soutenance :** 24 juin 2026  
**Dépôt :** https://github.com/Anas-elkhabbaz/DataLakeHouse_PFE

---

## Description

Plateforme complète de triage automatique des incidents du projet Apache Spark, construite sur
une architecture en médaillon (Bronze → Argent → Or) hébergée sur Snowflake et orchestrée par dbt.
Le dataset source est le dump public JIRA Apache Spark de Kaggle (mars 2025, ~49 832 tickets SPARK).

Deux chemins de consommation sont exposés :

- **Chemin 1 — Inférence IA** : pipeline V6 Hybrid RCA basé sur des embeddings duaux
  (`BAAI/bge-large-en-v1.5`, 1024d), fusion Reciprocal Rank Fusion (RRF), ré-ranking changelog,
  gate de confiance, et arbitrage LLM optionnel (Ollama ou Anthropic).
- **Chemin 2 — Tableau de bord analytique** : dashboard Streamlit 5 pages explorant les
  volumes mensuels, la dynamique de résolution, la charge des assignataires, les liens entre
  tickets, et les anomalies de cycle de vie.

---

## Résultats obtenus

> Les métriques ci-dessous sont des valeurs représentatives de la configuration V6 complète
> sur le jeu de validation (2022). Les résultats définitifs sur le jeu de test (2023) sont
> produits par `python load/run_ml_pipeline.py --phase final` après verrouillage des hyperparamètres.

| Métrique | Valeur | Seuil cible |
|----------|--------|-------------|
| Accuracy issuetype | — | > 70 % |
| Accuracy résolution | — | > 75 % |
| Macro-F1 issuetype | — | — |
| Macro-F1 résolution | — | — |

> Le macro-F1 est structurellement bas sur ce dataset : Bug + Improvement + Sub-task = ~75 %
> des tickets. Les classes rares (Question, Documentation, Cannot Reproduce) tirent la
> moyenne vers le bas. L'accuracy globale reste au-dessus du seuil cible.

**Jeu de données :**

| Table | Lignes |
|-------|--------|
| RAW.ISSUES | 1 149 321 |
| RAW.COMMENTS | 5 047 714 |
| RAW.CHANGELOG | 9 653 526 |
| RAW.ISSUELINKS | 390 063 |
| Tickets SPARK filtrés | 49 832 |
| MARTS_ML.MART_ML (train + val + test) | 42 083 |
| Tickets d'entraînement (avant 2022) | 38 274 |
| Tickets de validation (2022) | 3 809 |
| Tickets de test (2023) | ~3 700 (hors entraînement) |

**Tests dbt :** PASS=55 WARN=0 ERROR=0

---

## Prérequis

- Python 3.12 (le dbt venv) + Python 3.11+ (scripts de chargement)
- Un compte Snowflake (trial ou payant — voir note ci-dessous)
- dbt-snowflake 1.11+ installé via `uv` dans `dbt_project/.venv/`
- Les 4 fichiers CSV dans `data/` (issues, comments, changelog, issuelinks)
- Docker Desktop (optionnel, pour lancer les apps via docker-compose)

> **Note Snowflake Cortex :** Les fonctions `SNOWFLAKE.CORTEX.COMPLETE` et
> `SNOWFLAKE.CORTEX.EMBED_TEXT_1024` sont bloquées sur les comptes trial. Le pipeline
> d'inférence utilise donc `sentence-transformers` en local (gratuit, ~1,5 GB pour bge-large).
> Les scripts `cortex/*.sql` sont fournis pour référence et fonctionneront sur un compte payant.

---

## Installation rapide (Docker)

La façon la plus simple de lancer les applications :

```bash
git clone https://github.com/Anas-elkhabbaz/DataLakeHouse_PFE.git
cd DataLakeHouse_PFE

# Configurer les identifiants Snowflake
cp .env.example .env
# Éditer .env avec vos valeurs SNOWFLAKE_*
# Optionnel : ANTHROPIC_API_KEY pour l'arbitrage LLM

# Lancer les deux applications
docker-compose up --build
```

- Application d'inférence : http://localhost:8501
- Tableau de bord analytique : http://localhost:8502

La première construction télécharge le modèle `BAAI/bge-large-en-v1.5` (~1,3 GB). Les lancements
suivants démarrent en quelques secondes grâce au cache Docker.

---

## Installation manuelle

```bash
git clone https://github.com/Anas-elkhabbaz/DataLakeHouse_PFE.git
cd DataLakeHouse_PFE

# Installer les dépendances de l'app d'inférence
pip install -r apps/inference/requirements.txt

# Installer les dépendances du tableau de bord
pip install -r apps/analytics/requirements.txt

# Configurer les identifiants
cp .env.example .env
# Éditer .env

# Lancer les apps
streamlit run apps/inference/inference_app.py   # port 8501
streamlit run apps/analytics/analytics_app.py  # port 8502
```

---

## Configuration Snowflake (chargement initial des données)

### 1. Écrire le profil dbt

```bash
python load/write_profiles.py
```

Ce script lit `.env` et écrit `~/.dbt/profiles.yml` en gérant correctement l'encodage Unicode.

### 2. Créer la base de données, les schémas et le warehouse

```bash
python load/run_phase1.py
```

Crée : DATABASE `PFE_SPARK`, 6 schémas (RAW, STAGING, INTERMEDIATE, MARTS_ML,
MARTS_ANALYTICS, CORTEX), warehouse `PFE_WH`, stage interne `RAW.CSV_STAGE`.

### 3. Inspecter les en-têtes CSV

```bash
python load/inspect_headers.py
```

Affiche les positions exactes des colonnes dans chaque CSV. Vérifier que le mapping
dans `load/04_copy_into_raw.sql` correspond avant de passer à l'étape suivante.

### 4. Charger les CSV vers le stage puis dans les tables brutes

```bash
python load/03_put_files.py    # PUT vers @RAW.CSV_STAGE (~30 min selon la connexion)
python load/run_phase4.py      # COPY INTO + vérification des comptes
```

### 5. Pipeline dbt

```bash
cd dbt_project
.venv\Scripts\dbt deps         # Installer dbt-utils
.venv\Scripts\dbt seed         # Tables de mapping labels
.venv\Scripts\dbt run          # 13 modèles
.venv\Scripts\dbt test         # 55 tests (attendu : PASS=55, WARN=0, ERROR=0)
```

### 6. Pipeline ML (embeddings + prédictions + évaluation)

```bash
# Phase d'ajustement (jeu de validation 2022)
python load/run_ml_pipeline.py --phase tune

# Phase finale — UNE SEULE FOIS après verrouillage des hyperparamètres
python load/run_ml_pipeline.py --phase final
```

Génère les embeddings duaux (`results/embeddings_noco.npz` + `results/embeddings_rich.npz`,
~150 MB au total), fait les prédictions sur le jeu sélectionné, évalue les performances
avec intervalles de confiance bootstrap (n=500), et sauvegarde les résultats dans `results/`
et dans `CORTEX.MART_PREDICTIONS` sur Snowflake.

### 7. Expériences d'ablation (optionnel)

```bash
python experiments/01_k_sweep.py              # Sweep k ∈ {5,10,15,20,30,50}
python experiments/02_boost_ablation.py       # Leave-one-out des boosts
python experiments/03_architecture_ablation.py # 6 configurations comparées
python experiments/04_keyword_rerank.py       # BM25 vs embedding vs hybride
```

Résultats dans `results/ablations/`.

---

## Configuration optionnelle — LLM (Anthropic ou Ollama)

### Anthropic (cloud)

```
ANTHROPIC_API_KEY=sk-ant-...
```

Obtenir une clé sur [console.anthropic.com](https://console.anthropic.com).
Le modèle utilisé est `claude-haiku-4-5`. Sans cette clé, le pipeline tente Ollama.

### Ollama (local, gratuit)

```bash
ollama pull mistral:7b   # ~4 GB, une seule fois
ollama serve             # lancer le serveur local
```

Si ni Anthropic ni Ollama n'est disponible, le pipeline fonctionne en mode DIRECT
(sans arbitrage LLM) — les prédictions à faible confiance sont signalées en rouge dans l'UI.

---

## Limitations

- **Temps de calcul des embeddings** : BAAI/bge-large-en-v1.5 sur CPU prend ~30–60 min
  par corpus (NOCO + RICH = ~120 min total). GPU recommandé pour la production.
- **Jeu de test unique** : le jeu de test (2023) ne doit être utilisé qu'une seule fois
  (`--phase final`) après avoir figé tous les hyperparamètres sur la validation (2022).
- **Déséquilibre des classes** : le macro-F1 bas est structurel et attendu. Bug + Improvement
  représentent 75 % du corpus. La plateforme cible l'accuracy globale, pas le macro-F1.
- **Compte Snowflake** : les fonctions Cortex AI (COMPLETE, EMBED_TEXT_1024) requièrent
  un compte payant. Le pipeline Python est fonctionnel sans compte payant.

---

## Structure du projet

```
DataLakeHouse_PFE/
├── .env.example                 # Template de configuration
├── .gitignore
├── .dockerignore
├── docker-compose.yml           # Lance inference + analytics
├── pyproject.toml
├── README.md
│
├── data/                        # CSVs source (non versionnés, ~8 GB total)
│   ├── issues.csv
│   ├── comments.csv
│   ├── changelog.csv
│   └── issuelinks.csv
│
├── load/                        # Scripts de chargement Bronze + ML
│   ├── run_phase1.py            # Crée la base Snowflake
│   ├── inspect_headers.py       # Vérifie les positions CSV
│   ├── 03_put_files.py          # PUT vers le stage
│   ├── run_phase4.py            # COPY INTO + vérification
│   ├── run_ml_pipeline.py       # V6: dual embeddings + RRF + prédictions
│   ├── retrieval.py             # Module partagé RRF + changelog re-rank
│   ├── write_profiles.py        # Génère ~/.dbt/profiles.yml
│   └── 04_copy_into_raw.sql     # DDL tables brutes + mapping $N
│
├── dbt_project/                 # Transformations Silver + Or
│   ├── models/
│   │   ├── staging/             # 4 vues (1:1 avec les sources)
│   │   ├── intermediate/        # 4 tables (NLP, features, split)
│   │   └── marts/
│   │       ├── ml/              # MART_ML (42 083 lignes, 3 splits)
│   │       └── analytics/       # MART_ANALYTICS_OPS + WORKLOAD + LINKS
│   ├── seeds/                   # issuetype_mapping.csv, resolution_mapping.csv
│   ├── macros/                  # clean_jira_text, generate_schema_name
│   └── .venv/                   # Python 3.12 venv pour dbt-snowflake
│
├── cortex/                      # Pipeline Python LLM + scripts Snowflake Cortex (référence)
│   ├── __init__.py
│   ├── llm_client.py            # Anthropic / Ollama adapter
│   ├── arbitration.py           # Arbitrage LLM contraint
│   ├── fix_summary.py           # Résumé fix lazy, cache JSON
│   ├── 01_train_enriched.sql    # RCA via CORTEX.COMPLETE (compte payant)
│   ├── 02_train_embeddings.sql  # Embeddings via CORTEX.EMBED_TEXT_1024
│   ├── 03_predict.sql           # KNN + arbitrage LLM
│   └── 04_evaluate.sql          # Accuracy, F1, matrice de confusion
│
├── apps/
│   ├── inference/               # Application de triage (Streamlit)
│   │   ├── Dockerfile
│   │   ├── inference_app.py     # V6: dual embed, routing badge, fix_summary
│   │   └── requirements.txt
│   └── analytics/               # Tableau de bord 5 pages (Streamlit)
│       ├── Dockerfile
│       ├── analytics_app.py
│       ├── pages/
│       │   ├── 1_overview.py
│       │   ├── 2_resolution_dynamics.py
│       │   ├── 3_workload.py
│       │   ├── 4_relationships.py
│       │   └── 5_anomalies.py   # Nouveauté V6
│       └── requirements.txt
│
├── experiments/                 # Expériences d'ablation
│   ├── 01_k_sweep.py
│   ├── 02_boost_ablation.py
│   ├── 03_architecture_ablation.py
│   └── 04_keyword_rerank.py
│
├── results/                     # Artefacts de l'évaluation
│   ├── embeddings_noco.npz      # Embeddings NOCO (BAAI/bge-large, 1024d)
│   ├── embeddings_rich.npz      # Embeddings RICH (avec commentaires)
│   ├── embeddings_meta.json     # Métadonnées + SHA256 des colonnes source
│   ├── fix_summaries.json       # Cache des résumés fix générés par LLM
│   ├── ablations/               # Résultats des expériences
│   └── ...                      # Prédictions et métriques (non versionnées)
│
└── docs/
    ├── architecture.md
    ├── data_dictionary.md
    └── decisions_log.md
```

---

## Documentation

| Document | Contenu |
|----------|---------|
| [docs/architecture.md](docs/architecture.md) | Schéma V6 Hybrid RCA et description des couches |
| [docs/data_dictionary.md](docs/data_dictionary.md) | Description de chaque colonne des marts Gold |
| [docs/decisions_log.md](docs/decisions_log.md) | Choix architecturaux figés et leur justification |
