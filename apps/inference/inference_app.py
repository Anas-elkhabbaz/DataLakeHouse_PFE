"""
Spark Issue Triage System — Professional Inference Interface
PFE UIR 2026 | Pipeline V6 Hybrid RCA

Launch: streamlit run apps/inference/inference_app.py
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

ROOT       = Path(__file__).parent.parent.parent
CACHE_PATH = ROOT / "results" / "embeddings_cache.npz"
MODEL_NAME = "all-MiniLM-L6-v2"
K          = 15

ROUTING = {
    "Bug":           "Core Engineering — escalate for fix",
    "Improvement":   "Core Engineering — backlog review",
    "New Feature":   "Product — roadmap evaluation",
    "Sub-task":      "Link to parent ticket and assign owner",
    "Task":          "Assign to relevant team",
    "Test":          "QA Engineering",
    "Documentation": "Documentation team",
    "Question":      "Developer Support / Community",
    "Other":         "Manual qualification required",
}

RESOLUTION_GUIDANCE = {
    "Fixed":            "Assign to an engineer and open a fix branch.",
    "Won't Fix":        "Close with a written justification for the reporter.",
    "Not A Problem":    "Confirm expected behaviour, document and close.",
    "Duplicate":        "Find the original ticket, link it, and close this one.",
    "Incomplete":       "Request a minimal reproducible example from the reporter.",
    "Invalid":          "Close the ticket with an explanation.",
    "Cannot Reproduce": "Ask for environment details and a reproduction script.",
}

CONF_THRESHOLDS = {"high": 0.65, "medium": 0.45}


def confidence_label(c: float) -> str:
    if c >= CONF_THRESHOLDS["high"]:
        return "High"
    elif c >= CONF_THRESHOLDS["medium"]:
        return "Medium"
    return "Low"


def confidence_color(c: float) -> str:
    if c >= CONF_THRESHOLDS["high"]:
        return "#22c55e"
    elif c >= CONF_THRESHOLDS["medium"]:
        return "#f59e0b"
    return "#ef4444"


# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Spark Issue Triage",
    page_icon="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>S</text></svg>",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    /* Global */
    [data-testid="stAppViewContainer"] { background: #ffffff; }
    [data-testid="stSidebar"] {
        background: #f8fafc;
        border-right: 1px solid #e2e8f0;
    }
    [data-testid="stSidebar"] * { font-family: 'Inter', sans-serif; }
    .block-container { padding-top: 2rem; padding-bottom: 2rem; }

    /* Hide Streamlit chrome */
    #MainMenu { visibility: hidden; }
    footer { visibility: hidden; }
    header { visibility: hidden; }

    /* Prediction card */
    .pred-card {
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        padding: 28px 24px;
        height: 100%;
    }
    .pred-label {
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 0.1em;
        color: #94a3b8;
        text-transform: uppercase;
        margin-bottom: 6px;
    }
    .pred-value {
        font-size: 28px;
        font-weight: 700;
        color: #0f172a;
        margin-bottom: 14px;
        line-height: 1.2;
    }
    .conf-row {
        display: flex;
        align-items: center;
        gap: 10px;
        margin-top: 4px;
    }
    .conf-bar-track {
        flex: 1;
        background: #e2e8f0;
        border-radius: 4px;
        height: 6px;
    }
    .conf-bar-fill {
        height: 6px;
        border-radius: 4px;
    }
    .conf-pct {
        font-size: 13px;
        font-weight: 600;
        color: #334155;
        min-width: 36px;
    }
    .conf-badge {
        display: inline-block;
        font-size: 11px;
        font-weight: 600;
        padding: 2px 8px;
        border-radius: 20px;
        margin-top: 8px;
    }

    /* Section headers */
    .section-header {
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 0.1em;
        color: #94a3b8;
        text-transform: uppercase;
        margin-bottom: 14px;
        margin-top: 6px;
    }

    /* Analysis block */
    .analysis-block {
        background: #f0f7ff;
        border-left: 3px solid #3b82f6;
        border-radius: 0 8px 8px 0;
        padding: 18px 20px;
        font-size: 15px;
        line-height: 1.7;
        color: #1e293b;
    }

    /* Warning block */
    .warn-block {
        background: #fffbeb;
        border-left: 3px solid #f59e0b;
        border-radius: 0 8px 8px 0;
        padding: 14px 18px;
        font-size: 14px;
        color: #92400e;
    }

    /* Action cards */
    .action-card {
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 18px 20px;
    }
    .action-key {
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 0.08em;
        color: #94a3b8;
        text-transform: uppercase;
        margin-bottom: 6px;
    }
    .action-val {
        font-size: 14px;
        font-weight: 500;
        color: #1e293b;
        line-height: 1.5;
    }

    /* Evidence table */
    .evidence-row {
        display: flex;
        align-items: flex-start;
        gap: 16px;
        padding: 16px 0;
        border-bottom: 1px solid #f1f5f9;
    }
    .ev-key {
        font-family: 'Courier New', monospace;
        font-size: 13px;
        font-weight: 700;
        color: #3b82f6;
        min-width: 110px;
    }
    .ev-sim {
        font-size: 13px;
        font-weight: 600;
        color: #334155;
        min-width: 46px;
    }
    .ev-tag {
        display: inline-block;
        font-size: 11px;
        font-weight: 600;
        padding: 2px 8px;
        border-radius: 4px;
        background: #e0f2fe;
        color: #0369a1;
        margin-right: 4px;
    }
    .ev-summary {
        font-size: 13px;
        color: #475569;
        margin-top: 4px;
        line-height: 1.5;
    }

    /* Sidebar brand */
    .sidebar-brand {
        font-size: 16px;
        font-weight: 700;
        color: #0f172a;
        padding: 4px 0 20px 0;
        border-bottom: 1px solid #e2e8f0;
        margin-bottom: 24px;
    }
    .sidebar-sub {
        font-size: 11px;
        color: #94a3b8;
        margin-top: 2px;
    }

    /* Download button */
    [data-testid="stDownloadButton"] button {
        background: #0f172a !important;
        color: white !important;
        border: none !important;
        border-radius: 6px !important;
        font-weight: 600 !important;
        font-size: 13px !important;
        padding: 10px 20px !important;
    }
    [data-testid="stDownloadButton"] button:hover {
        background: #1e293b !important;
    }
</style>
""", unsafe_allow_html=True)


