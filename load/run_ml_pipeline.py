"""
V6 Hybrid RCA — Python pipeline (no Snowflake Cortex required)

Architecture:
  1. Fetch mart_ml (train + eval split) from Snowflake
  2. Embed text_noco AND text_rich with BAAI/bge-large-en-v1.5 (1024d)
  3. RRF fusion of NOCO + RICH similarities
  4. Changelog feature re-ranking
  5. Metadata-boosted top-15 retrieval
  6. Confidence-gated voting (DIRECT / LLM_REQUIRED)
  7. Evaluate with bootstrap CIs + confusion matrix PNGs
  8. Upload MART_PREDICTIONS to Snowflake

Usage:
  python load/run_ml_pipeline.py              # tune mode (uses 2022 validation)
  python load/run_ml_pipeline.py --phase final # final mode (uses 2023 test — one time only)
  python load/run_ml_pipeline.py --class-weighted
"""
import argparse, hashlib, json, os, sys, time
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer
from sklearn.metrics import (
    accuracy_score, classification_report, confusion_matrix,
    f1_score,
)
from sklearn.utils.class_weight import compute_class_weight
import snowflake.connector

sys.path.insert(0, str(Path(__file__).parent))
from retrieval import (
    CHANGELOG_FEATURES, QUERY_PREFIX,
    build_scaler, retrieve_top_k, weighted_vote, route,
)

load_dotenv()

# ── Constants ────────────────────────────────────────────────────────────────
EMBEDDING_MODEL = "BAAI/bge-large-en-v1.5"
EMBEDDING_DIM   = 1024
K_FINAL         = 15
RRF_TOP         = 30

RESULTS      = Path(__file__).parent.parent / "results"
RESULTS.mkdir(exist_ok=True)
ABLATIONS    = RESULTS / "ablations"
ABLATIONS.mkdir(exist_ok=True)

CACHE_NOCO   = RESULTS / "embeddings_noco.npz"
CACHE_RICH   = RESULTS / "embeddings_rich.npz"
META_PATH    = RESULTS / "embeddings_meta.json"

# ── CLI ──────────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument("--phase", choices=["tune", "final"], default="tune",
                    help="tune = 2022 validation (default);  final = 2023 test (once only)")
parser.add_argument("--class-weighted", action="store_true",
                    help="Upweight minority classes in voting")
args = parser.parse_args()

EVAL_SPLIT = "validation" if args.phase == "tune" else "test"
print(f"\n=== V6 Hybrid RCA pipeline  phase={args.phase}  eval_split={EVAL_SPLIT} ===\n")

# ── 1. Connect + fetch data ──────────────────────────────────────────────────
print("Connecting to Snowflake …")
conn = snowflake.connector.connect(
    account   = os.environ["SNOWFLAKE_ACCOUNT"],
    user      = os.environ["SNOWFLAKE_USER"],
    password  = os.environ["SNOWFLAKE_PASSWORD"],
    role      = os.environ["SNOWFLAKE_ROLE"],
    warehouse = os.environ.get("SNOWFLAKE_WAREHOUSE", "PFE_WH"),
    database  = os.environ.get("SNOWFLAKE_DATABASE",  "PFE_SPARK"),
    schema    = "MARTS_ML",
)
cur = conn.cursor()

print("Fetching mart_ml …")
cur.execute("""
    SELECT key, split, issuetype, resolution,
           text_noco, text_rich,
           priority, status, reporter,
           n_status_changes, n_priority_changes, n_assignee_changes,
           n_resolution_changes, was_escalated, was_deescalated,
           n_people_involved, n_total_changes
    FROM PFE_SPARK.MARTS_ML.MART_ML
    WHERE split IN ('train', 'validation', 'test')
""")
rows = cur.fetchall()
cols = [d[0].lower() for d in cur.description]
df   = pd.DataFrame(rows, columns=cols)
df[CHANGELOG_FEATURES] = df[CHANGELOG_FEATURES].fillna(0).astype(float)

train = df[df["split"] == "train"].reset_index(drop=True)
eval_ = df[df["split"] == EVAL_SPLIT].reset_index(drop=True)
print(f"  train={len(train):,}  {EVAL_SPLIT}={len(eval_):,}")


