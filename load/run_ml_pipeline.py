"""
V6 Hybrid RCA — Python fallback pipeline (no Snowflake Cortex required)
Steps:
  1. Fetch mart_ml from Snowflake
  2. Embed text_noco with sentence-transformers (all-MiniLM-L6-v2)
  3. KNN similarity search (top-15 train neighbors per val ticket)
  4. Vote on issuetype + resolution
  5. Evaluate (accuracy, macro-F1, confusion matrix)
  6. Save results locally + upload predictions table to Snowflake
"""
import os, time, json
from pathlib import Path
from dotenv import load_dotenv

import numpy as np
import pandas as pd
from sklearn.metrics import f1_score, confusion_matrix
from sentence_transformers import SentenceTransformer
import snowflake.connector
from snowflake.connector.pandas_tools import write_pandas

load_dotenv()

RESULTS = Path(__file__).parent.parent / "results"
RESULTS.mkdir(exist_ok=True)

EMBED_CACHE = RESULTS / "embeddings_cache.npz"

# ── 1. Connect + fetch data ─────────────────────────────────────────────────
print("Connecting to Snowflake …")
conn = snowflake.connector.connect(
    account=os.environ["SNOWFLAKE_ACCOUNT"],
    user=os.environ["SNOWFLAKE_USER"],
    password=os.environ["SNOWFLAKE_PASSWORD"],
    role=os.environ["SNOWFLAKE_ROLE"],
    warehouse="PFE_WH",
    database="PFE_SPARK",
    schema="MARTS_ML",
)
cur = conn.cursor()

print("Fetching mart_ml …")
cur.execute("""
    SELECT key, split, issuetype, resolution, text_noco
    FROM PFE_SPARK.MARTS_ML.MART_ML
    WHERE split IN ('train', 'validation')
""")
rows = cur.fetchall()
cols = [d[0].lower() for d in cur.description]
df = pd.DataFrame(rows, columns=cols)
print(f"  Loaded {len(df):,} rows  (train={len(df[df.split=='train']):,}, val={len(df[df.split=='validation']):,})")

train = df[df["split"] == "train"].reset_index(drop=True)
val   = df[df["split"] == "validation"].reset_index(drop=True)

# ── 2. Embed with sentence-transformers ─────────────────────────────────────
model_name = "all-MiniLM-L6-v2"

if EMBED_CACHE.exists():
    print(f"Loading cached embeddings from {EMBED_CACHE} …")
    cache = np.load(EMBED_CACHE, allow_pickle=True)
    train_emb = cache["train_emb"]
    val_emb   = cache["val_emb"]
    print(f"  train_emb shape: {train_emb.shape}, val_emb shape: {val_emb.shape}")
else:
    print(f"Loading model {model_name} …")
    model = SentenceTransformer(model_name)

    print(f"Embedding {len(train):,} train tickets …")
    t0 = time.time()
    train_texts = train["text_noco"].fillna("").tolist()
    train_emb = model.encode(train_texts, batch_size=256, show_progress_bar=True,
                             normalize_embeddings=True)
    print(f"  Done in {time.time()-t0:.0f}s — shape {train_emb.shape}")

    print(f"Embedding {len(val):,} validation tickets …")
    t0 = time.time()
    val_texts = val["text_noco"].fillna("").tolist()
    val_emb = model.encode(val_texts, batch_size=256, show_progress_bar=True,
                           normalize_embeddings=True)
    print(f"  Done in {time.time()-t0:.0f}s — shape {val_emb.shape}")

    np.savez_compressed(EMBED_CACHE, train_emb=train_emb, val_emb=val_emb)
    print(f"  Embeddings cached → {EMBED_CACHE}")

# ── 3. KNN similarity search (top-15 per val ticket) ────────────────────────
print("Computing cosine similarity (val × train) …")
t0 = time.time()
# embeddings already L2-normalised → dot product = cosine similarity
# Process in batches to limit peak RAM
BATCH = 500
K = 15

pred_issuetype  = []
pred_resolution = []
pred_confidence_it  = []
pred_confidence_res = []
pred_method     = []

for start in range(0, len(val), BATCH):
    end = min(start + BATCH, len(val))
    sim = val_emb[start:end] @ train_emb.T          # (batch, n_train)

    for i, row_sim in enumerate(sim):
        top_idx = np.argpartition(row_sim, -K)[-K:]
        top_idx = top_idx[np.argsort(row_sim[top_idx])[::-1]]
        top_sim = row_sim[top_idx]
        top_it  = train.iloc[top_idx]["issuetype"].values
        top_res = train.iloc[top_idx]["resolution"].values

        # Weighted vote — weight by similarity score
        def weighted_vote(labels, weights):
            scores = {}
            for lbl, w in zip(labels, weights):
                scores[lbl] = scores.get(lbl, 0.0) + float(w)
            total = sum(scores.values())
            best  = max(scores, key=scores.get)
            conf  = scores[best] / total if total > 0 else 0.0
            return best, conf

        it,  conf_it  = weighted_vote(top_it,  top_sim)
        res, conf_res = weighted_vote(top_res, top_sim)

        pred_issuetype.append(it)
        pred_resolution.append(res)
        pred_confidence_it.append(round(conf_it, 4))
        pred_confidence_res.append(round(conf_res, 4))
        pred_method.append("DIRECT")

