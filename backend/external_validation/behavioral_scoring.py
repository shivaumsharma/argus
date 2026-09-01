"""
A real Stage 4/5-equivalent for YelpChi and Amazon, replacing the bare
`fraud_density > threshold` rule that `run.py`'s `evaluate()` has used until
now -- confirmed structurally identical to the gap already documented for
Elliptic (elliptic.py's own docstring: "one bare density > 50% rule...
substituted for the entire Stage 4+5 decision logic"). `evaluate()`'s
`fraud_density` uses the ground-truth label itself as the score (the mean of
`labels[members]` over a candidate cluster) -- Stage 4/5 in the primary
system never do that; they score a candidate cluster on BEHAVIORAL evidence
and never look at ground truth at all.

This module trains a REAL classifier -- logistic regression and a
gradient-boosted tree (XGBoost) -- on each dataset's genuine per-node
handcrafted features (32-dim YelpChi, Rayana & Akoglu; 25-dim Amazon, Zhang
et al. 2020), never the label itself as an input:

  HARD RULE, never relaxed: the ground-truth label is the TRAINING TARGET
  (as it must be for any supervised classifier -- that is not leakage, it is
  what supervised learning means) and is NEVER an input feature, directly or
  as any derived quantity, at training-input or inference time. No
  cluster-average-of-labels, no neighbor-label-fraction, nothing built from
  the answer key anywhere in the feature vector a model sees. Verified by
  construction: `X` is always exactly `features[node_ids]` (the .mat file's
  opaque handcrafted feature matrix, which contains no label information --
  confirmed by direct inspection, see docs/EXTERNAL_VALIDATION.md), never
  concatenated with anything derived from `labels`.

Split discipline, mirroring `pipeline/eval.py`'s dev/holdout protocol exactly,
extended to three-way: TRAIN (fit the model) / DEV (feature-selection-free
here since all 32/25 features are used, but used for model-family selection,
hyperparameter search, and picking the cluster-aggregate operating
threshold) / TEST (touched exactly once, at the end, to report the numbers
in this module's own docstring and any doc that cites it). The prior version
of this module (Cohen's-d feature selection + summed z-scores, a first-pass
heuristic) is kept here as `heuristic_suspicion_score()` for direct,
labeled comparison -- not because it's still the recommended method, but
because reporting "here's what a blunt first pass got vs. a real trained
model" is more honest than quietly deleting the earlier attempt.

Run: python -m backend.external_validation.behavioral_scoring [yelpchi|amazon|both]
"""

import sys

import numpy as np
import scipy.io as sio

from ..pipeline.clustering import dedupe_candidates, stage2_hard_clusters, stage3_soft_clusters
from .run import DATASETS

TRAIN_FRACTION = 0.60
DEV_FRACTION = 0.15
# TEST_FRACTION is whatever remains (0.25) -- computed, not hardcoded twice.
SPLIT_SEED = 7               # same literal seed pipeline/eval.py's HOLDOUT_SEED uses
TOP_K_FEATURES = 6           # kept only for the heuristic (superseded) method, for its own comparability


def _load_graph_inputs(dataset_key: str):
    """Rebuilds exactly the same candidate clusters run.py's evaluate() uses --
    same imports, same relation weighting, same stage2/stage3 calls, unchanged.
    Only what happens AFTER candidates exist (the flagging rule) is new here."""
    import networkx as nx
    cfg = DATASETS[dataset_key]
    m = sio.loadmat(cfg["path"])
    labels = m["label"].flatten().astype(int)
    features = m["features"]
    features = features.toarray() if hasattr(features, "toarray") else np.asarray(features)

    hard_mat = m[cfg["hard_relation"]]
    H = nx.from_scipy_sparse_array(hard_mat)
    combined = cfg["hard_weight"] * hard_mat
    for rel, w, _ in cfg["soft_relations"]:
        combined = combined + w * m[rel]
    G = nx.from_scipy_sparse_array(combined)

    hard_clusters = stage2_hard_clusters(H)
    soft_clusters = stage3_soft_clusters(G)
    candidates = dedupe_candidates(hard_clusters, soft_clusters)
    return labels, features, candidates