# ── 2. Hash the corpus to detect stale cache ────────────────────────────────
def _sha256_col(series: pd.Series) -> str:
    return hashlib.sha256(
        "".join(series.fillna("").tolist()).encode()
    ).hexdigest()[:16]

noco_hash = _sha256_col(train["text_noco"])
rich_hash = _sha256_col(train["text_rich"])


def _cache_valid() -> bool:
    if not (CACHE_NOCO.exists() and CACHE_RICH.exists() and META_PATH.exists()):
        return False
    meta = json.loads(META_PATH.read_text())
    return (meta.get("model") == EMBEDDING_MODEL
            and meta.get("n_train") == len(train)
            and meta.get("noco_hash") == noco_hash
            and meta.get("rich_hash") == rich_hash)


# ── 3. Embed or load from cache ──────────────────────────────────────────────
if _cache_valid():
    print("Loading cached embeddings …")
    train_emb_noco = np.load(CACHE_NOCO)["train_emb"]
    train_emb_rich = np.load(CACHE_RICH)["train_emb"]
    print(f"  noco shape: {train_emb_noco.shape}  rich shape: {train_emb_rich.shape}")
else:
    print(f"Loading model {EMBEDDING_MODEL} …")
    model = SentenceTransformer(EMBEDDING_MODEL)

    print(f"Embedding {len(train):,} train tickets (NOCO) …")
    t0 = time.time()
    train_emb_noco = model.encode(
        train["text_noco"].fillna("").tolist(),
        batch_size=32, show_progress_bar=True, normalize_embeddings=True,
    )
    print(f"  Done in {time.time()-t0:.0f}s")

    print(f"Embedding {len(train):,} train tickets (RICH) …")
    t0 = time.time()
    train_emb_rich = model.encode(
        train["text_rich"].fillna("").tolist(),
        batch_size=32, show_progress_bar=True, normalize_embeddings=True,
    )
    print(f"  Done in {time.time()-t0:.0f}s")

    np.savez_compressed(CACHE_NOCO, train_emb=train_emb_noco)
    np.savez_compressed(CACHE_RICH, train_emb=train_emb_rich)

    META_PATH.write_text(json.dumps({
        "model":      EMBEDDING_MODEL,
        "dim":        EMBEDDING_DIM,
        "n_train":    len(train),
        "noco_hash":  noco_hash,
        "rich_hash":  rich_hash,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }, indent=2))
    print(f"  Embeddings cached → {CACHE_NOCO}, {CACHE_RICH}")

# ── 4. Build changelog scaler ────────────────────────────────────────────────
print("Fitting changelog scaler …")
scaler = build_scaler(train)

# ── 5. Class weights (optional) ───────────────────────────────────────────────
it_class_weights  = None
res_class_weights = None
if args.class_weighted:
    it_labels  = train["issuetype"].unique()
    res_labels = train["resolution"].unique()
    it_w  = compute_class_weight("balanced", classes=it_labels,  y=train["issuetype"])
    res_w = compute_class_weight("balanced", classes=res_labels, y=train["resolution"])
    it_class_weights  = dict(zip(it_labels, it_w))
    res_class_weights = dict(zip(res_labels, res_w))
    print("  Class weights computed (balanced)")

# ── 6. Embed eval set + predict ──────────────────────────────────────────────
print(f"\nLoading model for eval encoding …")
try:
    model
except NameError:
    model = SentenceTransformer(EMBEDDING_MODEL)

print(f"Embedding {len(eval_):,} {EVAL_SPLIT} tickets …")
t0 = time.time()
eval_emb_noco = model.encode(
    (QUERY_PREFIX + eval_["text_noco"].fillna("")).tolist(),
    batch_size=32, show_progress_bar=True, normalize_embeddings=True,
)
eval_emb_rich = model.encode(
    (QUERY_PREFIX + eval_["text_rich"].fillna("")).tolist(),
    batch_size=32, show_progress_bar=True, normalize_embeddings=True,
)
print(f"  Done in {time.time()-t0:.0f}s")

