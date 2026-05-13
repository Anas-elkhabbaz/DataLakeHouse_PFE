"""
Shared retrieval module — dual-embedding RRF + changelog re-ranking.
Used by both run_ml_pipeline.py (batch) and inference_app.py (interactive).
"""
import math
import numpy as np
from sklearn.preprocessing import StandardScaler

CHANGELOG_FEATURES = [
    "n_status_changes", "n_priority_changes", "n_assignee_changes",
    "n_resolution_changes", "was_escalated", "was_deescalated",
    "n_people_involved", "n_total_changes",
]

QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


def rrf_fuse(scores_noco: np.ndarray, scores_rich: np.ndarray,
             k: int = 60, top_k: int = 30):
    """Reciprocal Rank Fusion of two score arrays (higher = better).
    Returns (indices, rrf_scores) for the top_k candidates."""
    n = len(scores_noco)
    rank_noco = (n - 1 - (-scores_noco).argsort().argsort()).astype(float) + 1
    rank_rich = (n - 1 - (-scores_rich).argsort().argsort()).astype(float) + 1
    rrf = 1.0 / (k + rank_noco) + 1.0 / (k + rank_rich)
    top_idx = np.argpartition(rrf, -top_k)[-top_k:]
    top_idx = top_idx[np.argsort(rrf[top_idx])[::-1]]
    return top_idx, rrf[top_idx]


def metadata_boost(query_priority, query_status, query_reporter,
                   cand_priority, cand_status, cand_reporter):
    """Per-candidate metadata boost vector (same priority/status/reporter)."""
    boost = np.zeros(len(cand_priority))
    boost += 0.10 * (np.array(cand_priority) == query_priority)
    boost += 0.08 * (np.array(cand_status)   == query_status)
    boost += 0.05 * (np.array(cand_reporter)  == query_reporter)
    return boost


def build_scaler(train_df):
    """Fit a StandardScaler on changelog features of the training set."""
    scaler = StandardScaler()
    scaler.fit(train_df[CHANGELOG_FEATURES].fillna(0).values)
    return scaler


def changelog_sim(query_cl: np.ndarray, cand_cl: np.ndarray) -> np.ndarray:
    """1 / (1 + L2 distance) in standardized changelog feature space."""
    diff = cand_cl - query_cl
    return 1.0 / (1.0 + np.linalg.norm(diff, axis=1))


def fuse_scores(rrf_scores: np.ndarray, meta_boost: np.ndarray,
                cl_sim: np.ndarray,
                alpha: float = 1.0, beta: float = 0.15, gamma: float = 0.10):
    return alpha * rrf_scores + beta * meta_boost + gamma * cl_sim


def weighted_vote(labels, weights, class_weight_map=None):
    """Weighted vote, optionally upweighting minority classes."""
    scores = {}
    for lbl, w in zip(labels, weights):
        multiplier = class_weight_map.get(lbl, 1.0) if class_weight_map else 1.0
        scores[lbl] = scores.get(lbl, 0.0) + float(w) * multiplier
    total = sum(scores.values())
    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    best_lbl = sorted_scores[0][0]
    best_val = sorted_scores[0][1]
    runner_up = sorted_scores[1][1] if len(sorted_scores) > 1 else 0.0
    l0_conf = best_val / total if total > 0 else 0.0
    margin = (best_val - runner_up) / total if total > 0 else 0.0
    return best_lbl, l0_conf, margin, scores


def route(l0_conf: float, margin: float) -> str:
    """Confidence gate: DIRECT for high-confidence, LLM_REQUIRED otherwise."""
    if l0_conf >= 0.65 and margin >= 0.10:
        return "DIRECT"
    return "LLM_REQUIRED"


def retrieve_top_k(query_emb_noco: np.ndarray, query_emb_rich: np.ndarray,
                   train_emb_noco: np.ndarray, train_emb_rich: np.ndarray,
                   train_df, query_row,
                   scaler: StandardScaler,
                   rrf_top: int = 30, final_k: int = 15):
    """
    Full retrieval pipeline for a single query ticket.
    Returns (top_k_indices, final_scores) into train_df.
    """
    scores_noco = train_emb_noco @ query_emb_noco
    scores_rich = train_emb_rich @ query_emb_rich

    top30_idx, rrf_scores = rrf_fuse(scores_noco, scores_rich, top_k=rrf_top)

    # Metadata boost on the top-30
    q_priority = query_row.get("priority", "")
    q_status   = query_row.get("status",   "")
    q_reporter = query_row.get("reporter", "")
    cands = train_df.iloc[top30_idx]
    meta = metadata_boost(
        q_priority, q_status, q_reporter,
        cands["priority"].fillna("").tolist(),
        cands["status"].fillna("").tolist(),
        cands["reporter"].fillna("").tolist(),
    )

    # Changelog similarity on the top-30
    q_cl = scaler.transform(
        np.array([[query_row.get(f, 0) for f in CHANGELOG_FEATURES]], dtype=float)
    )
    cand_cl = scaler.transform(
        cands[CHANGELOG_FEATURES].fillna(0).values
    )
    cl = changelog_sim(q_cl, cand_cl)

    final = fuse_scores(rrf_scores, meta, cl)
    best_local = np.argsort(final)[::-1][:final_k]
    return top30_idx[best_local], final[best_local]
