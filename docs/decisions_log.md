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

**Note implémentation :** La valeur "Won't Fix" contient une apostrophe. Dans les tests
`accepted_values` dbt, la valeur doit être écrite `"Won''t Fix"` (apostrophe doublée) pour
que dbt génère le SQL valide `'Won''t Fix'`. Un simple `"Won't Fix"` génère `'Won't Fix'`
(syntaxe SQL invalide, erreur `unexpected 't'`).

---

## D-04 : Split temporel 3-way (train / validation / test)

| Partition | Filtre | Lignes approx. | Usage |
|-----------|--------|----------------|-------|
| `train` | `created_at < '2022-01-01'` | ~38 274 | Index de récupération KNN |
| `validation` | `2022-01-01 ≤ created_at < '2023-01-01'` | ~3 809 | Ajustement des hyperparamètres |
| `test` | `2023-01-01 ≤ created_at < '2024-01-01'` | ~3 700 | Évaluation finale unique |
| `excluded` | `created_at ≥ '2024-01-01'` | — | Année partielle, exclue |

**Raison :** Le split temporel est plus réaliste qu'un split aléatoire — en production, on
prédit sur des tickets futurs, jamais sur du passé mélangé avec l'entraînement. La partition
`test` ne doit être utilisée qu'une seule fois (`--phase final`) après avoir figé tous les
hyperparamètres sur la validation, pour garantir une évaluation honnête.

**Adaptation :** Le split initial était 2-way (train < 2023, validation 2023). La refonte V6
l'a rendu 3-way pour séparer le jeu d'ajustement du jeu d'évaluation finale. Cela réduit
légèrement l'ensemble d'entraînement (~8 400 tickets de 2022 passent en validation).

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

## D-07 : Pipeline d'inférence — V6 Hybrid RCA (Python)

**Décision initiale (spécification) :** Pipeline entièrement dans Snowflake Cortex.
- Embeddings : `SNOWFLAKE.CORTEX.EMBED_TEXT_1024('voyage-multilingual-2', ...)` (1024d)
- Résumé RCA : `SNOWFLAKE.CORTEX.COMPLETE('mistral-large2', ...)`
- Arbitrage LLM : `SNOWFLAKE.CORTEX.COMPLETE('mistral-large2', ...)`
- Génération fix_summary : `SNOWFLAKE.CORTEX.COMPLETE('llama3.1-70b', ...)`

**Décision implémentée :** Pipeline Python V6 Hybrid RCA implémentant les 4 principes :

| Principe V6 | Implémentation |
|-------------|----------------|
| Dual embeddings | NOCO (sans commentaires) + RICH (avec commentaires), BAAI/bge-large-en-v1.5 (1024d) |
| Fusion RRF | Reciprocal Rank Fusion k=60, top-30 candidats |
| Changelog re-ranking | Score L2 inverse dans l'espace changelog standardisé (8 features) |
| Confidence gate + LLM | Gate l0_conf/margin → DIRECT ou LLM_REQUIRED (Anthropic/Ollama) |

**Raison de l'adaptation :** Les fonctions `CORTEX.COMPLETE` et `CORTEX.EMBED_TEXT_1024`
sont bloquées sur les comptes Snowflake trial (erreur 399258 : *AI function COMPLETE is not
available for trial accounts*). Le fallback Python implémente intégralement l'architecture V6
et produit des résultats mesurables sans coût supplémentaire.

**Les scripts `cortex/*.sql` sont conservés** et fonctionneront intégralement sur un compte payant.

---

## D-08 : Seuils du gate de confiance

Implémenté dans `load/retrieval.py` (`route()`) et utilisé par le pipeline batch et l'app d'inférence :

| Signal | Définition | Seuil DIRECT |
|--------|------------|--------------|
| `l0_conf` | Score du label gagnant / score total du vote | ≥ 0.65 |
| `margin` | (Score gagnant − Score 2ème) / score total | ≥ 0.10 |

Les deux conditions doivent être simultanément satisfaites pour router en DIRECT.
Sinon : LLM_REQUIRED → appel au LLM avec liste de labels contrainte.

**Raison :** Ces seuils séparent les prédictions à forte majorité (voisins d'accord)
des prédictions incertaines (vote partagé entre plusieurs classes). La margin évite les
cas où l0_conf est élevé par défaut (label très fréquent) mais le 2ème candidat est proche.

**Colonnes dans CORTEX.MART_PREDICTIONS :**
- `routing_issuetype` : "DIRECT" ou "LLM_REQUIRED"
- `margin_issuetype` : margin du vote issuetype
- `routing_resolution` : "DIRECT" ou "LLM_REQUIRED"
- `margin_resolution` : margin du vote résolution

---

## D-09 : Gestion des tables brutes en VARCHAR

**Décision :** Toutes les colonnes de RAW.ISSUES, RAW.COMMENTS, RAW.CHANGELOG et
RAW.ISSUELINKS sont déclarées en VARCHAR.

**Raison :** Les CSV Kaggle contiennent des valeurs mal formées (timestamps invalides,
nombres en notation scientifique). Typer les colonnes en COPY INTO provoquerait des erreurs
et des lignes ignorées silencieusement. Le cast est effectué en staging via `TRY_TO_*` qui
retourne NULL plutôt qu'une erreur.

---

## D-10 : Cache local des embeddings duaux

**Décision :** Les embeddings d'entraînement sont calculés une seule fois et sauvegardés dans
`results/embeddings_noco.npz` et `results/embeddings_rich.npz`. Un fichier de métadonnées
`results/embeddings_meta.json` stocke le modèle, les dimensions, le sha256 des colonnes source
et la date de calcul pour valider la cohérence des caches.

**Raison :** BAAI/bge-large-en-v1.5 sur CPU prend ~30–60 min par corpus (NOCO + RICH = ~120 min
total). Versionner les caches permet à tout collaborateur ou container Docker de démarrer
l'inférence sans recalcul. La taille combinée (~150 MB) est sous la limite hard de GitHub (100 MB
par fichier, 2 fichiers séparés).