print(f"\nRunning retrieval + voting for {len(eval_):,} tickets …")
t0 = time.time()

pred_issuetype  = []
pred_resolution = []
pred_conf_it    = []
pred_conf_res   = []
pred_routing_it = []
pred_margin_it  = []
pred_routing_res = []
pred_margin_res  = []

for i in range(len(eval_)):
    row = eval_.iloc[i]
    q_noco = eval_emb_noco[i]
    q_rich = eval_emb_rich[i]

    top_idx, _ = retrieve_top_k(
        q_noco, q_rich,
        train_emb_noco, train_emb_rich,
        train, row, scaler,
        rrf_top=RRF_TOP, final_k=K_FINAL,
    )
    neighbors = train.iloc[top_idx]

    # Similarity scores for weighting (recompute on final k)
    sim_noco = train_emb_noco[top_idx] @ q_noco
    sim_rich = train_emb_rich[top_idx] @ q_rich
    weights  = (sim_noco + sim_rich) / 2.0

    it, conf_it, margin_it, _ = weighted_vote(
        neighbors["issuetype"].tolist(), weights, it_class_weights
    )
    res, conf_res, margin_res, _ = weighted_vote(
        neighbors["resolution"].tolist(), weights, res_class_weights
    )

    pred_issuetype.append(it)
    pred_resolution.append(res)
    pred_conf_it.append(round(conf_it, 4))
    pred_conf_res.append(round(conf_res, 4))
    pred_routing_it.append(route(conf_it, margin_it))
    pred_margin_it.append(round(margin_it, 4))
    pred_routing_res.append(route(conf_res, margin_res))
    pred_margin_res.append(round(margin_res, 4))

print(f"  Prediction done in {time.time()-t0:.1f}s")

# ── 7. Build predictions dataframe ───────────────────────────────────────────
preds = eval_[["key", "issuetype", "resolution"]].copy()
preds.columns = ["key", "true_issuetype", "true_resolution"]
preds["pred_issuetype"]    = pred_issuetype
preds["pred_resolution"]   = pred_resolution
preds["conf_issuetype"]    = pred_conf_it
preds["conf_resolution"]   = pred_conf_res
preds["routing_issuetype"] = pred_routing_it
preds["margin_issuetype"]  = pred_margin_it
preds["routing_resolution"] = pred_routing_res
preds["margin_resolution"]  = pred_margin_res
preds["fix_summary"]        = ""

# ── 8. Evaluate ───────────────────────────────────────────────────────────────

def bootstrap_ci(y_true, y_pred, labels, n_boot=500, average="macro", seed=42):
    rng = np.random.default_rng(seed)
    n   = len(y_true)
    scores = [
        f1_score(y_true[idx := rng.integers(0, n, n)],
                 y_pred[idx], labels=labels, average=average, zero_division=0)
        for _ in range(n_boot)
    ]
    return np.percentile(scores, [2.5, 50, 97.5])


def full_eval(true_ser, pred_ser, target_name, output_dir):
    true  = true_ser.tolist()
    pred  = pred_ser.tolist()
    labels = sorted(set(true) | set(pred))

    acc       = accuracy_score(true, pred)
    macro_f1  = f1_score(true, pred, labels=labels, average="macro",    zero_division=0)
    weighted_f1 = f1_score(true, pred, labels=labels, average="weighted", zero_division=0)
    report    = classification_report(true, pred, labels=labels, zero_division=0, output_dict=True)
    cm        = confusion_matrix(true, pred, labels=labels)
    ci        = bootstrap_ci(np.array(true), np.array(pred), labels)

    # Confusion matrix PNG
    fig, ax = plt.subplots(figsize=(max(8, len(labels)), max(6, len(labels) - 1)))
    sns.heatmap(cm, annot=True, fmt="d", xticklabels=labels, yticklabels=labels,
                cmap="Blues", ax=ax)
    ax.set_xlabel("Predicted"); ax.set_ylabel("True")
    ax.set_title(f"Confusion Matrix — {target_name}")
    fig.tight_layout()
    fig.savefig(output_dir / f"confusion_{target_name}.png", dpi=150)
    plt.close(fig)

    result = {
        "target": target_name,
        "n_eval": len(true),
        "accuracy": round(acc, 4),
        "macro_f1": round(macro_f1, 4),
        "weighted_f1": round(weighted_f1, 4),
        "macro_f1_ci_95": [round(x, 4) for x in ci],
        "per_class": {k: {m: round(v, 4) for m, v in vs.items()}
                      for k, vs in report.items() if isinstance(vs, dict)},
    }
    (output_dir / f"eval_{target_name}.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False)
    )
    return result