def _three_way_split(n_nodes: int, train_frac=TRAIN_FRACTION, dev_frac=DEV_FRACTION, seed=SPLIT_SEED):
    """One fixed random permutation, sliced three ways -- deterministic and
    reproducible for a given seed, no class stratification beyond what a
    uniform random split naturally gives on a large-enough n."""
    rng = np.random.RandomState(seed)
    perm = rng.permutation(n_nodes)
    n_train = int(n_nodes * train_frac)
    n_dev = int(n_nodes * dev_frac)
    split = np.empty(n_nodes, dtype=object)
    split[perm[:n_train]] = "train"
    split[perm[n_train:n_train + n_dev]] = "dev"
    split[perm[n_train + n_dev:]] = "test"
    return split


# --------------------------------------------------------------------------
# Heuristic (superseded): Cohen's-d feature selection + summed z-scores.
# Kept for direct, labeled comparison against the real trained models below.
# --------------------------------------------------------------------------

def _select_features_and_signs(features, labels, train_mask, k=TOP_K_FEATURES):
    idx = np.where(train_mask)[0]
    tr_labels, tr_feats = labels[idx], features[idx]
    fraud_mask, organic_mask = tr_labels == 1, tr_labels == 0

    n_features = features.shape[1]
    effect_sizes = np.zeros(n_features)
    for j in range(n_features):
        col = tr_feats[:, j]
        mu_f, mu_o = col[fraud_mask].mean(), col[organic_mask].mean()
        pooled_std = np.sqrt((col[fraud_mask].var() + col[organic_mask].var()) / 2)
        effect_sizes[j] = (mu_f - mu_o) / pooled_std if pooled_std > 1e-9 else 0.0

    top_idx = np.argsort(-np.abs(effect_sizes))[:k]
    signs = np.sign(effect_sizes[top_idx])
    signs[signs == 0] = 1.0
    means, stds = tr_feats[:, top_idx].mean(axis=0), tr_feats[:, top_idx].std(axis=0)
    stds[stds < 1e-9] = 1.0
    return {"feature_indices": top_idx.tolist(), "effect_sizes": effect_sizes[top_idx].tolist(),
            "signs": signs.tolist(), "means": means.tolist(), "stds": stds.tolist()}


def heuristic_suspicion_score(features, selection):
    idx = selection["feature_indices"]
    z = (features[:, idx] - np.array(selection["means"])) / np.array(selection["stds"])
    return (z * np.array(selection["signs"])).mean(axis=1)


# --------------------------------------------------------------------------
# Real trained classifiers: logistic regression + gradient-boosted trees.
# --------------------------------------------------------------------------

def _fit_logistic_regression(X_train, y_train, X_dev, y_dev):
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score
    from sklearn.preprocessing import StandardScaler

    scaler = StandardScaler().fit(X_train)
    Xtr, Xdv = scaler.transform(X_train), scaler.transform(X_dev)

    best = None
    for C in (0.001, 0.01, 0.1, 1.0, 10.0, 100.0):
        clf = LogisticRegression(C=C, max_iter=5000, class_weight="balanced")
        clf.fit(Xtr, y_train)
        dev_auc = roc_auc_score(y_dev, clf.predict_proba(Xdv)[:, 1])
        if best is None or dev_auc > best[0]:
            best = (dev_auc, C, clf)
    dev_auc, best_C, clf = best
    return {"kind": "logistic_regression", "predict": lambda X: clf.predict_proba(scaler.transform(X))[:, 1],
            "chosen_hyperparameters": {"C": best_C}, "dev_auc": round(float(dev_auc), 4)}


