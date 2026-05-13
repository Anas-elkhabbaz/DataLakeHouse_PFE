# Dictionnaire des données — PFE Spark Triage

---

## MARTS_ML.MART_ML

Table Gold de référence pour le pipeline d'inférence.

**Granularité :** un ticket Apache Spark JIRA par ligne  
**Lignes réelles :** 42 083 (train + validation + test)  
**Filtre :** `split IN ('train', 'validation', 'test')` — les tickets 2024+ (excluded) sont absents

### Identification et partitionnement

| Colonne | Type | Description |
|---------|------|-------------|
| `key` | VARCHAR | Clé unique du ticket JIRA (ex. SPARK-12345). Clé primaire. |
| `created_at` | TIMESTAMP_TZ | Date et heure de création du ticket. |
| `split` | VARCHAR | Partition temporelle : `train` (<2022), `validation` (2022), `test` (2023). |

### Cibles de classification

| Colonne | Type | Classes | Fréquence approx. |
|---------|------|---------|-------------------|
| `issuetype` | VARCHAR | Bug, Improvement, Sub-task, New Feature, Task, Test, Documentation, Question, Other | Bug 45%, Improvement 30%, Sub-task 15%, autres <5% chacun |
| `resolution` | VARCHAR | Fixed, Won't Fix, Not A Problem, Incomplete, Duplicate, Invalid, Cannot Reproduce | Fixed ~62%, Won't Fix ~16%, autres <10% chacun |

### Texte nettoyé

| Colonne | Type | Description |
|---------|------|-------------|
| `summary_clean` | VARCHAR | Résumé après nettoyage NLP 6 étapes (HTML, JIRA markup, URLs, espaces). |
| `description_clean` | VARCHAR | Description complète nettoyée. Chaîne vide si absente (~2,4 % des tickets). |
| `comments_concat` | VARCHAR | Commentaires agrégés : first-5 chronologiques + last-3, chaque snippet tronqué à 400 chars, séparateur ` || `. |

### Représentations textuelles pour l'inférence (dual embedding)

| Colonne | Type | Description |
|---------|------|-------------|
| `text_noco` | VARCHAR | Représentation structurée **sans commentaires et sans labels** (format TICKET/PRI/STATUS/DESC), tronquée à 2 000 caractères. Utilisée pour l'embedding NOCO et le corpus BM25. |
| `text_rich` | VARCHAR | Représentation structurée **avec commentaires** (format TICKET/PRIORITY/STATUS/N_COMMENTS/DESCRIPTION/DISCUSSION), tronquée à 6 000 caractères. Utilisée pour l'embedding RICH. |

Format exact de `text_noco` (sans leakage de label) :
```
TICKET: {summary_clean}
PRI: {priority}
STATUS: {status}
DESC: {description_clean[:1500]}
```

Format exact de `text_rich` :
```
TICKET: {summary_clean}
PRIORITY: {priority}
STATUS: {status}
N_COMMENTS: {n_comments}
DESCRIPTION: {description_clean[:2000]}
DISCUSSION: {all_comments[:2500]}
```

### Métadonnées pour le boost de récupération

| Colonne | Type | Description | Boost KNN |
|---------|------|-------------|-----------|
| `priority` | VARCHAR | Blocker, Critical, Major, Minor, Trivial. | +0,10 si égal au ticket requête |
| `status` | VARCHAR | Open, In Progress, Resolved, Closed, Reopened. | +0,08 si égal |
| `reporter` | VARCHAR | Identifiant de l'auteur du ticket. | +0,05 si égal |
| `assignee` | VARCHAR | Identifiant de l'assignataire. `Unassigned` si non renseigné (~34 %). | — |

### Features changelog (contribution originale du PFE)