print("\n=== Evaluation ===")
eval_it  = full_eval(preds["true_issuetype"],  preds["pred_issuetype"],  "issuetype",  RESULTS)
eval_res = full_eval(preds["true_resolution"],  preds["pred_resolution"], "resolution", RESULTS)

direct_it  = (preds["routing_issuetype"]  == "DIRECT").sum()
direct_res = (preds["routing_resolution"] == "DIRECT").sum()

print(f"\n  issuetype  acc={eval_it['accuracy']:.4f}  macro-F1={eval_it['macro_f1']:.4f}  "
      f"[95% CI {eval_it['macro_f1_ci_95'][0]:.4f}–{eval_it['macro_f1_ci_95'][2]:.4f}]")
print(f"  resolution acc={eval_res['accuracy']:.4f}  macro-F1={eval_res['macro_f1']:.4f}  "
      f"[95% CI {eval_res['macro_f1_ci_95'][0]:.4f}–{eval_res['macro_f1_ci_95'][2]:.4f}]")
print(f"\n  Routing  issuetype:  DIRECT={direct_it:,}  LLM_REQUIRED={len(preds)-direct_it:,}")
print(f"  Routing  resolution: DIRECT={direct_res:,}  LLM_REQUIRED={len(preds)-direct_res:,}")

# Save predictions CSV
preds.to_csv(RESULTS / "mart_predictions.csv", index=False, encoding="utf-8")
print(f"\n  mart_predictions.csv  ({len(preds):,} rows)")

# ── 9. Upload to Snowflake ────────────────────────────────────────────────────
print("\nUploading CORTEX.MART_PREDICTIONS to Snowflake …")
cur.execute("USE DATABASE PFE_SPARK")
cur.execute("USE SCHEMA CORTEX")
cur.execute("""
    CREATE OR REPLACE TABLE CORTEX.MART_PREDICTIONS (
        key                VARCHAR,
        true_issuetype     VARCHAR,
        true_resolution    VARCHAR,
        pred_issuetype     VARCHAR,
        pred_resolution    VARCHAR,
        conf_issuetype     FLOAT,
        conf_resolution    FLOAT,
        routing_issuetype  VARCHAR,
        margin_issuetype   FLOAT,
        routing_resolution VARCHAR,
        margin_resolution  FLOAT,
        fix_summary        VARCHAR
    )
""")

rows_to_upload = [
    (
        str(r.key), str(r.true_issuetype), str(r.true_resolution),
        str(r.pred_issuetype), str(r.pred_resolution),
        float(r.conf_issuetype), float(r.conf_resolution),
        str(r.routing_issuetype), float(r.margin_issuetype),
        str(r.routing_resolution), float(r.margin_resolution),
        str(r.fix_summary),
    )
    for r in preds.itertuples()
]
cur.executemany("""
    INSERT INTO CORTEX.MART_PREDICTIONS
        (key, true_issuetype, true_resolution,
         pred_issuetype, pred_resolution,
         conf_issuetype, conf_resolution,
         routing_issuetype, margin_issuetype,
         routing_resolution, margin_resolution,
         fix_summary)
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
""", rows_to_upload)
print(f"  Uploaded {len(rows_to_upload):,} rows")

conn.close()
print("\nPipeline complete. Results in results/")
print(f"  embeddings_noco.npz, embeddings_rich.npz, embeddings_meta.json")
print(f"  eval_issuetype.json, eval_resolution.json")
print(f"  confusion_issuetype.png, confusion_resolution.png")
print(f"  mart_predictions.csv")
