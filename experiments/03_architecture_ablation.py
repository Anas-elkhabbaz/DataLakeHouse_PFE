"""
Ablation 03 — Architecture ablation (6 configurations)
Compares: metadata-only, single NOCO, single NOCO+boost, dual+boost,
          dual+boost+changelog, full V6 (with confidence gate).
Outputs a Markdown table and CSV, with bootstrap 95 % CI on Macro-F1.

Usage: python experiments/03_architecture_ablation.py
"""
import json, os, sys, time
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from sklearn.metrics import accuracy_score, f1_score
import snowflake.connector

sys.path.insert(0, str(Path(__file__).parent.parent))
from load.retrieval import (
    CHANGELOG_FEATURES, QUERY_PREFIX, build_scaler,
    rrf_fuse, metadata_boost, changelog_sim, fuse_scores, route,
)

load_dotenv()

RESULTS    = Path(__file__).parent.parent / "results"
ABLATIONS  = RESULTS / "ablations"
ABLATIONS.mkdir(exist_ok=True)

CACHE_NOCO  = RESULTS / "embeddings_noco.npz"
CACHE_RICH  = RESULTS / "embeddings_rich.npz"
K           = 15
RRF_TOP     = 30
N_BOOTSTRAP = 500
RNG         = np.random.default_rng(42)

# ── Load data ────────────────────────────────────────────────────────────────
print("Connecting to Snowflake …")
conn = snowflake.connector.connect(
    account   = os.environ["SNOWFLAKE_ACCOUNT"],
    user      = os.environ["SNOWFLAKE_USER"],
    password  = os.environ["SNOWFLAKE_PASSWORD"],
    role      = os.environ.get("SNOWFLAKE_ROLE",      "SYSADMIN"),
    warehouse = os.environ.get("SNOWFLAKE_WAREHOUSE", "PFE_WH"),
    database  = os.environ.get("SNOWFLAKE_DATABASE",  "PFE_SPARK"),
)
cur = conn.cursor()
cur.execute(f"""
    SELECT key, split, issuetype, resolution, text_noco, text_rich,
           priority, status, reporter,
           {', '.join(CHANGELOG_FEATURES)}
    FROM PFE_SPARK.MARTS_ML.MART_ML
    WHERE split IN ('train', 'validation')
""")
rows = cur.fetchall()
cols = [d[0].lower() for d in cur.description]
df   = pd.DataFrame(rows, columns=cols)
df[CHANGELOG_FEATURES] = df[CHANGELOG_FEATURES].fillna(0).astype(float)
conn.close()

train = df[df["split"] == "train"].reset_index(drop=True)
val   = df[df["split"] == "validation"].reset_index(drop=True)

# ── Load / encode embeddings ─────────────────────────────────────────────────
print("Loading embeddings …")
from sentence_transformers import SentenceTransformer
emb_noco = np.load(CACHE_NOCO)["train_emb"].astype("float32")
emb_rich = np.load(CACHE_RICH)["train_emb"].astype("float32")

model = SentenceTransformer("BAAI/bge-large-en-v1.5")
val_emb_noco = model.encode(
    (QUERY_PREFIX + val["text_noco"].fillna("")).tolist(),
    batch_size=32, normalize_embeddings=True, show_progress_bar=True,
).astype("float32")
val_emb_rich = model.encode(
    (QUERY_PREFIX + val["text_rich"].fillna("")).tolist(),
    batch_size=32, normalize_embeddings=True, show_progress_bar=True,
).astype("float32")

scaler = build_scaler(train)
train_cl_std = scaler.transform(train[CHANGELOG_FEATURES].fillna(0).values)
val_cl_raw   = val[CHANGELOG_FEATURES].fillna(0).values

# ── Precompute scores that are shared across configs ──────────────────────────
print("Precomputing similarity matrices …")
# NOCO-only cosine scores (n_val × n_train)
scores_noco_all = (emb_noco @ val_emb_noco.T).T   # (n_val, n_train)
scores_rich_all = (emb_rich @ val_emb_rich.T).T

