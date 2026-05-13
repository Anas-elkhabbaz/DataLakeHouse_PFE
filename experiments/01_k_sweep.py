"""
Ablation 01 — k sweep
Tests KNN voting for k in {5, 10, 15, 20, 30, 50} on the validation set.
Requires embeddings and mart_ml to already be fetched/cached.

Usage: python experiments/01_k_sweep.py
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
from load.retrieval import CHANGELOG_FEATURES, QUERY_PREFIX, build_scaler, rrf_fuse

load_dotenv()

RESULTS   = Path(__file__).parent.parent / "results"
ABLATIONS = RESULTS / "ablations"
ABLATIONS.mkdir(exist_ok=True)

CACHE_NOCO = RESULTS / "embeddings_noco.npz"
CACHE_RICH = RESULTS / "embeddings_rich.npz"
K_VALUES   = [5, 10, 15, 20, 30, 50]

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

# Load embeddings
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

# ── Precompute top-50 candidates per val ticket ───────────────────────────────
print("Precomputing top-50 candidates …")
top50_indices = []
top50_sims    = []
for i in range(len(val)):
    s_n = emb_noco @ val_emb_noco[i]
    s_r = emb_rich @ val_emb_rich[i]
    idx, rrf = rrf_fuse(s_n, s_r, top_k=50)
    weights  = (s_n[idx] + s_r[idx]) / 2.0
    top50_indices.append(idx)
    top50_sims.append(weights)

# ── Sweep k ──────────────────────────────────────────────────────────────────
results = []
for k in K_VALUES:
    print(f"  k={k} …")
    pred_it  = []
    pred_res = []
    for i in range(len(val)):
        idx    = top50_indices[i][:k]
        weights = top50_sims[i][:k]
        neighbors = train.iloc[idx]

        def vote(labels, ws):
            s: dict = {}
            for l, w in zip(labels, ws): s[l] = s.get(l, 0.0) + float(w)
            return max(s, key=s.get)

        pred_it.append(vote(neighbors["issuetype"].tolist(), weights))
        pred_res.append(vote(neighbors["resolution"].tolist(), weights))

    it_labels  = sorted(val["issuetype"].unique())
    res_labels = sorted(val["resolution"].unique())

    results.append({
        "k":              k,
        "acc_issuetype":  round(accuracy_score(val["issuetype"], pred_it),   4),
        "macro_f1_it":    round(f1_score(val["issuetype"], pred_it, labels=it_labels, average="macro", zero_division=0), 4),
        "acc_resolution": round(accuracy_score(val["resolution"], pred_res),  4),
        "macro_f1_res":   round(f1_score(val["resolution"], pred_res, labels=res_labels, average="macro", zero_division=0), 4),
    })
    print(f"    acc_it={results[-1]['acc_issuetype']:.4f}  macro_f1_it={results[-1]['macro_f1_it']:.4f}")

out_df = pd.DataFrame(results)
out_df.to_csv(ABLATIONS / "k_sweep.csv", index=False)
print(f"\nSaved → {ABLATIONS / 'k_sweep.csv'}")
print(out_df.to_string(index=False))

# Plot
fig, axes = plt.subplots(1, 2, figsize=(12, 4))
for ax, metric, title in [
    (axes[0], ("acc_issuetype", "macro_f1_it"),    "Issuetype"),
    (axes[1], ("acc_resolution", "macro_f1_res"),  "Resolution"),
]:
    for col, label in zip(metric, ["Accuracy", "Macro-F1"]):
        ax.plot(out_df["k"], out_df[col], marker="o", label=label)
    ax.set_xlabel("k"); ax.set_title(title); ax.legend(); ax.grid(True, alpha=.3)

fig.suptitle("K Sweep — Accuracy & Macro-F1 vs k")
fig.tight_layout()
fig.savefig(ABLATIONS / "k_sweep.png", dpi=150)
print(f"Plot → {ABLATIONS / 'k_sweep.png'}")