def _fit_xgboost(X_train, y_train, X_dev, y_dev):
    import xgboost as xgb
    from sklearn.metrics import roc_auc_score

    n_pos, n_neg = int(y_train.sum()), int((y_train == 0).sum())
    scale_pos_weight = n_neg / n_pos if n_pos else 1.0

    best = None
    for max_depth in (3, 4, 6):
        for n_estimators in (100, 300):
            clf = xgb.XGBClassifier(
                max_depth=max_depth, n_estimators=n_estimators, learning_rate=0.1,
                scale_pos_weight=scale_pos_weight, eval_metric="auc",
                random_state=SPLIT_SEED, n_jobs=-1,
            )
            clf.fit(X_train, y_train, eval_set=[(X_dev, y_dev)], verbose=False)
            dev_auc = roc_auc_score(y_dev, clf.predict_proba(X_dev)[:, 1])
            if best is None or dev_auc > best[0]:
                best = (dev_auc, {"max_depth": max_depth, "n_estimators": n_estimators}, clf)
    dev_auc, params, clf = best
    return {"kind": "xgboost", "predict": lambda X: clf.predict_proba(X)[:, 1],
            "chosen_hyperparameters": params, "dev_auc": round(float(dev_auc), 4)}


# --------------------------------------------------------------------------
# Cluster-level aggregation and evaluation (shared by every method)
# --------------------------------------------------------------------------

def _cluster_rows(candidates, labels, node_scores, split, split_name):
    """One row per candidate cluster, restricted to members in `split_name`
    (dev or test) -- the split used for training never leaks into these rows."""
    rows = []
    for members, stage in candidates:
        members = sorted(members)
        subset = [m for m in members if split[m] == split_name]
        if not subset:
            continue
        s_labels = labels[subset]
        s_scores = node_scores[subset]
        rows.append({"stage": stage, "n": len(subset), "frauds": int(s_labels.sum()),
                     "mean_score": float(s_scores.mean())})
    return rows


def _sweep(rows, total_fraud, thresholds):
    out = []
    for t in thresholds:
        flagged = [r for r in rows if r["mean_score"] > t]
        captured_fraud = sum(r["frauds"] for r in flagged)
        captured_total = sum(r["n"] for r in flagged)
        recall = captured_fraud / total_fraud if total_fraud else float("nan")
        precision = captured_fraud / captured_total if captured_total else float("nan")
        out.append({"threshold": round(float(t), 5), "n_flagged": len(flagged),
                     "captured_total": captured_total, "captured_fraud": captured_fraud,
                     "recall": round(recall, 4), "precision": round(precision, 4)})
    return out


def _threshold_for_target_recall(sweep_rows, target_recall):
    """The threshold whose recall is closest to (and, tie-broken toward, at or
    above) target_recall -- chosen ONCE on dev, then applied as-is to test."""
    candidates = [r for r in sweep_rows if r["recall"] is not None and r["recall"] == r["recall"]]
    if not candidates:
        return None
    above = [r for r in candidates if r["recall"] >= target_recall]
    pool = above if above else candidates
    return min(pool, key=lambda r: abs(r["recall"] - target_recall))


def _evaluate_method(name, node_scores, candidates, labels, split, dev_total_fraud, test_total_fraud,
                      target_recall, thresholds):
    dev_rows = _cluster_rows(candidates, labels, node_scores, split, "dev")
    test_rows = _cluster_rows(candidates, labels, node_scores, split, "test")
    dev_sweep = _sweep(dev_rows, dev_total_fraud, thresholds)
    test_sweep = _sweep(test_rows, test_total_fraud, thresholds)

    chosen = _threshold_for_target_recall(dev_sweep, target_recall)
    test_at_chosen = None
    if chosen is not None:
        test_at_chosen = next((r for r in test_sweep if r["threshold"] == chosen["threshold"]), None)

    return {"name": name, "dev_sweep": dev_sweep, "test_sweep": test_sweep,
            "dev_chosen_threshold": chosen, "test_result_at_dev_chosen_threshold": test_at_chosen}


