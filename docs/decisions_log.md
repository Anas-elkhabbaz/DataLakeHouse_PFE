# Journal des décisions de conception — PFE Spark Triage

Ce document liste les décisions architecturales prises durant le projet, leur justification,
et les adaptations apportées lors de l'implémentation réelle par rapport à la spécification initiale.

---

## D-01 : Cibles de classification

**Décision :** Deux cibles de classification et une analyse textuelle.

| Cible | Nature | Justification |
|-------|--------|---------------|
| `issuetype` | Classification (9 classes) | Discrimine le type de travail et oriente le routage |
| `resolution` | Classification (7 classes) | Prédit l'issue probable, oriente la priorité |
| Analyse textuelle | Génération (2-3 phrases) | Explication actionnable pour l'ingénieur |

**Raison :** Correspond à la question métier réelle d'un responsable qualité :
*Quel type de problème est-ce ? Comment va-t-il être résolu ? Que faut-il faire ?*

---

## D-02 : Vocabulaire issuetype consolidé

**9 classes finales :**

| Classe | Valeurs brutes regroupées |
|--------|--------------------------|
| Bug | Bug |
| Improvement | Improvement |
| Sub-task | Sub-task |
| New Feature | New Feature |
| Task | Task, Technical task |
| Test | Test |
| Documentation | Documentation |
| Question | Question |
| Other | Umbrella, Wish, Story, Dependency upgrade, Epic, et toute valeur inconnue |

**Raison :** Les classes rares (<0,5 % chacune) sont trop peu représentées pour être apprises.
Les regrouper en `Other` évite le sur-apprentissage sur des classes anecdotiques.

---

## D-03 : Vocabulaire resolution consolidé

**7 classes finales :**

| Classe | Valeurs brutes regroupées |
|--------|--------------------------|
| Fixed | Fixed, Done, Resolved, Implemented |
| Won't Fix | Won't Fix, Won't Do, Later, Abandoned |
| Not A Problem | Not A Problem, Not A Bug, Works for Me |
| Incomplete | Incomplete |
| Duplicate | Duplicate |
| Invalid | Invalid |
| Cannot Reproduce | Cannot Reproduce |

**Valeurs supprimées :** Auto Closed, Workaround, Information Provided, NULL (issues ouvertes).

**Raison :** Les issues ouvertes (résolution NULL) ne peuvent pas servir d'exemples
d'entraînement car leur résolution finale est inconnue. Après filtrage, il reste 42 083 tickets.

---

## D-04 : Split temporel

| Partition | Filtre | Lignes réelles | Usage |
|-----------|--------|----------------|-------|
| `train` | `created_at < '2023-01-01'` | 38 274 | Index de récupération KNN |
| `validation` | `2023-01-01 ≤ created_at < '2024-01-01'` | 3 809 | Évaluation hors-échantillon |
| `excluded` | `created_at ≥ '2024-01-01'` | ~3 700 | Année partielle, exclue |

**Raison :** Le split temporel est plus réaliste qu'un split aléatoire — en production, on
prédit sur des tickets futurs, jamais sur du passé mélangé avec l'entraînement.

---

## D-05 : Périmètre projet = SPARK uniquement

**Décision :** Seules les issues avec `project_key = 'SPARK'` sont traitées.

**Raison :** La spécialisation garantit la cohérence du vocabulaire technique. Le dataset
complet contient 1 149 321 issues toutes projets confondus ; SPARK en représente 49 832
(4,3 %), un volume suffisant pour entraîner et évaluer le pipeline.

---

## D-06 : Déduplication à la source

**Décision :** `QUALIFY ROW_NUMBER() OVER (PARTITION BY key ORDER BY id) = 1` dans `stg_issues`.

