# Dictionnaire des données — PFE Spark Triage

---

## MARTS_ML.MART_ML

Table Gold de référence pour le pipeline d'inférence.

**Granularité :** un ticket Apache Spark JIRA par ligne  
**Lignes réelles :** 42 083 (38 274 train + 3 809 validation)  
**Filtre :** `split IN ('train', 'validation')` — les tickets 2024+ (excluded) sont absents

### Identification et partitionnement

| Colonne | Type | Description |
|---------|------|-------------|
| `key` | VARCHAR | Clé unique du ticket JIRA (ex. SPARK-12345). Clé primaire. |
| `created_at` | TIMESTAMP_TZ | Date et heure de création du ticket. |
| `split` | VARCHAR | Partition temporelle : `train` (avant 2023) ou `validation` (2023). |

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
| `comments_concat` | VARCHAR | Commentaires agrégés chronologiquement, tronqués à 3 000 caractères. Chaîne vide si aucun commentaire. |

### Représentation textuelles pour l'inférence

| Colonne | Type | Description |
|---------|------|-------------|
| `text_noco` | VARCHAR | Représentation structurée sans commentaires (format TICKET/TYPE/STATUS/DESC), tronquée à 2 000 caractères. Utilisée comme entrée de l'embedding de récupération. |

Format exact de `text_noco` :
```
TICKET: {summary_clean}
TYPE: {issuetype} | PRI: {priority}
STATUS: {status}
DESC: {description_clean[:800]}
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
la contribution technique distinctive du projet.

| Colonne | Type | Description |
|---------|------|-------------|
| `n_total_changes` | NUMBER | Nombre total de changements de champs enregistrés dans le changelog. |
| `n_status_changes` | NUMBER | Nombre de transitions de statut (Open → In Progress → Resolved…). |
| `n_priority_changes` | NUMBER | Nombre de changements de priorité. |
| `n_assignee_changes` | NUMBER | Nombre de réassignations. Indicateur de complexité. |
| `n_resolution_changes` | NUMBER | Nombre de changements de résolution (réouvertures incluses). |
| `was_escalated` | NUMBER (0/1) | 1 si la priorité a augmenté au moins une fois (ex. Minor → Major). |
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

Résultats de l'évaluation du pipeline sur le jeu de validation.

**Lignes :** 3 809 (un ticket de validation par ligne)  
**Peuplé par :** `python load/run_ml_pipeline.py`

| Colonne | Type | Description |
|---------|------|-------------|
| `key` | VARCHAR | Clé du ticket de validation (SPARK-NNNNN). |
| `true_issuetype` | VARCHAR | Label réel issuetype (ground truth). |
| `true_resolution` | VARCHAR | Label réel résolution (ground truth). |
| `pred_issuetype` | VARCHAR | Issuetype prédit par le pipeline KNN. |
| `pred_resolution` | VARCHAR | Résolution prédite. |
| `conf_issuetype` | FLOAT | Confiance du vote pondéré pour issuetype (0–1). |
| `conf_resolution` | FLOAT | Confiance du vote pondéré pour résolution (0–1). |
| `method` | VARCHAR | Toujours `DIRECT` dans l'implémentation Python (vote pondéré). |
| `fix_summary` | VARCHAR | Vide dans l'implémentation Python (réservé pour l'implémentation Cortex). |

### Métriques d'évaluation (calculées sur MART_PREDICTIONS)

| Cible | Accuracy | Macro-F1 |
|-------|----------|----------|
| issuetype | **75,32 %** | 33,77 % |
| résolution | **91,52 %** | 16,40 % |

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

## MARTS_ANALYTICS.MART_ANALYTICS_DEPS

Agrégats pour les pages "Charge de travail" et "Relations" du tableau de bord.

**Granularité :** entité (assignataire ou ticket) × type de section  
**Lignes :** 13 968

| Colonne | Type | Description |
|---------|------|-------------|
| `section_type` | VARCHAR | `assignee` ou `issue_links`. |
| `entity_key` | VARCHAR | Identifiant de l'assignataire ou clé du ticket. |
| `n_assigned` | NUMBER | Nombre de tickets assignés (section assignee). |
| `n_fixed` | NUMBER | Nombre de tickets résolus en Fixed. |
| `avg_resolution_days` | FLOAT | Délai moyen de résolution. |
| `top_issuetype` | VARCHAR | Type d'incident le plus fréquent pour cet assignataire. |
| `n_links` | NUMBER | Nombre total de liens (section issue_links). |

---

## Fichiers locaux (non dans Snowflake)

### results/embeddings_cache.npz

Cache NumPy des embeddings d'entraînement.

| Propriété | Valeur |
|-----------|--------|
| Clé dans le fichier | `train_emb` |
| Shape | (38 274, 384) |
| Dtype | float32 |
| Normalisation | L2 (vecteurs unitaires) |
| Taille sur disque | 57 MB |
| Modèle source | all-MiniLM-L6-v2 (sentence-transformers) |

Chargé par `apps/inference/inference_app.py` et `load/run_ml_pipeline.py`.
Si absent, recalculé automatiquement (~10 min).

### Seeds dbt

| Fichier | Lignes | Description |
|---------|--------|-------------|
| `dbt_project/seeds/issuetype_mapping.csv` | 22 | raw_value → 9 classes consolidées |
| `dbt_project/seeds/resolution_mapping.csv` | 15 | raw_value → 7 classes consolidées |