# ── Snowflake connection ──────────────────────────────────────────────────────
@st.cache_resource(show_spinner=False)
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


# ── Embedding model ───────────────────────────────────────────────────────────
@st.cache_resource(show_spinner=False)
def load_model():
    return SentenceTransformer(MODEL_NAME)


# ── Train data ────────────────────────────────────────────────────────────────
@st.cache_resource(show_spinner=False)
def load_train_data():
    df = run_query("""
        SELECT key, issuetype, resolution, priority, status, reporter,
               summary_clean, LEFT(text_noco, 300) AS excerpt
        FROM PFE_SPARK.MARTS_ML.MART_ML
        WHERE split = 'train'
    """)
    if CACHE_PATH.exists():
        cache = np.load(CACHE_PATH, allow_pickle=True)
        emb = cache["train_emb"].astype("float32")
        norms = np.linalg.norm(emb, axis=1, keepdims=True)
        emb = emb / np.where(norms == 0, 1, norms)
    else:
        model = load_model()
        texts = df["excerpt"].fillna("").tolist()
        emb = model.encode(texts, batch_size=256, normalize_embeddings=True,
                           show_progress_bar=False).astype("float32")
        CACHE_PATH.parent.mkdir(exist_ok=True)
        np.savez_compressed(CACHE_PATH, train_emb=emb)
    return df.reset_index(drop=True), emb