print(f"  Similarity + voting done in {time.time()-t0:.1f}s")

# ── 4. Build predictions dataframe ──────────────────────────────────────────
preds = val[["key", "issuetype", "resolution"]].copy()
preds.columns = ["key", "true_issuetype", "true_resolution"]
preds["pred_issuetype"]   = pred_issuetype
preds["pred_resolution"]  = pred_resolution
preds["conf_issuetype"]   = pred_confidence_it
preds["conf_resolution"]  = pred_confidence_res
preds["method"]           = pred_method
preds["fix_summary"]      = ""   # no LLM enrichment in fallback

# ── 5. Evaluate ─────────────────────────────────────────────────────────────
def evaluate(true, pred, label):
    acc = (np.array(true) == np.array(pred)).mean()
    f1  = f1_score(true, pred, average="macro", zero_division=0)
    print(f"\n  [{label}]  accuracy={acc:.4f}  macro-F1={f1:.4f}")
    return acc, f1

print("\n=== Evaluation ===")
acc_it,  f1_it  = evaluate(preds["true_issuetype"],  preds["pred_issuetype"],  "issuetype")
acc_res, f1_res = evaluate(preds["true_resolution"],  preds["pred_resolution"], "resolution")

# Per-class F1
it_labels = sorted(preds["true_issuetype"].unique())
it_f1_per_class = f1_score(preds["true_issuetype"], preds["pred_issuetype"],
                            labels=it_labels, average=None, zero_division=0)

res_labels = sorted(preds["true_resolution"].unique())
res_f1_per_class = f1_score(preds["true_resolution"], preds["pred_resolution"],
                             labels=res_labels, average=None, zero_division=0)

# Confusion matrices
cm_it  = confusion_matrix(preds["true_issuetype"],  preds["pred_issuetype"],  labels=it_labels)
cm_res = confusion_matrix(preds["true_resolution"],  preds["pred_resolution"], labels=res_labels)

# ── 6. Save results locally ─────────────────────────────────────────────────
print("\n=== Saving results ===")

# Predictions CSV
preds_path = RESULTS / "mart_predictions.csv"
preds.to_csv(preds_path, index=False, encoding="utf-8")
print(f"  mart_predictions.csv  ({len(preds):,} rows)")

# Confusion matrices
pd.DataFrame(cm_it,  index=it_labels,  columns=it_labels).to_csv(
    RESULTS / "confusion_matrix_issuetype.csv")
pd.DataFrame(cm_res, index=res_labels, columns=res_labels).to_csv(
    RESULTS / "confusion_matrix_resolution.csv")
print("  confusion_matrix_issuetype.csv")
print("  confusion_matrix_resolution.csv")

# Evaluation report
report_lines = [
    "=== PFE Spark Triage — Evaluation Report ===",
    f"Model : sentence-transformers/{model_name}  (KNN k=15, cosine similarity)",
    f"Train  : {len(train):,} tickets",
    f"Val    : {len(val):,} tickets",
    "",
    "--- issuetype ---",
    f"Accuracy : {acc_it:.4f}",
    f"Macro-F1 : {f1_it:.4f}",
    "Per-class F1:",
]
for lbl, score in zip(it_labels, it_f1_per_class):
    report_lines.append(f"  {lbl:<20} {score:.4f}")

report_lines += [
    "",
    "--- resolution ---",
    f"Accuracy : {acc_res:.4f}",
    f"Macro-F1 : {f1_res:.4f}",
    "Per-class F1:",
]
for lbl, score in zip(res_labels, res_f1_per_class):
    report_lines.append(f"  {lbl:<20} {score:.4f}")

report_lines += [
    "",
    f"Method breakdown: DIRECT={len(preds[preds.method=='DIRECT']):,}  LLM=0",
]

report_text = "\n".join(report_lines)
(RESULTS / "evaluation_report.txt").write_text(report_text, encoding="utf-8")
print("  evaluation_report.txt")
print()
print(report_text)

# ── 7. Upload predictions to Snowflake ──────────────────────────────────────
print("\nUploading CORTEX.MART_PREDICTIONS to Snowflake …")
cur.execute("USE DATABASE PFE_SPARK")
cur.execute("USE SCHEMA CORTEX")
cur.execute("""
    CREATE OR REPLACE TABLE CORTEX.MART_PREDICTIONS (
        key               VARCHAR,
        true_issuetype    VARCHAR,
        true_resolution   VARCHAR,
        pred_issuetype    VARCHAR,
        pred_resolution   VARCHAR,
        conf_issuetype    FLOAT,
        conf_resolution   FLOAT,
        method            VARCHAR,
        fix_summary       VARCHAR
    )
""")

upload_df = preds.copy()
upload_df.columns = [c.upper() for c in upload_df.columns]
success, n_chunks, n_rows, _ = write_pandas(conn, upload_df, "MART_PREDICTIONS",
                                             schema="CORTEX", database="PFE_SPARK")
print(f"  Uploaded {n_rows:,} rows  (success={success})")

conn.close()
print("\nPipeline complete. All results saved to results/")