# Changelog metadata for all val tickets (standardized)
val_cl_std = scaler.transform(val_cl_raw)

# ── Bootstrap CI helper ───────────────────────────────────────────────────────

def bootstrap_ci(y_true, y_pred, labels, n=N_BOOTSTRAP):
    """95 % bootstrap CI on macro-F1."""
    y_true = np.array(y_true)
    y_pred = np.array(y_pred)
    scores = []
    for _ in range(n):
        idx = RNG.integers(0, len(y_true), len(y_true))
        scores.append(f1_score(y_true[idx], y_pred[idx], labels=labels,
                                average="macro", zero_division=0))
    scores = np.array(scores)
    return np.percentile(scores, 2.5), np.percentile(scores, 97.5)

# ── Configuration runners ─────────────────────────────────────────────────────

def run_config(cfg_name: str, cfg_fn) -> dict:
    t0 = time.time()
    print(f"  [{cfg_name}] …")
    pred_it, pred_res, routings = cfg_fn()
    elapsed = time.time() - t0

    it_labels  = sorted(val["issuetype"].unique())
    res_labels = sorted(val["resolution"].unique())

    acc_it  = accuracy_score(val["issuetype"], pred_it)
    mf1_it  = f1_score(val["issuetype"], pred_it, labels=it_labels, average="macro", zero_division=0)
    acc_res = accuracy_score(val["resolution"], pred_res)
    mf1_res = f1_score(val["resolution"], pred_res, labels=res_labels, average="macro", zero_division=0)

    ci_lo_it,  ci_hi_it  = bootstrap_ci(val["issuetype"], pred_it, it_labels)
    ci_lo_res, ci_hi_res = bootstrap_ci(val["resolution"], pred_res, res_labels)

    pct_direct = 100.0 * sum(r == "DIRECT" for r in routings) / len(routings) if routings else float("nan")

    return {
        "Configuration":   cfg_name,
        "Acc_IT":          round(acc_it,  4),
        "MF1_IT":          round(mf1_it,  4),
        "CI95_IT":         f"[{ci_lo_it:.3f}, {ci_hi_it:.3f}]",
        "Acc_Res":         round(acc_res, 4),
        "MF1_Res":         round(mf1_res, 4),
        "CI95_Res":        f"[{ci_lo_res:.3f}, {ci_hi_res:.3f}]",
        "DIRECT%":         round(pct_direct, 1),
        "Time_s":          round(elapsed, 1),
    }

# ── Config 1: Metadata-only baseline ─────────────────────────────────────────

def cfg1_metadata_only():
    pred_it, pred_res = [], []
    priority_vals = train["priority"].fillna("Unknown").values
    it_vals       = train["issuetype"].values
    res_vals      = train["resolution"].values
    for i in range(len(val)):
        qp   = val.at[i, "priority"]
        mask = priority_vals == qp
        if mask.sum() == 0:
            mask = np.ones(len(train), dtype=bool)
        from collections import Counter
        pred_it.append(Counter(it_vals[mask]).most_common(1)[0][0])
        pred_res.append(Counter(res_vals[mask]).most_common(1)[0][0])
    return pred_it, pred_res, []

# ── Config 2: Single NOCO, no boost ─────────────────────────────────────────

def cfg2_noco_only():
    pred_it, pred_res = [], []
    for i in range(len(val)):
        sn  = scores_noco_all[i]
        idx = np.argsort(sn)[::-1][:K]
        w   = sn[idx]
        def vote(labels, ws):
            s = {}
            for l, ww in zip(labels, ws): s[l] = s.get(l, 0.0) + float(ww)
            return max(s, key=s.get)
        pred_it.append(vote(train.iloc[idx]["issuetype"].tolist(), w))
        pred_res.append(vote(train.iloc[idx]["resolution"].tolist(), w))
    return pred_it, pred_res, []