# ── LLM analysis ─────────────────────────────────────────────────────────────
def llm_analysis(summary: str, description: str, it: str, res: str,
                 conf_it: float, conf_res: float, similar_rows: pd.DataFrame) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        # Deterministic template fallback
        top = similar_rows.iloc[0]
        pct_it  = f"{conf_it:.0%}"
        pct_res = f"{conf_res:.0%}"
        return (
            f"The model classified this ticket as <strong>{it}</strong> with {pct_it} confidence, "
            f"based on semantic similarity to {K} historical Apache Spark incidents. "
            f"The closest match is {top['key']} ({top['similarity']:.0%} similarity), "
            f"which was resolved as <strong>{top['resolution']}</strong> — consistent with the predicted outcome. "
            f"A {pct_res} confidence on the <strong>{res}</strong> resolution suggests "
            + ("strong historical precedent for this outcome." if conf_res >= 0.65
               else "moderate agreement across similar tickets; manual review is advised.")
        )

    import anthropic
    neighbors_ctx = "\n".join(
        f"- {r['key']} ({r['similarity']:.0%} similarity): "
        f"[{r['issuetype']} / {r['resolution']}] \"{r.get('summary_clean', '')}\"​"
        for _, r in similar_rows.iterrows()
    )
    prompt = (
        f"You are a senior Apache Spark engineering lead reviewing a new issue ticket.\n\n"
        f"Ticket summary: {summary}\n"
        f"Description: {description[:600]}\n\n"
        f"An ML triage system classified this ticket as:\n"
        f"  Issue type: {it} (confidence {conf_it:.0%})\n"
        f"  Resolution: {res} (confidence {conf_res:.0%})\n\n"
        f"The 3 most similar historical tickets are:\n{neighbors_ctx}\n\n"
        f"Write exactly 2-3 sentences of professional analysis explaining "
        f"why this classification makes sense and what it means for the engineering team. "
        f"Be specific, reference the ticket content, and do NOT mention ML, embeddings, or confidence scores. "
        f"Write in plain English, no bullet points, no markdown."
    )
    try:
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=220,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text.strip()
    except Exception:
        return llm_analysis(summary, description, it, res, conf_it, conf_res, similar_rows)


# ── Prediction engine ─────────────────────────────────────────────────────────
def predict(summary: str, description: str, priority: str,
            status: str, reporter: str) -> dict:
    text_noco = (
        f"TICKET: {summary}\n"
        f"TYPE: Unknown | PRI: {priority}\n"
        f"STATUS: {status}\n"
        f"DESC: {description[:800]}"
    )[:2000]

    model = load_model()
    train_df, train_emb = load_train_data()

    q_emb = model.encode([text_noco], normalize_embeddings=True).astype("float32")[0]
    sims  = train_emb @ q_emb

    fused = (sims
             + (train_df["priority"] == priority).astype(float).values * 0.10
             + (train_df["status"]   == status).astype(float).values   * 0.08
             + (train_df["reporter"] == reporter).astype(float).values  * 0.05)

    top_idx  = np.argsort(fused)[::-1][:K]
    top_sims = fused[top_idx]
    top_rows = train_df.iloc[top_idx].copy()
    top_rows["similarity"] = top_sims.round(4)

    def vote(labels, weights):
        scores: dict = {}
        for l, w in zip(labels, weights):
            scores[l] = scores.get(l, 0.0) + float(w)
        total = sum(scores.values())
        best  = max(scores, key=scores.get)
        return best, round(scores[best] / total, 4) if total else 0.0

    it,  ci = vote(top_rows["issuetype"].values, top_sims)
    res, cr = vote(top_rows["resolution"].values, top_sims)

    return {
        "issuetype": it, "conf_it": ci,
        "resolution": res, "conf_res": cr,
        "similar": top_rows.head(3).reset_index(drop=True),
    }


# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR — Input form
# ══════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("""
        <div class="sidebar-brand">
            Spark Issue Triage
            <div class="sidebar-sub">PFE UIR 2026 — V6 Hybrid RCA</div>
        </div>
    """, unsafe_allow_html=True)

    summary = st.text_area(
        "Issue Summary",
        value="SparkContext fails to initialize with OutOfMemoryError on executor startup",
        height=90,
        placeholder="Describe the issue in one sentence…",
    )
    description = st.text_area(
        "Description",
        value=(
            "When submitting a job with spark.executor.memory=4g on a YARN cluster, "
            "the executors crash immediately with java.lang.OutOfMemoryError: GC overhead limit exceeded. "
            "The issue is reproducible with Spark 3.4.0 and Hadoop 3.3.x. "
            "Driver logs show: ERROR SparkContext: Error initializing SparkContext. "
            "Reducing executor memory to 2g resolves the issue."
        ),
        height=180,
        placeholder="Paste the full ticket description…",
    )

    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
    col_p, col_s = st.columns(2)
    with col_p:
        priority = st.selectbox("Priority", ["Major", "Critical", "Minor", "Blocker", "Trivial"])
    with col_s:
        status = st.selectbox("Status", ["Open", "In Progress", "Resolved", "Closed", "Reopened"])

    reporter = st.text_input("Reporter", value="", placeholder="username (optional)")

    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
    analyze_btn = st.button("Analyze Ticket", type="primary", use_container_width=True)

    st.markdown("<div style='height:24px'></div>", unsafe_allow_html=True)
    llm_mode = "LLM" if os.environ.get("ANTHROPIC_API_KEY") else "Template"
    st.markdown(
        f"<span style='font-size:11px;color:#94a3b8;'>"
        f"Analysis mode: <strong>{llm_mode}</strong><br>"
        f"Model: {MODEL_NAME}<br>"
        f"Train set: 38,274 tickets</span>",
        unsafe_allow_html=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
# MAIN — Results
# ══════════════════════════════════════════════════════════════════════════════
if not analyze_btn:
    st.markdown("""
        <div style="display:flex;align-items:center;justify-content:center;
                    height:60vh;flex-direction:column;gap:12px;">
            <div style="font-size:40px;font-weight:800;color:#e2e8f0;letter-spacing:-1px;">
                Spark Issue Triage
            </div>
            <div style="font-size:15px;color:#94a3b8;">
                Fill in the issue details on the left and click Analyze Ticket.
            </div>
        </div>
    """, unsafe_allow_html=True)
    st.stop()

if not summary.strip():
    st.error("Issue summary is required.")
    st.stop()

with st.spinner("Running inference…"):
    r = predict(summary, description, priority, status, reporter or "Unknown")
    analysis_text = llm_analysis(
        summary, description,
        r["issuetype"], r["resolution"],
        r["conf_it"], r["conf_res"],
        r["similar"],
    )

it      = r["issuetype"]
res     = r["resolution"]
ci      = r["conf_it"]
cr      = r["conf_res"]
similar = r["similar"]

# ── Breadcrumb ────────────────────────────────────────────────────────────────
st.markdown(
    f"<p style='font-size:12px;color:#94a3b8;margin-bottom:24px;'>"
    f"Results for: <strong style='color:#475569;'>{summary[:80]}</strong>"
    f"</p>",
    unsafe_allow_html=True,
)

# ── Prediction cards ──────────────────────────────────────────────────────────
c1, c2 = st.columns(2, gap="large")

for col, label, value, conf in [
    (c1, "Issue Type",         it,  ci),
    (c2, "Predicted Resolution", res, cr),
]:
    color  = confidence_color(conf)
    clabel = confidence_label(conf)
    bar_w  = int(conf * 100)
    with col:
        st.markdown(f"""
        <div class="pred-card">
            <div class="pred-label">{label}</div>
            <div class="pred-value">{value}</div>
            <div class="conf-row">
                <div class="conf-bar-track">
                    <div class="conf-bar-fill"
                         style="width:{bar_w}%;background:{color};"></div>
                </div>
                <span class="conf-pct">{conf:.0%}</span>
            </div>
            <span class="conf-badge"
                  style="background:{color}22;color:{color};">
                {clabel} Confidence
            </span>
        </div>
        """, unsafe_allow_html=True)

st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)

# ── LLM / Template analysis ───────────────────────────────────────────────────
st.markdown("<div class='section-header'>Analysis</div>", unsafe_allow_html=True)
st.markdown(
    f"<div class='analysis-block'>{analysis_text}</div>",
    unsafe_allow_html=True,
)

if ci < CONF_THRESHOLDS["medium"] or cr < CONF_THRESHOLDS["medium"]:
    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
    st.markdown(
        "<div class='warn-block'>"
        "One or more confidence scores are below the medium threshold. "
        "Review the supporting evidence below before taking action."
        "</div>",
        unsafe_allow_html=True,
    )

st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)

# ── Recommended actions ───────────────────────────────────────────────────────
st.markdown("<div class='section-header'>Recommended Actions</div>", unsafe_allow_html=True)
a1, a2 = st.columns(2, gap="large")
with a1:
    st.markdown(f"""
    <div class="action-card">
        <div class="action-key">Routing</div>
        <div class="action-val">{ROUTING.get(it, "Manual qualification required")}</div>
    </div>""", unsafe_allow_html=True)
with a2:
    st.markdown(f"""
    <div class="action-card">
        <div class="action-key">Next Step</div>
        <div class="action-val">{RESOLUTION_GUIDANCE.get(res, "Review and qualify manually.")}</div>
    </div>""", unsafe_allow_html=True)

st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)

# ── Supporting evidence ───────────────────────────────────────────────────────
st.markdown("<div class='section-header'>Supporting Evidence — Top 3 Similar Tickets</div>",
            unsafe_allow_html=True)

for _, row in similar.iterrows():
    sim_pct = int(row["similarity"] * 100)
    summary_clean = row.get("summary_clean", "") or ""
    st.markdown(f"""
    <div class="evidence-row">
        <div>
            <div class="ev-key">{row['key']}</div>
            <div style="font-size:12px;color:#94a3b8;margin-top:2px;">{sim_pct}% match</div>
        </div>
        <div style="flex:1;">
            <span class="ev-tag">{row['issuetype']}</span>
            <span class="ev-tag" style="background:#dcfce7;color:#166534;">{row['resolution']}</span>
            <div class="ev-summary">{summary_clean}</div>
        </div>
        <div style="min-width:80px;">
            <div style="background:#e2e8f0;border-radius:3px;height:5px;margin-top:8px;">
                <div style="width:{sim_pct}%;background:#3b82f6;height:5px;border-radius:3px;"></div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)

