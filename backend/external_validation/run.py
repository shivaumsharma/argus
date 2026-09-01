"""
External validation on real, independently-labeled fraud data -- not our own
synthetic construction. YelpChi and Amazon (Rayana & Akoglu, KDD 2015 /
McAuley & Leskovec; standard benchmarks via the CARE-GNN / PC-GNN repos)
label individual reviews as genuine or fraudulent (fake-review spam), and
ship the underlying relational graphs the original papers built: same
reviewer, same product+time-window, same product+rating+time-window (Yelp);
same product, same rating-week, top-similarity text (Amazon).

The mapping onto our architecture is direct: these relation graphs ARE the
"shared attribute" edges Stage 1 would have built from raw signals, so no
edge-detection logic needs to be reused or rewritten -- only which relation
counts as a near-certain identity signal (hard) vs. a broader circumstantial
one (soft) is a judgment call, made explicit below. Stage 2 (hard-signal
connected components) and Stage 3 (Louvain) are imported from
backend.pipeline.clustering UNCHANGED -- the exact same functions already
proven on the synthetic dataset and the COD-collusion extension.

What does NOT transfer: Stage 4/5's specific behavioral features (order-value
templating, referral-claim timing) don't exist in this domain -- there's no
order or referral concept in a review dataset. The closest honest analog to
"is this cluster real fraud" is the ground truth itself: a cluster's fraud
density (fraction of its members independently labeled fraudulent by the
original authors, not by us). That substitution is stated explicitly, not
hidden.

Run: python -m backend.external_validation.run [yelpchi|amazon|both]
"""

import json
import sys
from pathlib import Path

import networkx as nx
import scipy.io as sio

from ..pipeline.clustering import dedupe_candidates, stage2_hard_clusters, stage3_soft_clusters
from ..pipeline.data_io import PROCESSED_DIR

ROOT = Path(__file__).resolve().parents[2]
FLAG_THRESHOLD = 0.5  # cluster is a "predicted ring" if more than half its members are independently labeled fraud

DATASETS = {
    "yelpchi": {
        "name": "YelpChi",
        "path": ROOT / "data" / "external" / "yelpchi" / "YelpChi.mat",
        "hard_relation": "net_rur",
        "hard_label": "same reviewer (R-U-R)",
        "hard_weight": 4.0,
        "soft_relations": [
            ("net_rtr", 1.2, "same product+month (R-T-R)"),
            ("net_rsr", 0.4, "same product+rating+week (R-S-R) -- very dense, down-weighted"),
        ],
        "source": "Rayana & Akoglu, KDD 2015 -- via github.com/YingtongDou/CARE-GNN",
    },
    "amazon": {
        "name": "Amazon",
        "path": ROOT / "data" / "external" / "amazon" / "Amazon.mat",
        "hard_relation": "net_upu",
        "hard_label": "same product reviewed (U-P-U)",
        "hard_weight": 4.0,
        # net_usu (same rating within a week) is deliberately excluded, not just down-weighted: at
        # avg degree ~597 across 11,944 nodes it is a near-complete graph -- computationally
        # prohibitive for Louvain and, more importantly, not a discriminating signal at that density
        # (almost everyone shares a rating-week with almost everyone else). This is the same judgment
        # Stage 5's philosophy already makes on our own data: an overly-broad shared attribute earns
        # suspicion, not weight.
        "soft_relations": [
            ("net_uvu", 1.0, "top-5% TF-IDF text similarity (U-V-U)"),
        ],
        "excluded_relations": [("net_usu", "same rating within a week (U-S-U) -- avg degree ~597, near-complete graph, excluded as non-discriminating and computationally prohibitive")],
        "source": "McAuley & Leskovec -- via github.com/YingtongDou/CARE-GNN",
    },
}


