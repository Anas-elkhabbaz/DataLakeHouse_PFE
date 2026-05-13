"""
Ablation 02 — Boost ablation (leave-one-out)
Tests what happens when each metadata/changelog boost term is removed.
Requires embeddings and mart_ml to already be fetched/cached.

Usage: python experiments/02_boost_ablation.py
"""
import json, os, sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from dotenv import load_dotenv
from sklearn.metrics import accuracy_score, f1_score
import snowflake.connector

sys.path.insert(0, str(Path(__file__).parent.parent))
from load.retrieval import (
    CHANGELOG_FEATURES, QUERY_PREFIX, build_scaler,
    rrf_fuse, metadata_boost, changelog_sim, fuse_scores,
)

load_dotenv()

RESULTS   = Path(__file__).parent.parent / "results"
ABLATIONS = RESULTS / "ablations"
ABLATIONS.mkdir(exist_ok=True)

CACHE_NOCO = RESULTS / "embeddings_noco.npz"
CACHE_RICH = RESULTS / "embeddings_rich.npz"
K          = 15   # fixed best-k from 01_k_sweep
RRF_TOP    = 30

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

# Standardize changelog features once
train_cl_std = scaler.transform(train[CHANGELOG_FEATURES].fillna(0).values)
val_cl_raw   = val[CHANGELOG_FEATURES].fillna(0).values

# ── Precompute top-30 RRF candidates per val ticket ──────────────────────────
print("Precomputing RRF top-30 …")
top30_per_val = []
rrf_per_val   = []
for i in range(len(val)):
    s_n = emb_noco @ val_emb_noco[i]
    s_r = emb_rich @ val_emb_rich[i]
    idx, rrf = rrf_fuse(s_n, s_r, top_k=RRF_TOP)
    top30_per_val.append(idx)
    rrf_per_val.append(rrf)

# ── Evaluation helper ────────────────────────────────────────────────────────

def eval_config(
    name: str,
    use_priority: bool = True,
    use_status:   bool = True,
    use_reporter: bool = True,
    use_changelog: bool = True,
) -> dict:
    """Run the full RRF + selective boost pipeline on val; return metrics."""
    pred_it  = []
    pred_res = []

    for i in range(len(val)):
        idx     = top30_per_val[i]
        rrf_sc  = rrf_per_val[i]
        cands   = train.iloc[idx]

        # Metadata boost
        qp = val.at[i, "priority"] if use_priority else "__NONE__"
        qs = val.at[i, "status"]   if use_status   else "__NONE__"
        qr = val.at[i, "reporter"] if use_reporter  else "__NONE__"
        meta = metadata_boost(
            qp, qs, qr,
            cands["priority"].fillna("").tolist(),
            cands["status"].fillna("").tolist(),
            cands["reporter"].fillna("").tolist(),
        )

        # Changelog sim
        if use_changelog:
            q_cl   = scaler.transform(val_cl_raw[i:i+1])
            cand_cl = train_cl_std[idx]
            cl = changelog_sim(q_cl, cand_cl)
        else:
            cl = np.zeros(RRF_TOP)

        final = fuse_scores(rrf_sc, meta, cl)
        best_local = np.argsort(final)[::-1][:K]
        neighbors  = cands.iloc[best_local]
        weights    = final[best_local]

        def vote(labels, ws):
            s: dict = {}
            for l, w in zip(labels, ws): s[l] = s.get(l, 0.0) + float(w)
            return max(s, key=s.get)

        pred_it.append(vote(neighbors["issuetype"].tolist(), weights))
        pred_res.append(vote(neighbors["resolution"].tolist(), weights))

    it_labels  = sorted(val["issuetype"].unique())
    res_labels = sorted(val["resolution"].unique())

    return {
        "configuration":    name,
        "acc_issuetype":    round(accuracy_score(val["issuetype"], pred_it),   4),
        "macro_f1_it":      round(f1_score(val["issuetype"], pred_it, labels=it_labels, average="macro", zero_division=0), 4),
        "acc_resolution":   round(accuracy_score(val["resolution"], pred_res),  4),
        "macro_f1_res":     round(f1_score(val["resolution"], pred_res, labels=res_labels, average="macro", zero_division=0), 4),
    }


# ── Run ablations ─────────────────────────────────────────────────────────────
configs = [
    ("Full V6",               True,  True,  True,  True),
    ("No priority boost",     False, True,  True,  True),
    ("No status boost",       True,  False, True,  True),
    ("No reporter boost",     True,  True,  False, True),
    ("No changelog re-rank",  True,  True,  True,  False),
    ("No metadata at all",    False, False, False, False),
]

results = []
for cfg in configs:
    name, p, s, r, c = cfg
    print(f"  {name} …")
    row = eval_config(name, p, s, r, c)
    results.append(row)
    print(f"    acc_it={row['acc_issuetype']:.4f}  macro_f1_it={row['macro_f1_it']:.4f}")

out_df = pd.DataFrame(results)
out_df.to_csv(ABLATIONS / "boost_ablation.csv", index=False)
print(f"\nSaved → {ABLATIONS / 'boost_ablation.csv'}")
print(out_df.to_string(index=False))

# ── Plot ─────────────────────────────────────────────────────────────────────
x = np.arange(len(results))
w = 0.2
fig, ax = plt.subplots(figsize=(13, 5))
ax.bar(x - 1.5*w, out_df["acc_issuetype"],  w, label="Acc IssueType")
ax.bar(x - 0.5*w, out_df["macro_f1_it"],    w, label="Macro-F1 IT")
ax.bar(x + 0.5*w, out_df["acc_resolution"], w, label="Acc Resolution")
ax.bar(x + 1.5*w, out_df["macro_f1_res"],   w, label="Macro-F1 Res")
ax.set_xticks(x)
ax.set_xticklabels(out_df["configuration"], rotation=20, ha="right")
ax.set_ylim(0, 1)
ax.set_title("Boost Ablation — Leave-One-Out")
ax.legend()
ax.grid(axis="y", alpha=0.3)
fig.tight_layout()
fig.savefig(ABLATIONS / "boost_ablation.png", dpi=150)
print(f"Plot → {ABLATIONS / 'boost_ablation.png'}")