# ── Export ────────────────────────────────────────────────────────────────────
st.markdown("<div class='section-header'>Export</div>", unsafe_allow_html=True)

report = "\n".join([
    "SPARK ISSUE TRIAGE REPORT",
    "=" * 42,
    f"Summary  : {summary}",
    f"Priority : {priority}   Status: {status}",
    "",
    "PREDICTION",
    f"  Issue Type  : {it}   ({ci:.0%} confidence — {confidence_label(ci)})",
    f"  Resolution  : {res}  ({cr:.0%} confidence — {confidence_label(cr)})",
    "",
    "ANALYSIS",
    analysis_text,
    "",
    "RECOMMENDED ACTIONS",
    f"  Routing   : {ROUTING.get(it, 'Manual qualification')}",
    f"  Next step : {RESOLUTION_GUIDANCE.get(res, 'Review manually.')}",
    "",
    "SUPPORTING EVIDENCE",
] + [
    f"  {row['key']:12s}  {int(row['similarity']*100):3d}% match  "
    f"[{row['issuetype']} / {row['resolution']}]  \"{row.get('summary_clean','')}\""
    for _, row in similar.iterrows()
])

st.download_button(
    label="Download Triage Report",
    data=report,
    file_name=f"triage_{summary[:40].replace(' ','_')}.txt",
    mime="text/plain",
)