def evaluate(dataset_key: str, verbose=True):
    cfg = DATASETS[dataset_key]
    m = sio.loadmat(cfg["path"])
    labels = m["label"].flatten().astype(int)
    n = len(labels)
    total_fraud = int(labels.sum())
    base_rate = total_fraud / n

    hard_mat = m[cfg["hard_relation"]]
    H = nx.from_scipy_sparse_array(hard_mat)

    combined = cfg["hard_weight"] * hard_mat
    signal_notes = [f"{cfg['hard_label']}: hard, weight {cfg['hard_weight']}"]
    for rel, w, label in cfg["soft_relations"]:
        combined = combined + w * m[rel]
        signal_notes.append(f"{label}: soft, weight {w}")
    for rel, label in cfg.get("excluded_relations", []):
        signal_notes.append(f"{label}: EXCLUDED")
    G = nx.from_scipy_sparse_array(combined)

    hard_clusters = stage2_hard_clusters(H)          # unmodified import
    soft_clusters = stage3_soft_clusters(G)           # unmodified import
    candidates = dedupe_candidates(hard_clusters, soft_clusters)

    rows = []
    for members, stage in candidates:
        members = sorted(members)
        size = len(members)
        frauds = int(labels[members].sum())
        rows.append({"stage": stage, "size": size, "frauds": frauds, "fraud_density": frauds / size})

    flagged = [r for r in rows if r["fraud_density"] > FLAG_THRESHOLD]
    hard_flagged = [r for r in flagged if r["stage"] == "hard"]
    soft_flagged = [r for r in flagged if r["stage"] == "soft"]

    captured_fraud = sum(r["frauds"] for r in flagged)
    captured_total = sum(r["size"] for r in flagged)
    recall = captured_fraud / total_fraud if total_fraud else float("nan")
    precision = captured_fraud / captured_total if captured_total else float("nan")
    lift = (precision / base_rate) if base_rate else float("nan")

    largest = max((r["size"] for r in rows), default=0)

    report = {
        "dataset": cfg["name"], "source": cfg["source"], "signals": signal_notes,
        "n_nodes": n, "total_fraud": total_fraud, "base_fraud_rate": round(base_rate, 4),
        "n_candidates": len(rows), "n_hard_candidates": len(hard_clusters), "n_soft_candidates": len(soft_clusters),
        "largest_candidate_size": largest,
        "n_flagged": len(flagged), "n_flagged_hard": len(hard_flagged), "n_flagged_soft": len(soft_flagged),
        "fraud_recall": round(recall, 4), "flagged_cluster_precision": round(precision, 4),
        "lift_over_base_rate": round(lift, 2),
        "captured_fraud_nodes": captured_fraud, "captured_total_nodes": captured_total,
    }

    if verbose:
        print(f"\n=== {cfg['name']} ({cfg['source']}) ===")
        print(f"Nodes: {n:,} | Independently-labeled fraud: {total_fraud:,} ({base_rate:.1%} base rate)")
        print("Signals used:")
        for s in signal_notes:
            print(f"  - {s}")
        print(f"Candidates: {len(rows)} ({len(hard_clusters)} hard, {len(soft_clusters)} soft) | largest: {largest} nodes")
        print(f"Flagged (fraud density > {FLAG_THRESHOLD:.0%}): {len(flagged)} ({len(hard_flagged)} hard, {len(soft_flagged)} soft)")
        print(f"Fraud recall (fraud nodes captured in a flagged cluster): {recall:.1%} ({captured_fraud:,}/{total_fraud:,})")
        print(f"Flagged-cluster precision: {precision:.1%}  (vs. {base_rate:.1%} base rate -> {lift:.1f}x lift)")

    return report, rows


def run_and_save(verbose=True):
    """Runs YelpChi, Amazon, and Elliptic (the same unmodified functions the docs and CLI use)
    and persists one combined JSON for the dashboard -- so the External Validation tab reads the
    same live-computed numbers as EXTERNAL_VALIDATION.md, not a hand-copied duplicate."""
    from . import elliptic as elliptic_module

    yelpchi_report, _ = evaluate("yelpchi", verbose=verbose)
    amazon_report, _ = evaluate("amazon", verbose=verbose)
    elliptic_report = elliptic_module.run(verbose=verbose)

    combined = {"yelpchi": yelpchi_report, "amazon": amazon_report, "elliptic": elliptic_report}
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out_path = PROCESSED_DIR / "external_validation.json"
    with open(out_path, "w") as f:
        json.dump(combined, f, indent=2)
    if verbose:
        print(f"\nWritten -> {out_path}")
    return combined


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "both"
    if target == "all":
        run_and_save()
    else:
        keys = ["yelpchi", "amazon"] if target == "both" else [target]
        for k in keys:
            evaluate(k)
