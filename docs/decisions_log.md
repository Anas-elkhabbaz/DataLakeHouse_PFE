# Journal des décisions de conception — PFE Spark Triage

Ce document liste les décisions **figées** (§5 de la spécification) qui ne doivent pas
être modifiées sans instruction explicite. Il sert de référence pour le jury lors de la soutenance.

---

## D-01 : Cibles de classification (§5.1)

**Décision :** Deux cibles de classification, plus une génération de texte.

| Cible | Nature | Justification |
|-------|--------|---------------|
| `issuetype` | Classification (9 classes) | Discrimine le type de travail à effectuer |
| `resolution` | Classification (7 classes) | Prédit l'issue probable du ticket |
| `fix_summary` | Génération RAG (1-2 phrases) | Fournit une piste de correction actionnelle |

**Raison :** Correspond à la question métier réelle d'un responsable qualité : *Quel type de problème est-ce ? Comment va-t-il être résolu ? Que faut-il faire ?*

---

## D-02 : Vocabulaire issuetype consolidé (§5.2)

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
| **Other** | Umbrella, Wish, Story, Dependency upgrade, Epic, Brainstorming, IT Help, Request, Github Integration, Planned Work, New JIRA Project, Blog - New Blog Request, et toute valeur inconnue |

**Raison :** Les classes rares (<0,5 % chacune) sont trop peu représentées pour être apprises. Les regrouper en `Other` évite le sur-apprentissage sur des classes anecdotiques.

---

## D-03 : Vocabulaire resolution consolidé (§5.2)

**7 classes finales (lignes NULL supprimées, non étiquetées) :**

| Classe | Valeurs brutes regroupées |
|--------|--------------------------|
| Fixed | Fixed, Done, Resolved, Implemented |
| Won't Fix | Won't Fix, Won't Do, Later, Abandoned |
| Not A Problem | Not A Problem, Not A Bug, Works for Me |
| Incomplete | Incomplete |
| Duplicate | Duplicate |
| Invalid | Invalid |
| Cannot Reproduce | Cannot Reproduce |

**Valeurs supprimées (< 0,2 % combinées) :**
Auto Closed, Workaround, Information Provided, Feedback Received, et toute valeur NULL (issues ouvertes).

**Raison :** Les valeurs supprimées n'ont pas de sémantique stable pour un classificateur.
Les issues ouvertes (résolution NULL) ne peuvent pas servir d'exemple d'entraînement car leur résolution finale est inconnue.

---

## D-04 : Split temporel (§5.3)

| Partition | Filtre | Compte approx. | Usage |
|-----------|--------|----------------|-------|
| `train` | `created_at < '2023-01-01'` | ~41 400 | Index de récupération |
| `validation` | `created_at >= '2023-01-01' AND < '2024-01-01'` | ~4 700 | Évaluation hors-échantillon |
| `excluded` | `created_at >= '2024-01-01'` | ~3 700 | Année partielle, exclue |

**Raison :** Le split temporel est plus réaliste qu'un split aléatoire : en production, on prédit sur des tickets futurs, jamais sur du passé mélangé avec l'entraînement. La coupure 2023 est choisie pour laisser une pleine année de validation avec un volume suffisant (~4 700 tickets).

---

## D-05 : Périmètre projet = SPARK uniquement (§5.4)

**Décision :** Seules les issues avec `project.key = 'SPARK'` sont traitées.

**Raison :** La spécialisation sur un seul projet garantit la cohérence du vocabulaire technique (composants, erreurs, workflows propres à Spark). Étendre à d'autres projets Apache (Hadoop, Kafka…) nécessiterait une adaptation du mapping de labels et des prompts Cortex.

---

## D-06 : Architecture technique (hors périmètre)

Choix **exclus** du projet, non implémentés :

| Composant exclu | Raison |
|-----------------|--------|
| Streaming (Kafka) | Données statiques (snapshot Kaggle) |
| Airbyte / Fivetran | PUT + COPY INTO suffisent |
| Azure Data Lake | Stage interne Snowflake suffisant |
| Airflow / Dagster | Exécution manuelle suffisante pour un PFE |
| Power BI | Streamlit offre plus de flexibilité de développement |
| OCR d'images | JIRA Apache = tickets textuels uniquement |

---

## D-07 : Modèles Cortex utilisés

| Rôle | Modèle | Justification |
|------|--------|---------------|
| Embeddings | `voyage-multilingual-2` (1024d) | Meilleure qualité sur texte technique multilingue |
| RCA + arbitrage LLM | `mistral-large2` | Capacité de raisonnement structuré, coût maîtrisé |
| Génération fix_summary | `llama3.1-70b` | Génération fluide de texte court, plus rapide que mistral-large2 |

**Contrainte hard :** Toute inférence NLP utilise exclusivement Snowflake Cortex. Aucune API externe (OpenAI, Anthropic, etc.) n'est appelée.

---

## D-08 : Seuils du gate de confiance V6 (§9.4 Step 5)

| Cible | Seuil confiance | Max diversité (div) | Seuil margin |
|-------|-----------------|---------------------|--------------|
| issuetype | ≥ 0,55 | ≤ 4 | ≥ 0,20 |
| resolution | ≥ 0,50 | ≤ 4 | ≥ 0,15 |

**Raison :** Les seuils resolution sont assouplis car `Fixed` domine (~60 % des tickets) et génère naturellement une forte confiance dans le vote pondéré, ce qui évite des appels LLM inutiles sur les cas faciles.