**Raison :** La source RAW.ISSUES contient 4 clés JIRA en double (bug de l'export Kaggle).
Sans déduplication, les tests `unique` dbt échouaient en cascade jusqu'à `mart_ml`.
La déduplication par `id` le plus petit garantit l'idempotence et le choix de la ligne originale.

---

## D-07 : Pipeline d'inférence — Fallback Python

**Décision initiale (spécification) :** Pipeline entièrement dans Snowflake Cortex.
- Embeddings : `SNOWFLAKE.CORTEX.EMBED_TEXT_1024('voyage-multilingual-2', ...)` (1024d)
- Résumé RCA : `SNOWFLAKE.CORTEX.COMPLETE('mistral-large2', ...)`
- Arbitrage LLM : `SNOWFLAKE.CORTEX.COMPLETE('mistral-large2', ...)` pour les cas incertains
- Génération fix_summary : `SNOWFLAKE.CORTEX.COMPLETE('llama3.1-70b', ...)`

**Décision implémentée :** Pipeline Python avec sentence-transformers.
- Embeddings : `all-MiniLM-L6-v2` via sentence-transformers (384 dimensions, local)
- Prédiction : vote pondéré KNN cosinus (k=15)
- Analyse textuelle (UI) : `claude-haiku-4-5` via Anthropic API (optionnel) ou template structuré

**Raison de l'adaptation :** Les fonctions `CORTEX.COMPLETE` et `CORTEX.EMBED_TEXT_1024`
sont bloquées sur les comptes Snowflake trial (erreur 399258 : *AI function COMPLETE is not
available for trial accounts*). Le fallback Python produit des résultats conformes aux seuils
cibles (75,3 % accuracy issuetype, 91,5 % accuracy résolution) sans coût supplémentaire.

**Les scripts `cortex/*.sql` sont conservés** et fonctionneront intégralement sur un compte payant.

---

## D-08 : Seuils du gate de confiance

Implémenté dans le vote pondéré de `load/run_ml_pipeline.py` et `apps/inference/inference_app.py` :

| Niveau | Seuil confiance | Couleur UI | Comportement |
|--------|-----------------|------------|--------------|
| High | ≥ 65 % | Vert | Prédiction directe, affichée sans avertissement |
| Medium | 45–64 % | Ambre | Prédiction affichée, consultation des tickets similaires conseillée |
| Low | < 45 % | Rouge | Avertissement explicite — révision manuelle requise |

**Raison :** Ces seuils ont été calibrés empiriquement sur la distribution des confiances
observées sur les 3 809 tickets de validation.

---

## D-09 : Gestion des tables brutes en VARCHAR

**Décision :** Toutes les colonnes de RAW.ISSUES, RAW.COMMENTS, RAW.CHANGELOG et
RAW.ISSUELINKS sont déclarées en VARCHAR.

**Raison :** Les CSV Kaggle contiennent des valeurs mal formées (timestamps invalides,
nombres en notation scientifique). Typer les colonnes en COPY INTO provoquerait des erreurs
et des lignes ignorées silencieusement. Le cast est effectué en staging via `TRY_TO_*` qui
retourne NULL plutôt qu'une erreur.

---

## D-10 : Cache local des embeddings

**Décision :** Les embeddings d'entraînement sont calculés une seule fois et sauvegardés dans
`results/embeddings_cache.npz` (57 MB). Le fichier est versionné dans git.

**Raison :** Le calcul des embeddings pour 38 274 tickets prend ~10 min sur CPU. Versionner
le cache permet à tout collaborateur (ou container Docker) de démarrer l'application d'inférence
instantanément sans recalcul. La taille (57 MB) est sous la limite hard de GitHub (100 MB).

---

## D-11 : Architecture Docker

**Décision :** Deux Dockerfiles séparés (un par application) orchestrés via docker-compose.

| Service | Image de base | Particularité |
|---------|---------------|---------------|
| spark-inference | python:3.12-slim | Pré-charge all-MiniLM-L6-v2 dans le build, copie embeddings_cache.npz |
| spark-analytics | python:3.12-slim | Image légère, pas de modèle ML |

**Raison :** Séparer les deux apps permet de les rebuilder indépendamment.
Le pré-chargement du modèle dans le build évite tout téléchargement au démarrage du container.
