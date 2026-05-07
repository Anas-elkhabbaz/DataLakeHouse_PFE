# Dictionnaire des données — mart_ml

Table : `PFE_SPARK.MARTS_ML.MART_ML`  
Granularité : un ticket Apache Spark JIRA par ligne  
Lignes attendues : ~46 100 (train + validation)

---

## Colonnes d'identification et de partitionnement

| Colonne | Type | Description |
|---------|------|-------------|
| `key` | VARCHAR | Clé unique du ticket JIRA (format : SPARK-NNNNN). Clé primaire. |
| `created_at` | TIMESTAMP_TZ | Date et heure de création du ticket (fuseau horaire inclus). |
| `split` | VARCHAR | Partition temporelle : `train` (créé avant 2023-01-01) ou `validation` (2023). |

## Cibles de classification (§5.1)

| Colonne | Type | Description | Classes |
|---------|------|-------------|---------|
| `issuetype` | VARCHAR | Type d'incident consolidé (cible principale). | Bug, Improvement, Sub-task, New Feature, Task, Test, Documentation, Question, Other |
| `resolution` | VARCHAR | Résolution consolidée (cible secondaire). | Fixed, Won't Fix, Not A Problem, Incomplete, Duplicate, Invalid, Cannot Reproduce |

## Texte nettoyé

| Colonne | Type | Description |
|---------|------|-------------|
| `summary_clean` | VARCHAR | Résumé du ticket après nettoyage NLP (HTML, JIRA markup, URLs supprimés). |
| `description_clean` | VARCHAR | Description complète après nettoyage NLP. NULL si absente (~2,4 %). |
| `comments_concat` | VARCHAR | Commentaires agrégés chronologiquement, séparés par ` \| `, tronqués à 3 000 caractères. Chaîne vide si aucun commentaire. |

## Représentations textuelles (V6 Hybrid RCA)

| Colonne | Type | Description |
|---------|------|-------------|
| `text_noco` | VARCHAR | Représentation NOCO (No Comments) — format structuré TICKET/TYPE/STATUS/DESC, tronquée à 2 000 caractères. Reflète la distribution des tickets de validation (sans historique). |

*Note : `text_rich` est généré par `cortex/01_train_enriched.sql` et non stocké dans mart_ml.*

## Métadonnées pour le boost de récupération

| Colonne | Type | Description |
|---------|------|-------------|
| `priority` | VARCHAR | Priorité du ticket (Blocker, Critical, Major, Minor, Trivial). |
| `status` | VARCHAR | Statut courant (Open, In Progress, Resolved, Closed…). |
| `reporter` | VARCHAR | Identifiant de l'auteur du ticket. |
| `assignee` | VARCHAR | Identifiant de l'assignataire. `Unassigned` si non renseigné (~34 % des tickets). |

## Features changelog (contribution originale du PFE)

Ces features sont absentes du hackathon V6 originel et constituent la contribution technique principale.

| Colonne | Type | Description |
|---------|------|-------------|
| `n_total_changes` | NUMBER | Nombre total de changements de champs enregistrés dans l'historique. |
| `n_status_changes` | NUMBER | Nombre de transitions de statut (ex. Open → In Progress → Resolved). |
| `n_priority_changes` | NUMBER | Nombre de changements de priorité. |
| `n_assignee_changes` | NUMBER | Nombre de reasignations. Indicateur de complexité et d'escalade. |
| `n_resolution_changes` | NUMBER | Nombre de changements de résolution (ex. réouvertures). |
| `was_escalated` | NUMBER (0/1) | 1 si la priorité a augmenté au moins une fois dans l'historique (ex. Minor → Major). |
| `n_people_involved` | NUMBER | Nombre d'auteurs distincts dans le changelog (diversité des intervenants). |
| `first_assignee` | VARCHAR | Premier assignataire selon le changelog. NULL si aucun événement d'assignation. |

## Features de liens entre tickets

| Colonne | Type | Description |
|---------|------|-------------|
| `n_links_total` | NUMBER | Nombre total de liens sortants du ticket. |
| `n_duplicates` | NUMBER | Nombre de liens de type "Duplicate" — ticket marqué comme doublon d'autres. |
| `n_blocks` | NUMBER | Nombre de tickets que ce ticket bloque (liens entrants de type "Blocks"). |
| `n_blocked_by` | NUMBER | Nombre de tickets qui bloquent ce ticket (liens sortants de type "Blocks"). |
| `n_relates` | NUMBER | Nombre de liens de type "Relates" — relation informelle entre tickets. |

## Features de commentaires

| Colonne | Type | Description |
|---------|------|-------------|
| `n_comments` | NUMBER | Nombre total de commentaires après nettoyage (corps ≥ 10 caractères). |
| `n_commenters` | NUMBER | Nombre d'auteurs distincts ayant commenté le ticket. |

## Métriques de timing et de longueur

| Colonne | Type | Description |
|---------|------|-------------|
| `resolution_days` | NUMBER | Nombre de jours entre la création et la résolution, plafonné à 5 000. NULL si non résolu. |
| `summary_length` | NUMBER | Longueur en caractères du résumé nettoyé. |
| `description_length` | NUMBER | Longueur en caractères de la description nettoyée. 0 si NULL. |

---

## Tables annexes

### `PFE_SPARK.CORTEX.TRAIN_EMBEDDINGS`

| Colonne | Type | Description |
|---------|------|-------------|
| `key` | VARCHAR | Clé du ticket d'entraînement. |
| `issuetype` | VARCHAR | Label issuetype (index de récupération). |
| `resolution` | VARCHAR | Label resolution (index de récupération). |
| `priority` | VARCHAR | Pour le boost de métadonnées lors de l'inférence. |
| `status` | VARCHAR | Pour le boost de métadonnées. |
| `reporter` | VARCHAR | Pour le boost de métadonnées. |
| `text_rich` | VARCHAR | Représentation RICH (TICKET + RCA + COMMENTS) pour le contexte LLM. |
| `embedding_noco` | VECTOR(FLOAT, 1024) | Embedding voyage-multilingual-2 sur text_noco. |
| `embedding_rich` | VECTOR(FLOAT, 1024) | Embedding voyage-multilingual-2 sur text_rich. |

### `PFE_SPARK.CORTEX.MART_PREDICTIONS`

| Colonne | Type | Description |
|---------|------|-------------|
| `key` | VARCHAR | Clé du ticket de validation. |
| `predicted_issuetype` | VARCHAR | Issuetype prédit par le pipeline V6. |
| `predicted_resolution` | VARCHAR | Résolution prédite. |
| `fix_summary` | VARCHAR | Résumé du correctif généré par llama3.1-70b (1-2 phrases). |
| `method_issuetype` | VARCHAR | Chemin emprunté : `DIRECT` (vote pondéré) ou `LLM` (arbitrage mistral-large2). |
| `method_resolution` | VARCHAR | Chemin emprunté : `DIRECT` ou `LLM`. |