# ── Config 3: Single NOCO + metadata boost ──────────────────────────────────

def cfg3_noco_meta():
    pred_it, pred_res = [], []
    for i in range(len(val)):
        sn   = scores_noco_all[i]
        top  = np.argsort(sn)[::-1][:RRF_TOP]
        meta = metadata_boost(
            val.at[i, "priority"], val.at[i, "status"], val.at[i, "reporter"],
            train.iloc[top]["priority"].fillna("").tolist(),
            train.iloc[top]["status"].fillna("").tolist(),
            train.iloc[top]["reporter"].fillna("").tolist(),
        )
        final = sn[top] + 0.15 * meta
        best  = np.argsort(final)[::-1][:K]
        nb    = train.iloc[top[best]]
        w     = final[best]
        def vote(labels, ws):
            s = {}
            for l, ww in zip(labels, ws): s[l] = s.get(l, 0.0) + float(ww)
            return max(s, key=s.get)
        pred_it.append(vote(nb["issuetype"].tolist(), w))
        pred_res.append(vote(nb["resolution"].tolist(), w))
    return pred_it, pred_res, []

# ── Config 4: Dual NOCO+RICH + metadata boost ────────────────────────────────

def cfg4_dual_meta():
    pred_it, pred_res = [], []
    for i in range(len(val)):
        sn = scores_noco_all[i]
        sr = scores_rich_all[i]
        top, rrf = rrf_fuse(sn, sr, top_k=RRF_TOP)
        meta = metadata_boost(
            val.at[i, "priority"], val.at[i, "status"], val.at[i, "reporter"],
            train.iloc[top]["priority"].fillna("").tolist(),
            train.iloc[top]["status"].fillna("").tolist(),
            train.iloc[top]["reporter"].fillna("").tolist(),
        )
        final = fuse_scores(rrf, meta, np.zeros(RRF_TOP))
        best  = np.argsort(final)[::-1][:K]
        nb    = train.iloc[top[best]]
        w     = final[best]
        def vote(labels, ws):
            s = {}
            for l, ww in zip(labels, ws): s[l] = s.get(l, 0.0) + float(ww)
            return max(s, key=s.get)
        pred_it.append(vote(nb["issuetype"].tolist(), w))
        pred_res.append(vote(nb["resolution"].tolist(), w))
    return pred_it, pred_res, []

# ── Config 5: Dual + metadata + changelog re-ranker ──────────────────────────

def cfg5_dual_meta_cl():
    pred_it, pred_res = [], []
    for i in range(len(val)):
        sn = scores_noco_all[i]
        sr = scores_rich_all[i]
        top, rrf = rrf_fuse(sn, sr, top_k=RRF_TOP)
        meta = metadata_boost(
            val.at[i, "priority"], val.at[i, "status"], val.at[i, "reporter"],
            train.iloc[top]["priority"].fillna("").tolist(),
            train.iloc[top]["status"].fillna("").tolist(),
            train.iloc[top]["reporter"].fillna("").tolist(),
        )
        q_cl   = val_cl_std[i:i+1]
        cand_cl = train_cl_std[top]
        cl     = changelog_sim(q_cl, cand_cl)
        final  = fuse_scores(rrf, meta, cl)
        best   = np.argsort(final)[::-1][:K]
        nb     = train.iloc[top[best]]
        w      = final[best]
        def vote(labels, ws):
            s = {}
            for l, ww in zip(labels, ws): s[l] = s.get(l, 0.0) + float(ww)
            return max(s, key=s.get)
        pred_it.append(vote(nb["issuetype"].tolist(), w))
        pred_res.append(vote(nb["resolution"].tolist(), w))
    return pred_it, pred_res, []

# ── Config 6: Full V6 — above + confidence gate ──────────────────────────────

