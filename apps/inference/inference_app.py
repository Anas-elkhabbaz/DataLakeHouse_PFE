"""
Spark Issue Triage System — V6 Hybrid RCA Inference Interface
PFE UIR 2026

Launch: streamlit run apps/inference/inference_app.py
"""

import json
import math
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st
import snowflake.connector
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer

# Make load/ importable (works both locally and in Docker at /app)
_APP_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_APP_ROOT))

load_dotenv()

ROOT        = _APP_ROOT
CACHE_NOCO  = ROOT / "results" / "embeddings_noco.npz"
CACHE_RICH  = ROOT / "results" / "embeddings_rich.npz"
META_PATH   = ROOT / "results" / "embeddings_meta.json"
FIX_CACHE   = ROOT / "results" / "fix_summaries.json"

EMBEDDING_MODEL = "BAAI/bge-large-en-v1.5"
QUERY_PREFIX    = "Represent this sentence for searching relevant passages: "
K_FINAL         = 15
RRF_TOP         = 30

CHANGELOG_FEATURES = [
    "n_status_changes", "n_priority_changes", "n_assignee_changes",
    "n_resolution_changes", "was_escalated", "was_deescalated",
    "n_people_involved", "n_total_changes",
]

ROUTING_GUIDANCE = {
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

CONF_HIGH   = 0.65
CONF_MEDIUM = 0.45


def conf_color(c: float) -> str:
    return "#22c55e" if c >= CONF_HIGH else ("#f59e0b" if c >= CONF_MEDIUM else "#ef4444")


def conf_label(c: float) -> str:
    return "High" if c >= CONF_HIGH else ("Medium" if c >= CONF_MEDIUM else "Low")


# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Spark Issue Triage",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    [data-testid="stAppViewContainer"] { background: #ffffff; }
    [data-testid="stSidebar"] { background:#f8fafc; border-right:1px solid #e2e8f0; }
    .block-container { padding-top:2rem; padding-bottom:2rem; }
    #MainMenu,footer,header { visibility:hidden; }

    .pred-card {
        background:#f8fafc; border:1px solid #e2e8f0; border-radius:10px;
        padding:28px 24px; height:100%;
    }
    .pred-label {
        font-size:11px; font-weight:700; letter-spacing:.1em; color:#94a3b8;
        text-transform:uppercase; margin-bottom:6px;
    }
    .pred-value { font-size:28px; font-weight:700; color:#0f172a; margin-bottom:14px; line-height:1.2; }
    .conf-row { display:flex; align-items:center; gap:10px; margin-top:4px; }
    .conf-bar-track { flex:1; background:#e2e8f0; border-radius:4px; height:6px; }
    .conf-bar-fill { height:6px; border-radius:4px; }
    .conf-pct { font-size:13px; font-weight:600; color:#334155; min-width:36px; }
    .conf-badge { display:inline-block; font-size:11px; font-weight:600; padding:2px 8px;
                  border-radius:20px; margin-top:8px; }

    .routing-badge { display:inline-block; font-size:12px; font-weight:700; padding:4px 12px;
                     border-radius:20px; letter-spacing:.05em; }

    .section-header {
        font-size:11px; font-weight:700; letter-spacing:.1em; color:#94a3b8;
        text-transform:uppercase; margin-bottom:14px; margin-top:6px;
    }
    .analysis-block {
        background:#f0f7ff; border-left:3px solid #3b82f6; border-radius:0 8px 8px 0;
        padding:18px 20px; font-size:15px; line-height:1.7; color:#1e293b;
    }
    .warn-block {
        background:#fffbeb; border-left:3px solid #f59e0b; border-radius:0 8px 8px 0;
        padding:14px 18px; font-size:14px; color:#92400e;
    }
    .action-card {
        background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; padding:18px 20px;
    }
    .action-key { font-size:11px; font-weight:700; letter-spacing:.08em; color:#94a3b8;
                  text-transform:uppercase; margin-bottom:6px; }
    .action-val { font-size:14px; font-weight:500; color:#1e293b; line-height:1.5; }

    .evidence-row {
        display:flex; align-items:flex-start; gap:16px; padding:16px 0;
        border-bottom:1px solid #f1f5f9;
    }
    .ev-key { font-family:'Courier New',monospace; font-size:13px; font-weight:700;
              color:#3b82f6; min-width:110px; }
    .ev-sim { font-size:13px; font-weight:600; color:#334155; min-width:46px; }
    .ev-tag { display:inline-block; font-size:11px; font-weight:600; padding:2px 8px;
              border-radius:4px; background:#e0f2fe; color:#0369a1; margin-right:4px; }
    .ev-summary { font-size:13px; color:#475569; margin-top:4px; line-height:1.5; }
    .ev-fix { font-size:12px; color:#6b7280; margin-top:4px; font-style:italic; line-height:1.4; }

    .sidebar-brand { font-size:16px; font-weight:700; color:#0f172a;
                     padding:4px 0 20px 0; border-bottom:1px solid #e2e8f0; margin-bottom:24px; }
    .sidebar-sub { font-size:11px; color:#94a3b8; margin-top:2px; }

    [data-testid="stDownloadButton"] button {
        background:#0f172a !important; color:white !important; border:none !important;
        border-radius:6px !important; font-weight:600 !important;
        font-size:13px !important; padding:10px 20px !important;
    }
</style>
""", unsafe_allow_html=True)


# ── Snowflake ─────────────────────────────────────────────────────────────────
@st.cache_resource(show_spinner=False)
def get_conn():
    try:
        return snowflake.connector.connect(
            account   = os.environ["SNOWFLAKE_ACCOUNT"],
            user      = os.environ["SNOWFLAKE_USER"],
            password  = os.environ["SNOWFLAKE_PASSWORD"],
            role      = os.environ.get("SNOWFLAKE_ROLE",      "SYSADMIN"),
            warehouse = os.environ.get("SNOWFLAKE_WAREHOUSE", "PFE_WH"),
            database  = os.environ.get("SNOWFLAKE_DATABASE",  "PFE_SPARK"),
            schema    = "MARTS_ML",
        )
    except Exception as e:
        st.error(f"Snowflake connection failed: {e}")
        st.stop()


def run_query(sql: str) -> pd.DataFrame:
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute(sql)
        cols = [d[0].lower() for d in cur.description]
        return pd.DataFrame(cur.fetchall(), columns=cols)


# ── Model + embeddings ────────────────────────────────────────────────────────
@st.cache_resource(show_spinner="Loading embedding model…")
def load_model():
    return SentenceTransformer(EMBEDDING_MODEL)


@st.cache_resource(show_spinner="Loading training index…")
def load_train_index():
    """Load train DataFrame + both embedding matrices."""
    df = run_query(f"""
        SELECT key, issuetype, resolution, priority, status, reporter,
               summary_clean, text_noco,
               {', '.join(CHANGELOG_FEATURES)}
        FROM PFE_SPARK.MARTS_ML.MART_ML
        WHERE split = 'train'
    """)
    df[CHANGELOG_FEATURES] = df[CHANGELOG_FEATURES].fillna(0).astype(float)

    # Load or compute NOCO embeddings
    if CACHE_NOCO.exists():
        emb_noco = np.load(CACHE_NOCO)["train_emb"].astype("float32")
    else:
        st.warning("embeddings_noco.npz not found — computing on the fly (slow). "
                   "Run load/run_ml_pipeline.py first.")
        m = load_model()
        emb_noco = m.encode(df["text_noco"].fillna("").tolist(),
                            batch_size=16, normalize_embeddings=True,
                            show_progress_bar=False).astype("float32")
        CACHE_NOCO.parent.mkdir(exist_ok=True)
        np.savez_compressed(CACHE_NOCO, train_emb=emb_noco)

    # Load or reuse RICH embeddings (same noco if rich cache missing)
    if CACHE_RICH.exists():
        emb_rich = np.load(CACHE_RICH)["train_emb"].astype("float32")
    else:
        emb_rich = emb_noco  # degrade gracefully

    return df.reset_index(drop=True), emb_noco, emb_rich


@st.cache_data(show_spinner=False)
def load_fix_summaries() -> dict:
    if FIX_CACHE.exists():
        return json.loads(FIX_CACHE.read_text(encoding="utf-8"))
    return {}


# ── Retrieval helpers ─────────────────────────────────────────────────────────
def _rrf_fuse(s_noco, s_rich, k=60, top_k=30):
    n = len(s_noco)
    r_n = (n - 1 - (-s_noco).argsort().argsort()).astype(float) + 1
    r_r = (n - 1 - (-s_rich).argsort().argsort()).astype(float) + 1
    rrf = 1.0 / (k + r_n) + 1.0 / (k + r_r)
    top = np.argpartition(rrf, -top_k)[-top_k:]
    return top[np.argsort(rrf[top])[::-1]], rrf[top[np.argsort(rrf[top])[::-1]]]


def _changelog_sim(q_cl, cand_cl):
    diff = cand_cl - q_cl
    return 1.0 / (1.0 + np.linalg.norm(diff, axis=1))


def _weighted_vote(labels, weights):
    scores: dict = {}
    for lbl, w in zip(labels, weights):
        scores[lbl] = scores.get(lbl, 0.0) + float(w)
    total = sum(scores.values())
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    best, best_v = ranked[0]
    runner_up = ranked[1][1] if len(ranked) > 1 else 0.0
    l0_conf = best_v / total if total else 0.0
    margin  = (best_v - runner_up) / total if total else 0.0
    return best, l0_conf, margin


def _route(l0_conf, margin):
    return "DIRECT" if (l0_conf >= CONF_HIGH and margin >= 0.10) else "LLM_REQUIRED"


# ── LLM analysis ──────────────────────────────────────────────────────────────
def llm_analysis(summary, description, it, res, ci, cr, similar_rows) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        top = similar_rows.iloc[0]
        return (
            f"The model classified this ticket as <strong>{it}</strong> "
            f"with {ci:.0%} confidence, based on semantic similarity to historical "
            f"Apache Spark incidents. The closest match is {top['key']} "
            f"({top['sim']:.0%} similarity), resolved as "
            f"<strong>{top['resolution']}</strong>. "
            + ("Strong historical precedent supports this classification."
               if cr >= CONF_HIGH
               else "Moderate confidence — consult the supporting evidence below before acting.")
        )
    import anthropic
    ctx = "\n".join(
        f"- {r['key']} [{r['issuetype']} / {r['resolution']}] \"{r.get('summary_clean','')}\""
        for _, r in similar_rows.iterrows()
    )
    prompt = (
        f"You are a senior Apache Spark engineering lead reviewing a new issue.\n\n"
        f"Summary: {summary}\nDescription: {description[:600]}\n\n"
        f"ML triage: {it} ({ci:.0%}), resolution {res} ({cr:.0%})\n"
        f"Top similar tickets:\n{ctx}\n\n"
        f"Write 2-3 sentences of professional analysis. "
        f"Be specific, reference ticket content. No markdown, no bullet points."
    )
    try:
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=220,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text.strip()
    except Exception:
        return llm_analysis(summary, description, it, res, ci, cr, similar_rows)


# ── Prediction engine ─────────────────────────────────────────────────────────
def predict(summary: str, description: str, priority: str,
            status: str, reporter: str,
            n_status_changes: int = 0, n_priority_changes: int = 0,
            n_assignee_changes: int = 0) -> dict:

    t0 = time.time()

    text_noco = (
        f"TICKET: {summary}\n"
        f"PRI: {priority}\n"
        f"STATUS: {status}\n"
        f"DESC: {description[:1500]}"
    )[:2000]
    text_rich = (
        f"TICKET: {summary}\n"
        f"PRIORITY: {priority}\n"
        f"STATUS: {status}\n"
        f"N_COMMENTS: 0\n"
        f"DESCRIPTION: {description[:2000]}\n"
        f"DISCUSSION: "
    )

    model = load_model()
    train_df, emb_noco, emb_rich = load_train_index()
    fix_cache = load_fix_summaries()

    q_noco = model.encode(QUERY_PREFIX + text_noco, normalize_embeddings=True).astype("float32")
    q_rich = model.encode(QUERY_PREFIX + text_rich, normalize_embeddings=True).astype("float32")

    s_noco = emb_noco @ q_noco
    s_rich = emb_rich @ q_rich

    top30_idx, rrf_scores = _rrf_fuse(s_noco, s_rich, top_k=RRF_TOP)
    cands = train_df.iloc[top30_idx]

    # Metadata boost
    meta = (
        0.10 * (cands["priority"].fillna("").values == priority)
      + 0.08 * (cands["status"].fillna("").values   == status)
      + 0.05 * (cands["reporter"].fillna("").values  == reporter)
    )

    # Changelog similarity
    q_cl   = np.array([[n_status_changes, n_priority_changes, n_assignee_changes,
                         0, 0, 0, 0, n_status_changes + n_priority_changes + n_assignee_changes]],
                       dtype=float)
    cand_cl = cands[CHANGELOG_FEATURES].values
    # Simple L2 distance (no scaler at inference time — use raw feature space)
    cl_sim = 1.0 / (1.0 + np.linalg.norm(cand_cl - q_cl, axis=1))

    final = 1.0 * rrf_scores + 0.15 * meta + 0.10 * cl_sim
    best_local = np.argsort(final)[::-1][:K_FINAL]
    top_idx    = top30_idx[best_local]
    top_sims   = (s_noco[top_idx] + s_rich[top_idx]) / 2.0

    top_rows = train_df.iloc[top_idx].copy()
    top_rows["sim"] = top_sims.round(4)

    it,  ci, margin_it  = _weighted_vote(top_rows["issuetype"].tolist(), top_sims)
    res, cr, margin_res = _weighted_vote(top_rows["resolution"].tolist(), top_sims)

    routing_it  = _route(ci, margin_it)
    routing_res = _route(cr, margin_res)

    # Attach fix_summaries if available
    top_rows["fix_summary"] = top_rows["key"].map(fix_cache).fillna("")

    elapsed_ms = int((time.time() - t0) * 1000)

    return {
        "issuetype":   it,  "conf_it":    round(ci, 4),
        "resolution":  res, "conf_res":   round(cr, 4),
        "routing_it":  routing_it,  "margin_it":  round(margin_it, 4),
        "routing_res": routing_res, "margin_res": round(margin_res, 4),
        "similar":     top_rows.head(5).reset_index(drop=True),
        "elapsed_ms":  elapsed_ms,
    }


# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR
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
    llm_mode = "Anthropic claude-haiku-4-5" if os.environ.get("ANTHROPIC_API_KEY") else "Template"
    st.markdown(
        f"<span style='font-size:11px;color:#94a3b8;'>"
        f"Analysis: <strong>{llm_mode}</strong><br>"
        f"Embeddings: <strong>BGE-Large-EN v1.5</strong> (1024d)<br>"
        f"Retrieval: Dual NOCO+RICH · RRF · k=15</span>",
        unsafe_allow_html=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
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

# Input validation
if len(summary.strip()) < 10:
    st.warning("Issue summary must be at least 10 characters.")
    st.stop()
if len(description.strip()) < 20:
    st.warning("Description must be at least 20 characters.")
    st.stop()

with st.spinner("Running V6 inference…"):
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

# ── Breadcrumb + latency ──────────────────────────────────────────────────────
hdr_l, hdr_r = st.columns([4, 1])
with hdr_l:
    st.markdown(
        f"<p style='font-size:12px;color:#94a3b8;margin-bottom:24px;'>"
        f"Results for: <strong style='color:#475569;'>{summary[:80]}</strong></p>",
        unsafe_allow_html=True,
    )
with hdr_r:
    st.metric("Latency", f"{r['elapsed_ms']} ms")

# ── Prediction cards ──────────────────────────────────────────────────────────
c1, c2 = st.columns(2, gap="large")
for col, label, value, conf in [
    (c1, "Issue Type",           it,  ci),
    (c2, "Predicted Resolution", res, cr),
]:
    color  = conf_color(conf)
    clabel = conf_label(conf)
    bar_w  = int(conf * 100)
    with col:
        st.markdown(f"""
        <div class="pred-card">
            <div class="pred-label">{label}</div>
            <div class="pred-value">{value}</div>
            <div class="conf-row">
                <div class="conf-bar-track">
                    <div class="conf-bar-fill" style="width:{bar_w}%;background:{color};"></div>
                </div>
                <span class="conf-pct">{conf:.0%}</span>
            </div>
            <span class="conf-badge" style="background:{color}22;color:{color};">{clabel} Confidence</span>
        </div>
        """, unsafe_allow_html=True)

# ── Routing badges ────────────────────────────────────────────────────────────
st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)
st.markdown("<div class='section-header'>Routing Decision</div>", unsafe_allow_html=True)

rb1, rb2, rb3 = st.columns([2, 2, 3])
for col, label, routing in [(rb1, "Issue Type", r["routing_it"]), (rb2, "Resolution", r["routing_res"])]:
    with col:
        color = "#22c55e" if routing == "DIRECT" else "#f59e0b"
        bg    = "#f0fdf4" if routing == "DIRECT" else "#fffbeb"
        st.markdown(
            f"<div style='font-size:11px;color:#94a3b8;margin-bottom:4px;'>{label}</div>"
            f"<span class='routing-badge' style='background:{bg};color:{color};border:1px solid {color}40;'>"
            f"{routing}</span>",
            unsafe_allow_html=True,
        )
with rb3:
    st.markdown(
        f"<div style='font-size:11px;color:#94a3b8;margin-bottom:4px;'>Confidence · Margin</div>"
        f"<div style='font-size:13px;color:#334155;'>"
        f"IT {ci:.2f} / {r['margin_it']:.2f} &nbsp;·&nbsp; "
        f"RES {cr:.2f} / {r['margin_res']:.2f}</div>",
        unsafe_allow_html=True,
    )

st.markdown("<div style='height:24px'></div>", unsafe_allow_html=True)

# ── Analysis ──────────────────────────────────────────────────────────────────
st.markdown("<div class='section-header'>Analysis</div>", unsafe_allow_html=True)
st.markdown(f"<div class='analysis-block'>{analysis_text}</div>", unsafe_allow_html=True)

if ci < CONF_MEDIUM or cr < CONF_MEDIUM:
    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
    st.markdown(
        "<div class='warn-block'>"
        "One or more confidence scores are below the medium threshold (45%). "
        "Review the supporting evidence below before taking action."
        "</div>",
        unsafe_allow_html=True,
    )

st.markdown("<div style='height:24px'></div>", unsafe_allow_html=True)

# ── Recommended actions ───────────────────────────────────────────────────────
st.markdown("<div class='section-header'>Recommended Actions</div>", unsafe_allow_html=True)
a1, a2 = st.columns(2, gap="large")
with a1:
    st.markdown(f"""
    <div class="action-card">
        <div class="action-key">Routing</div>
        <div class="action-val">{ROUTING_GUIDANCE.get(it, "Manual qualification required")}</div>
    </div>""", unsafe_allow_html=True)
with a2:
    st.markdown(f"""
    <div class="action-card">
        <div class="action-key">Next Step</div>
        <div class="action-val">{RESOLUTION_GUIDANCE.get(res, "Review and qualify manually.")}</div>
    </div>""", unsafe_allow_html=True)

st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)

# ── Supporting evidence — top 5 ───────────────────────────────────────────────
st.markdown("<div class='section-header'>Supporting Evidence — Top 5 Similar Tickets</div>",
            unsafe_allow_html=True)

for _, row in similar.iterrows():
    sim_pct = int(row["sim"] * 100)
    smry    = row.get("summary_clean", "") or ""
    fix_s   = row.get("fix_summary", "")
    st.markdown(f"""
    <div class="evidence-row">
        <div>
            <div class="ev-key">{row['key']}</div>
            <div style="font-size:12px;color:#94a3b8;margin-top:2px;">{sim_pct}% match</div>
        </div>
        <div style="flex:1;">
            <span class="ev-tag">{row['issuetype']}</span>
            <span class="ev-tag" style="background:#dcfce7;color:#166534;">{row['resolution']}</span>
            <div class="ev-summary">{smry}</div>
            {'<div class="ev-fix">' + fix_s + '</div>' if fix_s else ''}
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
    f"  Issue Type  : {it}   ({ci:.0%} — {conf_label(ci)})  [{r['routing_it']}]",
    f"  Resolution  : {res}  ({cr:.0%} — {conf_label(cr)})  [{r['routing_res']}]",
    f"  Latency     : {r['elapsed_ms']} ms",
    "",
    "ANALYSIS",
    analysis_text,
    "",
    "RECOMMENDED ACTIONS",
    f"  Routing   : {ROUTING_GUIDANCE.get(it, 'Manual qualification')}",
    f"  Next step : {RESOLUTION_GUIDANCE.get(res, 'Review manually.')}",
    "",
    "SUPPORTING EVIDENCE",
] + [
    f"  {row['key']:12s}  {int(row['sim']*100):3d}% match  "
    f"[{row['issuetype']} / {row['resolution']}]  \"{row.get('summary_clean','')}\""
    for _, row in similar.iterrows()
])

st.download_button(
    label="Download Triage Report",
    data=report,
    file_name=f"triage_{summary[:40].replace(' ','_')}.txt",
    mime="text/plain",
)