Ces features sont absentes des travaux antérieurs sur ce dataset et constituent
la contribution technique distinctive du projet. Elles servent au ré-ranking des candidats
RRF (score L2 inverse dans l'espace standardisé).

| Colonne | Type | Description |
|---------|------|-------------|
| `n_total_changes` | NUMBER | Nombre total de changements de champs enregistrés dans le changelog. |
| `n_status_changes` | NUMBER | Nombre de transitions de statut (Open → In Progress → Resolved…). |
| `n_priority_changes` | NUMBER | Nombre de changements de priorité. |
| `n_assignee_changes` | NUMBER | Nombre de réassignations. Indicateur de complexité. |
| `n_resolution_changes` | NUMBER | Nombre de changements de résolution (réouvertures incluses). |
| `was_escalated` | NUMBER (0/1) | 1 si la priorité a augmenté au moins une fois (ex. Minor → Major). |
| `was_deescalated` | NUMBER (0/1) | 1 si la priorité a diminué au moins une fois (ex. Major → Minor). |
| `n_people_involved` | NUMBER | Nombre d'auteurs distincts dans le changelog. |
| `first_assignee` | VARCHAR | Premier assignataire selon le changelog. NULL si aucun événement. |

### Features de liens entre tickets

| Colonne | Type | Description |
|---------|------|-------------|
| `n_links_total` | NUMBER | Nombre total de liens sortants. |
| `n_duplicates` | NUMBER | Liens de type "Duplicate". |
| `n_blocks` | NUMBER | Tickets que ce ticket bloque. |
| `n_blocked_by` | NUMBER | Tickets qui bloquent ce ticket. |
| `n_relates` | NUMBER | Liens de type "Relates". |

### Features de commentaires

| Colonne | Type | Description |
|---------|------|-------------|
| `n_comments` | NUMBER | Nombre de commentaires (corps ≥ 10 caractères après nettoyage). |
| `n_commenters` | NUMBER | Nombre d'auteurs distincts ayant commenté. |

### Métriques de timing et de longueur

| Colonne | Type | Description |
|---------|------|-------------|
| `resolution_days` | NUMBER | Jours entre création et résolution, plafonné à 5 000. 0 si non résolu. |
| `summary_length` | NUMBER | Longueur en caractères du résumé nettoyé. |
| `description_length` | NUMBER | Longueur en caractères de la description nettoyée. |

---

## CORTEX.MART_PREDICTIONS

Résultats de l'évaluation du pipeline sur le jeu sélectionné (validation ou test).

**Lignes :** ~3 809 (validation) ou ~3 700 (test)  
**Peuplé par :** `python load/run_ml_pipeline.py --phase tune|final`

| Colonne | Type | Description |
|---------|------|-------------|
| `key` | VARCHAR | Clé du ticket (SPARK-NNNNN). |
| `true_issuetype` | VARCHAR | Label réel issuetype (ground truth). |
| `true_resolution` | VARCHAR | Label réel résolution (ground truth). |
| `pred_issuetype` | VARCHAR | Issuetype prédit par le pipeline V6. |
| `pred_resolution` | VARCHAR | Résolution prédite. |
| `conf_issuetype` | FLOAT | l0_conf du vote issuetype (0–1). |
| `conf_resolution` | FLOAT | l0_conf du vote résolution (0–1). |
| `routing_issuetype` | VARCHAR | "DIRECT" ou "LLM_REQUIRED" pour l'issuetype. |
| `margin_issuetype` | FLOAT | Margin du vote issuetype. |
| `routing_resolution` | VARCHAR | "DIRECT" ou "LLM_REQUIRED" pour la résolution. |
| `margin_resolution` | FLOAT | Margin du vote résolution. |
| `fix_summary` | VARCHAR | Résumé de correction généré par LLM (vide si LLM non disponible). |

---

## MARTS_ANALYTICS.MART_ANALYTICS_OPS

Agrégats pour la page "Vue d'ensemble" et "Dynamique de résolution" du tableau de bord.

**Granularité :** mois × issuetype  
**Lignes :** 1 352

| Colonne | Type | Description |
|---------|------|-------------|
| `month` | DATE | Premier jour du mois (DATE_TRUNC). |
| `issuetype` | VARCHAR | Type d'incident. |
| `total_issues` | NUMBER | Nombre de tickets créés ce mois pour ce type. |
| `total_resolved` | NUMBER | Tickets ayant une résolution non-NULL. |
| `median_resolution_days` | FLOAT | Médiane des délais de résolution (tickets résolus uniquement). |
| `avg_resolution_days` | FLOAT | Moyenne des délais de résolution. |
| `pct_fixed` | FLOAT | % de tickets résolus en "Fixed". |
| `pct_wontfix` | FLOAT | % de tickets résolus en "Won't Fix". |
| `pct_duplicate` | FLOAT | % de tickets marqués "Duplicate". |
| `pct_cannot_reproduce` | FLOAT | % de tickets "Cannot Reproduce". |
| `avg_summary_length` | FLOAT | Longueur moyenne du résumé (caractères). |
| `avg_description_length` | FLOAT | Longueur moyenne de la description. |
| `avg_n_comments` | FLOAT | Nombre moyen de commentaires par ticket. |

---

## MARTS_ANALYTICS.MART_ANALYTICS_WORKLOAD

Métriques par assignataire pour la page "Charge de travail".  
Remplace l'ancien `mart_analytics_deps` (supprimé).

**Granularité :** un assignataire par ligne  
**Source :** `int_issues_cleaned`  
**Filtre :** assignee IS NOT NULL AND assignee != 'Unassigned'

| Colonne | Type | Description |
|---------|------|-------------|
| `assignee` | VARCHAR | Identifiant de l'assignataire. Clé primaire. |
| `n_assigned` | NUMBER | Nombre total de tickets assignés. |
| `n_fixed` | NUMBER | Nombre de tickets résolus en "Fixed". |
| `avg_resolution_days` | FLOAT | Délai moyen de résolution (tickets résolus uniquement). |
| `top_issuetype` | VARCHAR | Type d'incident le plus fréquent pour cet assignataire (MODE). |
| `n_distinct_issuetypes` | NUMBER | Nombre de types distincts gérés. |

---

## MARTS_ANALYTICS.MART_ANALYTICS_LINKS

Métriques par ticket pour les liens entre tickets, page "Relations".  
Remplace l'ancien `mart_analytics_deps` (supprimé).

**Granularité :** un ticket par ligne  
**Source :** `int_issuelinks_features`  
**Filtre :** `n_links_total > 0`

| Colonne | Type | Description |
|---------|------|-------------|
| `key` | VARCHAR | Clé du ticket JIRA. Clé primaire. |
| `n_links_total` | NUMBER | Nombre total de liens (toutes directions). |
| `n_duplicates` | NUMBER | Liens de type "Duplicate". |
| `n_blocks` | NUMBER | Tickets bloqués par ce ticket. |
| `n_blocked_by` | NUMBER | Tickets qui bloquent ce ticket. |
| `n_relates` | NUMBER | Liens de type "Relates". |
| `n_outgoing_plus_incoming` | NUMBER | n_duplicates + n_blocks + n_blocked_by (liens directs). |

---

## Fichiers locaux (non dans Snowflake)

### results/embeddings_noco.npz

Cache NumPy des embeddings d'entraînement sur le texte sans commentaires.

| Propriété | Valeur |
|-----------|--------|
| Clé dans le fichier | `train_emb` |
| Shape | (~38 274, 1024) |
| Dtype | float32 |
| Normalisation | L2 (vecteurs unitaires) |
| Modèle source | BAAI/bge-large-en-v1.5 |

### results/embeddings_rich.npz

Cache NumPy des embeddings d'entraînement sur le texte avec commentaires.

| Propriété | Valeur |
|-----------|--------|
| Clé dans le fichier | `train_emb` |
| Shape | (~38 274, 1024) |
| Dtype | float32 |
| Normalisation | L2 (vecteurs unitaires) |
| Modèle source | BAAI/bge-large-en-v1.5 |

### results/embeddings_meta.json

Métadonnées des caches d'embeddings pour validation de cohérence.

| Champ | Description |
|-------|-------------|
| `model` | Nom du modèle d'embedding |
| `dim` | Dimension des vecteurs |
| `n_train` | Nombre de tickets d'entraînement |
| `sha256_noco` | SHA256 de la colonne text_noco du corpus d'entraînement |
| `sha256_rich` | SHA256 de la colonne text_rich du corpus d'entraînement |
| `computed_at` | Horodatage ISO 8601 du calcul |

### results/fix_summaries.json

Cache des résumés de correction générés par LLM. Clés : clés JIRA (SPARK-NNNNN).
Chaque entrée : `{"summary": "...", "generated_at": "..."}`.

### Seeds dbt

| Fichier | Lignes | Description |
|---------|--------|-------------|
| `dbt_project/seeds/issuetype_mapping.csv` | 22 | raw_value → 9 classes consolidées |
| `dbt_project/seeds/resolution_mapping.csv` | 15 | raw_value → 7 classes consolidées |