---

## D-11 : Architecture Docker

**Décision :** Deux Dockerfiles séparés (un par application) orchestrés via docker-compose.

| Service | Image de base | Particularité |
|---------|---------------|---------------|
| spark-inference | python:3.12-slim | Pré-charge BAAI/bge-large-en-v1.5 dans le build, copie embeddings_noco.npz + embeddings_rich.npz |
| spark-analytics | python:3.12-slim | Image légère, pas de modèle ML |

**Raison :** Séparer les deux apps permet de les rebuilder indépendamment.
Le pré-chargement du modèle dans le build évite tout téléchargement au démarrage du container.

---

## D-12 : Choix du modèle d'embedding — BAAI/bge-large-en-v1.5

**Décision :** Remplacer `all-MiniLM-L6-v2` (384d) par `BAAI/bge-large-en-v1.5` (1024d).

**Raison :** BGE-large-en-v1.5 domine les benchmarks MTEB (Massive Text Embedding Benchmark)
sur les tâches de récupération d'information en anglais (BEIR, HotpotQA, etc.). Le préfixe
asymétrique (`"Represent this sentence for searching relevant passages: "`) améliore la
récupération sans dégradation sur les documents. Le passage de 384d à 1024d augmente la capacité
représentationnelle pour des tickets techniques JIRA avec vocabulaire spécialisé.

**Coût :** Taille modèle ~1,3 GB (contre ~80 MB pour MiniLM). Temps d'encodage ~3x plus long.
Caches NPZ plus volumineux (~150 MB combiné contre 57 MB pour MiniLM).

---

## D-13 : Stratégie LLM — Ollama par défaut, Anthropic optionnel

**Décision :** L'adapter LLM (`cortex/llm_client.py`) tente Anthropic en premier si
`ANTHROPIC_API_KEY` est défini, sinon Ollama sur `http://localhost:11434`, sinon lève
`LLMUnavailableError`. Le pipeline fonctionne proprement dans tous les cas (mode dégradé DIRECT).

**Raison :** Ollama est gratuit et ne nécessite pas de compte — le cas le plus probable pour
un PFE sans budget cloud. Anthropic est proposé comme option premium pour la production.
L'indisponibilité LLM ne doit jamais bloquer le pipeline : les prédictions LLM_REQUIRED
sont conservées telles quelles avec un flag de confiance basse dans l'UI.

**Modèles :**
- Anthropic : `claude-haiku-4-5` (rapide, ~$0.25/M tokens)
- Ollama : `mistral:7b` (4 GB, gratuit, ~1–3 s par appel en local)

---

## D-14 : Split des marts analytics (workload + links)

**Décision :** Supprimer `mart_analytics_deps.sql` (VARIANT OBJECT_CONSTRUCT, colonnes polymorphes)
et le remplacer par deux marts plats :
- `mart_analytics_workload.sql` : métriques par assignataire
- `mart_analytics_links.sql` : métriques par ticket pour les liens

**Raison :** L'ancien mart utilisait `OBJECT_CONSTRUCT` qui produisait des colonnes de type VARIANT
non requêtables directement depuis pandas. Les pages Streamlit 3 et 4 contournaient déjà ce mart
en requêtant les tables INTERMEDIATE directement. Les deux nouveaux marts plats sont requêtables
directement et correspondent à la documentation du dictionnaire des données.

---

## D-15 : Dual embedding — texte NOCO vs RICH

**Décision :** Encoder deux représentations textuelles distinctes par ticket :
- `text_noco` : résumé + priorité + statut + description (sans commentaires, sans labels)
- `text_rich` : résumé + priorité + statut + n_comments + description + discussion (commentaires)

La colonne `TYPE: {issuetype}` a été **supprimée** de `text_noco` (leakage de label).

**Raison :** Encoder l'issuetype dans le texte servant à l'embedding crée un leakage direct :
lors de la requête, le ticket n'a pas encore de label, donc le texte requête n'inclut pas le
label → asymétrie entre le corpus et la requête → biais de récupération vers les tickets du
même label. Supprimer le label garantit une représentation honnête.

La stratégie NOCO + RICH permet de capter à la fois la similarité textuelle brute du ticket
(NOCO) et le contexte de discussion (RICH). La fusion RRF combine les deux listes de rang
sans supposer que l'une est systématiquement meilleure.

---

## D-16 : Génération lazy des fix_summaries

**Décision :** Les résumés de correction (`fix_summary`) sont générés à la demande uniquement
pour les tickets apparaissant comme top-5 voisins, et mis en cache dans `results/fix_summaries.json`.
Ils ne sont pas pré-calculés pour tout l'ensemble d'entraînement.

**Raison :** L'ensemble d'entraînement compte ~38 274 tickets. Générer un résumé LLM pour
chacun coûterait ~$10–50 (Anthropic) ou ~80–160 heures (Ollama local). En pratique, seul
un sous-ensemble de ~500–2000 tickets apparaît réellement comme voisin fréquent. La génération
lazy amortit ce coût sur les requêtes réelles plutôt que de le payer en avance.
