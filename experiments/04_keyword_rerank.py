"""
Ablation 04 — BM25 vs embedding vs hybrid retrieval
Compares three retrieval strategies:
  A) Pure embedding (dual RRF, no BM25)
  B) Pure BM25 (on text_noco corpus)
  C) Hybrid (50 % embedding score + 50 % BM25 score)

Uses rank_bm25.BM25Okapi for keyword matching.
Output: results/ablations/bm25_comparison.csv + PNG

Usage: python experiments/04_keyword_rerank.py
"""
import os, sys
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
K          = 15
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

# ── Embeddings ───────────────────────────────────────────────────────────────
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

# ── BM25 index ───────────────────────────────────────────────────────────────
print("Building BM25 index …")
try:
    from rank_bm25 import BM25Okapi
except ImportError:
    print("rank_bm25 not installed — run: pip install rank_bm25")
    sys.exit(1)

def tokenize(text: str):
    return str(text).lower().split()

train_corpus = train["text_noco"].fillna("").tolist()
bm25 = BM25Okapi([tokenize(t) for t in train_corpus])
print(f"  BM25 index built over {len(train_corpus):,} documents.")

# ── Precompute embedding scores ──────────────────────────────────────────────
print("Precomputing embedding scores (val × train) …")
# Shape: (n_val, n_train)
scores_emb_noco = (emb_noco @ val_emb_noco.T).T
scores_emb_rich = (emb_rich @ val_emb_rich.T).T

# ── Helpers ──────────────────────────────────────────────────────────────────

def min_max_norm(arr: np.ndarray) -> np.ndarray:
    lo, hi = arr.min(), arr.max()
    if hi - lo < 1e-9:
        return np.zeros_like(arr)
    return (arr - lo) / (hi - lo)


def vote(labels, weights):
    s = {}
    for l, w in zip(labels, weights):
        s[l] = s.get(l, 0.0) + float(w)
    return max(s, key=s.get)


def evaluate(pred_it, pred_res) -> dict:
    it_labels  = sorted(val["issuetype"].unique())
    res_labels = sorted(val["resolution"].unique())
    return {
        "acc_issuetype":  round(accuracy_score(val["issuetype"], pred_it),   4),
        "macro_f1_it":    round(f1_score(val["issuetype"], pred_it, labels=it_labels, average="macro", zero_division=0), 4),
        "acc_resolution": round(accuracy_score(val["resolution"], pred_res),  4),
        "macro_f1_res":   round(f1_score(val["resolution"], pred_res, labels=res_labels, average="macro", zero_division=0), 4),
    }

# ── Strategy A: Pure embedding (dual RRF) ────────────────────────────────────
print("\nStrategy A: Pure embedding (dual RRF) …")
pred_it_a, pred_res_a = [], []
for i in range(len(val)):
    sn = scores_emb_noco[i]
    sr = scores_emb_rich[i]
    top, rrf = rrf_fuse(sn, sr, top_k=K)
    nb = train.iloc[top]
    pred_it_a.append(vote(nb["issuetype"].tolist(), rrf))
    pred_res_a.append(vote(nb["resolution"].tolist(), rrf))
res_a = {"strategy": "A: Pure Embedding (dual RRF)", **evaluate(pred_it_a, pred_res_a)}
print(f"  acc_it={res_a['acc_issuetype']:.4f}  macro_f1_it={res_a['macro_f1_it']:.4f}")

# ── Strategy B: Pure BM25 ─────────────────────────────────────────────────────
print("Strategy B: Pure BM25 …")
pred_it_b, pred_res_b = [], []
for i in range(len(val)):
    query_tokens = tokenize(val.at[i, "text_noco"])
    bm25_scores  = np.array(bm25.get_scores(query_tokens), dtype=float)
    top  = np.argsort(bm25_scores)[::-1][:K]
    w    = bm25_scores[top]
    nb   = train.iloc[top]
    pred_it_b.append(vote(nb["issuetype"].tolist(), w))
    pred_res_b.append(vote(nb["resolution"].tolist(), w))
res_b = {"strategy": "B: Pure BM25", **evaluate(pred_it_b, pred_res_b)}
print(f"  acc_it={res_b['acc_issuetype']:.4f}  macro_f1_it={res_b['macro_f1_it']:.4f}")

# ── Strategy C: Hybrid (50 % embedding + 50 % BM25) ──────────────────────────
print("Strategy C: Hybrid (50 % embedding + 50 % BM25) …")
pred_it_c, pred_res_c = [], []
for i in range(len(val)):
    sn = scores_emb_noco[i]
    sr = scores_emb_rich[i]
    # RRF top-30 as candidate set
    top30, rrf30 = rrf_fuse(sn, sr, top_k=RRF_TOP)

    query_tokens = tokenize(val.at[i, "text_noco"])
    bm25_all     = np.array(bm25.get_scores(query_tokens), dtype=float)

    # Normalize both within the top-30 candidates
    emb_sub  = min_max_norm(rrf30)
    bm25_sub = min_max_norm(bm25_all[top30])

    hybrid = 0.5 * emb_sub + 0.5 * bm25_sub
    best   = np.argsort(hybrid)[::-1][:K]
    nb     = train.iloc[top30[best]]
    w      = hybrid[best]
    pred_it_c.append(vote(nb["issuetype"].tolist(), w))
    pred_res_c.append(vote(nb["resolution"].tolist(), w))
res_c = {"strategy": "C: Hybrid (50% emb + 50% BM25)", **evaluate(pred_it_c, pred_res_c)}
print(f"  acc_it={res_c['acc_issuetype']:.4f}  macro_f1_it={res_c['macro_f1_it']:.4f}")

# ── Save results ─────────────────────────────────────────────────────────────
out_df = pd.DataFrame([res_a, res_b, res_c])
out_df.to_csv(ABLATIONS / "bm25_comparison.csv", index=False)
print(f"\nSaved → {ABLATIONS / 'bm25_comparison.csv'}")
print(out_df.to_string(index=False))

# ── Plot ──────────────────────────────────────────────────────────────────────
labels   = [r["strategy"].split(":")[0] for r in [res_a, res_b, res_c]]
metrics  = {
    "Acc IssueType":  [r["acc_issuetype"]  for r in [res_a, res_b, res_c]],
    "Macro-F1 IT":    [r["macro_f1_it"]    for r in [res_a, res_b, res_c]],
    "Acc Resolution": [r["acc_resolution"] for r in [res_a, res_b, res_c]],
    "Macro-F1 Res":   [r["macro_f1_res"]   for r in [res_a, res_b, res_c]],
}

x  = np.arange(len(labels))
w  = 0.18
fig, ax = plt.subplots(figsize=(10, 5))
for j, (metric, vals) in enumerate(metrics.items()):
    offset = (j - 1.5) * w
    ax.bar(x + offset, vals, w, label=metric)

ax.set_xticks(x)
ax.set_xticklabels(labels)
ax.set_ylim(0, 1)
ax.set_title("BM25 vs. Embedding vs. Hybrid (k=15)")
ax.legend(loc="lower right")
ax.grid(axis="y", alpha=0.3)
fig.tight_layout()
fig.savefig(ABLATIONS / "bm25_comparison.png", dpi=150)
print(f"Plot → {ABLATIONS / 'bm25_comparison.png'}")