def cfg6_full_v6():
    """Same as cfg5 but with routing tags (no actual LLM call in this ablation)."""
    pred_it, pred_res, routings = [], [], []
    for i in range(len(val)):
        sn = scores_noco_all[i]
        sr = scores_rich_all[i]
        top, rrf = rrf_fuse(sn, sr, top_k=RRF_TOP)
        meta = metadata_boost(
            val.at[i, "priority"], val.at[i, "status"], val.at[i, "reporter"],
            train.iloc[top]["priority"].fillna("").tolist(),
            train.iloc[top]["status"].fillna("").tolist(),
            train.iloc[top]["reporter"].fillna("").tolist(),
        )
        q_cl   = val_cl_std[i:i+1]
        cand_cl = train_cl_std[top]
        cl      = changelog_sim(q_cl, cand_cl)
        final   = fuse_scores(rrf, meta, cl)
        best    = np.argsort(final)[::-1][:K]
        nb      = train.iloc[top[best]]
        w       = final[best]

        def vote_full(labels, ws):
            s = {}
            for l, ww in zip(labels, ws): s[l] = s.get(l, 0.0) + float(ww)
            total = sum(s.values())
            sv = sorted(s.values(), reverse=True)
            best_lbl  = max(s, key=s.get)
            l0_conf   = sv[0] / total if total else 0
            margin    = (sv[0] - sv[1]) / total if len(sv) > 1 and total else 0
            return best_lbl, l0_conf, margin

        it_lbl,  l0_it,  m_it  = vote_full(nb["issuetype"].tolist(), w)
        res_lbl, l0_res, m_res = vote_full(nb["resolution"].tolist(), w)
        pred_it.append(it_lbl)
        pred_res.append(res_lbl)
        # Routing based on issuetype confidence (primary prediction)
        routings.append(route(l0_it, m_it))
    return pred_it, pred_res, routings


# ── Run all configurations ────────────────────────────────────────────────────
cfgs = [
    ("1. Metadata-only baseline",          cfg1_metadata_only),
    ("2. Single NOCO, no boost",           cfg2_noco_only),
    ("3. Single NOCO + metadata boost",    cfg3_noco_meta),
    ("4. Dual NOCO+RICH + metadata boost", cfg4_dual_meta),
    ("5. Dual + metadata + changelog",     cfg5_dual_meta_cl),
    ("6. Full V6 (+ confidence gate)",     cfg6_full_v6),
]

rows = []
for name, fn in cfgs:
    rows.append(run_config(name, fn))

out_df = pd.DataFrame(rows)
out_df.to_csv(ABLATIONS / "architecture_ablation.csv", index=False)
print(f"\nSaved → {ABLATIONS / 'architecture_ablation.csv'}")

# ── Markdown table ────────────────────────────────────────────────────────────
md_lines = [
    "# Architecture Ablation Results\n",
    f"Val set size: {len(val):,} tickets | Bootstrap CIs: n={N_BOOTSTRAP}\n",
    "",
    "| Configuration | Acc IT | MF1 IT | CI95 IT | Acc Res | MF1 Res | CI95 Res | DIRECT% | Time (s) |",
    "|---|---|---|---|---|---|---|---|---|",
]
for _, r in out_df.iterrows():
    md_lines.append(
        f"| {r['Configuration']} "
        f"| {r['Acc_IT']:.4f} "
        f"| {r['MF1_IT']:.4f} "
        f"| {r['CI95_IT']} "
        f"| {r['Acc_Res']:.4f} "
        f"| {r['MF1_Res']:.4f} "
        f"| {r['CI95_Res']} "
        f"| {r['DIRECT%']} "
        f"| {r['Time_s']} |"
    )
md_text = "\n".join(md_lines)

md_path = ABLATIONS / "03_architecture_ablation.md"
md_path.write_text(md_text, encoding="utf-8")
print(f"Markdown → {md_path}")
print("\n" + md_text)