def evaluate_behavioral(dataset_key: str, verbose=True):
    cfg = DATASETS[dataset_key]
    labels, features, candidates = _load_graph_inputs(dataset_key)
    n_nodes = len(labels)
    split = _three_way_split(n_nodes)
    train_mask = split == "train"
    dev_mask = split == "dev"
    test_mask = split == "test"

    # Split, not tuple-assigned -- kept as two separate lines on purpose so the
    # no_label_leakage_test.py safeguard can check X's construction line in
    # isolation from y's, without a tuple-unpacking line confusing the two.
    X_train = features[train_mask]
    y_train = labels[train_mask]
    X_dev = features[dev_mask]
    y_dev = labels[dev_mask]
    dev_total_fraud = int(y_dev.sum())
    test_total_fraud = int(labels[test_mask].sum())

    if verbose:
        print(f"\n=== {cfg['name']}: real trained classifiers vs. the label-density baseline "
              f"vs. the superseded heuristic ===")
        print(f"Nodes: {n_nodes:,} | train={int(train_mask.sum()):,} dev={int(dev_mask.sum()):,} "
              f"test={int(test_mask.sum()):,} | dev fraud={dev_total_fraud:,} test fraud={test_total_fraud:,}")

    # Heuristic (superseded) -- feature selection on train only, exactly like before.
    selection = _select_features_and_signs(features, labels, train_mask)
    heuristic_scores = heuristic_suspicion_score(features, selection)
    heuristic_thresholds = np.quantile(heuristic_scores, np.linspace(0.01, 0.99, 60))

    # Logistic regression -- fit on train, model selection on dev.
    lr = _fit_logistic_regression(X_train, y_train, X_dev, y_dev)
    lr_scores = lr["predict"](features)

    # XGBoost -- fit on train, model selection on dev.
    xg = _fit_xgboost(X_train, y_train, X_dev, y_dev)
    xg_scores = xg["predict"](features)

    prob_thresholds = np.quantile(np.concatenate([lr_scores, xg_scores]), np.linspace(0.01, 0.999, 80))

    # Target recall: the operating point the OLD heuristic (2-way dev/holdout version, reported
    # previously) landed on, so the comparison in raw counts is at a comparable recall level --
    # 48.0% YelpChi, 5.7% Amazon, taken from that prior run, not re-derived here to avoid moving
    # the goalposts.
    target_recall = {"yelpchi": 0.48, "amazon": 0.057}[dataset_key]

    methods = {}
    methods["heuristic_superseded"] = _evaluate_method(
        "heuristic (Cohen's-d + z-score, superseded)", heuristic_scores, candidates, labels, split,
        dev_total_fraud, test_total_fraud, target_recall, heuristic_thresholds)
    methods["logistic_regression"] = _evaluate_method(
        "logistic regression", lr_scores, candidates, labels, split,
        dev_total_fraud, test_total_fraud, target_recall, prob_thresholds)
    methods["xgboost"] = _evaluate_method(
        "XGBoost", xg_scores, candidates, labels, split,
        dev_total_fraud, test_total_fraud, target_recall, prob_thresholds)

    report = {
        "dataset": cfg["name"], "n_nodes": n_nodes,
        "n_train": int(train_mask.sum()), "n_dev": int(dev_mask.sum()), "n_test": int(test_mask.sum()),
        "dev_total_fraud": dev_total_fraud, "test_total_fraud": test_total_fraud,
        "target_recall": target_recall,
        "logistic_regression_model": {"chosen_hyperparameters": lr["chosen_hyperparameters"], "dev_auc": lr["dev_auc"]},
        "xgboost_model": {"chosen_hyperparameters": xg["chosen_hyperparameters"], "dev_auc": xg["dev_auc"]},
        "heuristic_selected_features": selection,
        "methods": methods,
    }

    if verbose:
        print(f"Logistic regression: dev AUC={lr['dev_auc']:.4f}, chosen C={lr['chosen_hyperparameters']['C']}")
        print(f"XGBoost: dev AUC={xg['dev_auc']:.4f}, chosen params={xg['chosen_hyperparameters']}")
        print(f"\n=== Held-out TEST results, applying each method's DEV-chosen threshold exactly once ===")
        print(f"(target recall ~{target_recall:.1%}, matching the prior heuristic's own reported operating point)")
        for key, m in methods.items():
            r = m["test_result_at_dev_chosen_threshold"]
            if r:
                print(f"  {m['name']}: TEST recall={r['recall']:.1%}, precision={r['precision']:.1%}, "
                      f"caught={r['captured_fraud']}, wrongly_flagged={r['captured_total']-r['captured_fraud']}, "
                      f"n_flagged_clusters={r['n_flagged']}")
            else:
                print(f"  {m['name']}: no dev threshold reached the target recall")

    return report


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "both"
    keys = ["yelpchi", "amazon"] if target == "both" else [target]
    for k in keys:
        evaluate_behavioral(k)
