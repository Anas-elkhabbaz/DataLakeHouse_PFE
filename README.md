# Plateforme de Triage des Incidents Apache Spark

**Projet de Fin d'Études (PFE)** — Filière Big Data & IA, UIR Rabat  
**Étudiant :** Anas Elkhabbaz | **Encadrant entreprise :** SQLI Rabat  
**Soutenance :** 24 juin 2026

---

## Description

Cette plateforme ingère le dataset public Apache Spark JIRA (Kaggle, mars 2025) dans
Snowflake selon une architecture en médaillon (Bronze → Argent → Or), puis expose deux
consommateurs :

- **Chemin 1 — Inférence IA** : pipeline V6 Hybrid RCA (Snowflake Cortex) qui prédit
  le type d'incident, la résolution probable et génère un résumé de correctif.
- **Chemin 2 — Tableau de bord analytique** : dashboard Streamlit multi-pages explorant
  les patterns de bugs, la dynamique de résolution et la charge des assignataires.

---

## Prérequis

- Python 3.11+
- Un compte Snowflake (Standard ou Enterprise avec Cortex activé)
- dbt Core 1.8+
- Les 4 fichiers CSV dans `data/` (issues, comments, changelog, issuelinks)

---

## Installation

```bash
# 1. Cloner le dépôt
git clone <url-du-depot> pfe-spark-triage
cd pfe-spark-triage

# 2. Créer l'environnement virtuel
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux/Mac

# 3. Installer les dépendances
pip install -e .

# 4. Configurer les variables d'environnement
copy .env.example .env
# Remplir .env avec vos identifiants Snowflake
```

---

## Configuration Snowflake

### Étape 1 — Configurer le profil dbt

Copier `dbt_project/profiles.yml.example` vers `~/.dbt/profiles.yml` et remplir les valeurs :

```bash
copy dbt_project\profiles.yml.example %USERPROFILE%\.dbt\profiles.yml
```

### Étape 2 — Créer la base de données et le stage

Exécuter dans un worksheet Snowflake (dans l'ordre) :

```sql
-- 1. Base de données, schémas, warehouse
-- Fichier : load/01_create_database.sql

-- 2. Stage interne pour les CSV
-- Fichier : load/02_create_stage.sql
```

### Étape 3 — Charger les CSV

```bash
# Inspecte les en-têtes CSV et charge les fichiers vers le stage Snowflake
python load/03_put_files.py
```

> **Important :** Vérifier que les positions de colonnes affichées correspondent
> au mapping dans `load/04_copy_into_raw.sql` avant de l'exécuter.

### Étape 4 — COPY INTO les tables brutes

```sql
-- Fichier : load/04_copy_into_raw.sql
-- Puis vérifier :
-- Fichier : load/05_verify_counts.sql
```

---

## Pipeline dbt (couche Argent et Or)

```bash
cd dbt_project

# Vérifier la connexion
dbt debug

# Installer les packages
dbt deps

# Charger les seeds (tables de mapping)
dbt seed

# Exécuter tous les modèles
dbt run

# Lancer les tests
dbt test

# Générer la documentation
dbt docs generate && dbt docs serve
```

---

## Pipeline V6 Hybrid RCA (Cortex)

Exécuter les scripts SQL dans un worksheet Snowflake **avec un warehouse MEDIUM** :

```sql
-- 1. Générer les représentations enrichies (RCA summary via Cortex)
--    Fichier : cortex/01_train_enriched.sql  (~41 000 appels LLM, ~20 min)

-- 2. Calculer les embeddings duaux
--    Fichier : cortex/02_train_embeddings.sql  (~82 000 appels embed)

-- 3. Prédire sur le jeu de validation
--    Fichier : cortex/03_predict.sql  (194M comparaisons cosinus, warehouse LARGE recommandé)

-- 4. Évaluer les performances
--    Fichier : cortex/04_evaluate.sql
```

---

## Lancer les applications Streamlit

### Application d'inférence (Chemin 1)

```bash
streamlit run apps/inference/inference_app.py
```

Accessible sur : http://localhost:8501

### Tableau de bord analytique (Chemin 2)

```bash
streamlit run apps/analytics/analytics_app.py
```

Accessible sur : http://localhost:8502

---

## Structure du projet

```
pfe-spark-triage/
├── data/                    # CSVs locaux (non versionnés)
├── load/                    # Scripts de chargement Bronze
├── dbt_project/             # Transformations Silver + Or
│   ├── models/
│   │   ├── staging/         # Vues 1:1 avec les sources
│   │   ├── intermediate/    # Logique métier + nettoyage NLP
│   │   └── marts/           # Tables Gold (ML + Analytics)
│   ├── seeds/               # Tables de mapping labels
│   └── macros/              # Macros dbt réutilisables
├── cortex/                  # Pipeline V6 Hybrid RCA (SQL brut)
├── apps/
│   ├── inference/           # UI de prédiction (Streamlit)
│   └── analytics/           # Tableau de bord (Streamlit multi-pages)
└── docs/                    # Documentation en français
```

---

## Architecture

Voir [docs/architecture.md](docs/architecture.md) pour le schéma détaillé.

## Dictionnaire des données

Voir [docs/data_dictionary.md](docs/data_dictionary.md) pour la description de chaque colonne.

## Décisions de conception

Voir [docs/decisions_log.md](docs/decisions_log.md) pour les choix architecturaux figés.
