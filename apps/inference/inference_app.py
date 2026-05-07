"""
Triage automatique d'incidents Apache Spark
Application Streamlit — Path 1 : Inférence V6 Hybrid RCA (fallback local)

Lancement : streamlit run apps/inference/inference_app.py
"""

import os
from pathlib import Path
from dotenv import load_dotenv

import numpy as np
import pandas as pd
import streamlit as st
import snowflake.connector
from sentence_transformers import SentenceTransformer

load_dotenv()

ROOT        = Path(__file__).parent.parent.parent
CACHE_PATH  = ROOT / "results" / "embeddings_cache.npz"
MODEL_NAME  = "all-MiniLM-L6-v2"
K           = 15

st.set_page_config(
    page_title="Triage Spark — PFE UIR",
    page_icon="⚡",
    layout="wide",
)


# ── Connexion Snowflake ──────────────────────────────────────────────────────
@st.cache_resource(show_spinner="Connexion Snowflake…")
def get_conn():
    return snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        role=os.environ.get("SNOWFLAKE_ROLE", "SYSADMIN"),
        warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE", "PFE_WH"),
        database=os.environ.get("SNOWFLAKE_DATABASE", "PFE_SPARK"),
        schema="MARTS_ML",
    )


def run_query(sql: str) -> pd.DataFrame:
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute(sql)
        cols = [d[0].lower() for d in cur.description]
        return pd.DataFrame(cur.fetchall(), columns=cols)


# ── Modèle d'embedding ──────────────────────────────────────────────────────
@st.cache_resource(show_spinner="Chargement du modèle d'embedding…")
def load_model() -> SentenceTransformer:
    return SentenceTransformer(MODEL_NAME)


# ── Données d'entraînement (méta + embeddings) ───────────────────────────────
@st.cache_resource(show_spinner="Chargement des tickets d'entraînement…")
def load_train_data():
    """Returns (train_df, train_embeddings_array)."""
    df = run_query("""
        SELECT key, issuetype, resolution, priority, status, reporter,
               summary_clean, LEFT(text_noco, 300) AS excerpt
        FROM PFE_SPARK.MARTS_ML.MART_ML
        WHERE split = 'train'
    """)

    if CACHE_PATH.exists():
        cache = np.load(CACHE_PATH, allow_pickle=True)
        emb = cache["train_emb"].astype("float32")
        # L2-normalise (already done during training, but ensure consistency)
        norms = np.linalg.norm(emb, axis=1, keepdims=True)
        emb = emb / np.where(norms == 0, 1, norms)
    else:
        # Re-compute embeddings if cache is missing (first-time setup)
        model = load_model()
        texts = df["excerpt"].fillna("").tolist()
        emb = model.encode(texts, batch_size=256, normalize_embeddings=True,
                           show_progress_bar=False).astype("float32")
        CACHE_PATH.parent.mkdir(exist_ok=True)
        np.savez_compressed(CACHE_PATH, train_emb=emb)

    return df.reset_index(drop=True), emb


# ── Construction de text_noco ─────────────────────────────────────────────────
def build_text_noco(summary: str, priority: str,
                    status: str, description: str) -> str:
    return (
        f"TICKET: {summary}\n"
        f"TYPE: Unknown | PRI: {priority}\n"
        f"STATUS: {status}\n"
        f"DESC: {description[:800]}"
    )[:2000]


# ── Prédiction ────────────────────────────────────────────────────────────────
def predict(text_noco: str, val_priority: str,
            val_status: str, val_reporter: str) -> dict:
    model     = load_model()
    train_df, train_emb = load_train_data()

    # Embed input ticket
    q_emb = model.encode([text_noco], normalize_embeddings=True).astype("float32")[0]

    # Cosine similarity (dot product, embeddings are L2-normalised)
    sims = train_emb @ q_emb

    # Metadata boost (mirrors §9.4 spec)
    priority_boost = (train_df["priority"] == val_priority).astype(float) * 0.10
    status_boost   = (train_df["status"]   == val_status).astype(float)   * 0.08
    reporter_boost = (train_df["reporter"] == val_reporter).astype(float) * 0.05
    fused = sims + priority_boost.values + status_boost.values + reporter_boost.values

    top_idx  = np.argsort(fused)[::-1][:K]
    top_sims = fused[top_idx]
    top_rows = train_df.iloc[top_idx]

    # Weighted vote
    def weighted_vote(labels, weights):
        scores: dict = {}
        for lbl, w in zip(labels, weights):
            scores[lbl] = scores.get(lbl, 0.0) + float(w)
        total = sum(scores.values())
        best  = max(scores, key=scores.get)
        return best, round(scores[best] / total, 4) if total else 0.0, scores

    it,  conf_it,  _ = weighted_vote(top_rows["issuetype"].values, top_sims)
    res, conf_res, _ = weighted_vote(top_rows["resolution"].values, top_sims)

    similar = top_rows.head(3).copy()
    similar["similarity"] = top_sims[:3].round(4)

    return {
        "predicted_issuetype":  it,
        "predicted_resolution": res,
        "it_conf":              conf_it,
        "re_conf":              conf_res,
        "method":               "DIRECT",
        "similar":              similar,
    }


# ── Interface ─────────────────────────────────────────────────────────────────
st.title("⚡ Triage automatique d'incidents Apache Spark")
st.caption("Pipeline V6 Hybrid RCA — KNN Similarity | PFE UIR 2026")
st.divider()

col1, col2 = st.columns([2, 1])

with col1:
    summary = st.text_area(
        "Résumé de l'incident",
        value="SparkContext fails to initialize with OutOfMemoryError on executor startup",
        height=80,
    )
    description = st.text_area(
        "Description détaillée",
        value=(
            "When submitting a job with spark.executor.memory=4g on a YARN cluster, "
            "the executors crash immediately with java.lang.OutOfMemoryError: GC overhead limit exceeded. "
            "The issue is reproducible with Spark 3.4.0 and Hadoop 3.3.x. "
            "Driver logs show: ERROR SparkContext: Error initializing SparkContext. "
            "Reducing executor memory to 2g resolves the issue."
        ),
        height=150,
    )

with col2:
    priority = st.selectbox("Priorité", ["Major", "Critical", "Minor", "Blocker", "Trivial"])
    status   = st.selectbox("Statut",   ["Open", "In Progress", "Resolved", "Closed", "Reopened"])
    reporter = st.text_input("Reporter (optionnel)", value="")

predict_btn = st.button("🔍 Prédire", type="primary", use_container_width=True)

if predict_btn:
    text_noco = build_text_noco(summary, priority, status, description)

    with st.spinner("Calcul de similarité en cours…"):
        result = predict(text_noco, priority, status, reporter or "Unknown")

    st.divider()
    st.subheader("Résultats de prédiction")

    c1, c2 = st.columns(2)
    with c1:
        st.metric("Type d'incident  🟢 DIRECT", result["predicted_issuetype"])
        st.caption(f"Confiance : {result['it_conf']:.1%}")
    with c2:
        st.metric("Résolution prédite  🟢 DIRECT", result["predicted_resolution"])
        st.caption(f"Confiance : {result['re_conf']:.1%}")

    with st.expander("🔍 Tickets similaires retrouvés (top-3)", expanded=True):
        for _, row in result["similar"].iterrows():
            st.markdown(f"**{row['key']}** — similarité : `{row['similarity']}`")
            st.markdown(f"Type : `{row['issuetype']}` | Résolution : `{row['resolution']}`")
            st.caption(row["excerpt"])
            st.divider()
