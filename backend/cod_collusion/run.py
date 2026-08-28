"""
Orchestrates the COD-collusion pipeline end to end, and is the actual proof
of the BRD's stretch claim: Stage 2 (hard-signal connected components) and
Stage 3 (Louvain community detection) are imported from backend.pipeline
UNCHANGED -- not reimplemented, not adapted, the literal same functions fed
a graph built from a different edge vocabulary. Only Stage 1 (graph
construction), Stage 4 (feature scoring), and Stage 5 (the filter) are
loss-type-specific, because the signals and behavioral tells genuinely
differ between "referral bonus farming" and "order-then-refuse collusion."

Run: python -m backend.cod_collusion.run
"""

import json
import time
from pathlib import Path

from ..pipeline.clustering import dedupe_candidates, stage2_hard_clusters, stage3_soft_clusters
from . import graph_build
from .features import compute_features
from .filter import evaluate_cluster

ROOT = Path(__file__).resolve().parents[2]
GT_DIR = ROOT / "data" / "cod" / "ground_truth"
PROCESSED_DIR = ROOT / "data" / "cod" / "processed"
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


def run(verbose=True):
    t0 = time.time()
    accounts, orders = graph_build.load_data()
    G = graph_build.build_graph(accounts)
    H = graph_build.hard_signal_subgraph(G)

    hard_clusters = stage2_hard_clusters(H)          # unmodified import from backend.pipeline.clustering
    soft_clusters = stage3_soft_clusters(G)           # unmodified import from backend.pipeline.clustering
    candidates = dedupe_candidates(hard_clusters, soft_clusters)

    results = []
    for i, (members, stage) in enumerate(candidates):
        feats = compute_features(G, members, accounts, orders)
        verdict = evaluate_cluster(feats)
        results.append({
            "cluster_id": f"CC{i+1:04d}", "detection_stage": stage, "members": sorted(members),
            "features": feats, "flagged": verdict["flagged"], "filter_reason": verdict["reason"],
        })

    with open(PROCESSED_DIR / "clusters.json", "w") as f:
        json.dump(results, f, indent=2)

    elapsed = time.time() - t0
    if verbose:
        n_flagged = sum(1 for r in results if r["flagged"])
        print(f"Graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges (hard subgraph: {H.number_of_edges()} edges)")
        print(f"Stage 2 (hard connected components, reused unchanged): {len(hard_clusters)} candidates")
        print(f"Stage 3 (Louvain, reused unchanged): {len(soft_clusters)} candidates")
        print(f"Deduped candidates: {len(candidates)}")
        print(f"Flagged after Stage 5 filter: {n_flagged} / {len(results)}")
        print(f"Runtime: {elapsed:.2f}s")

    return results


def best_match(members: set, clusters: list, thresh: float = 0.5):
    best = None
    for c in clusters:
        cset = set(c["members"])
        inter = len(members & cset)
        if inter and inter / len(members) >= thresh and inter / len(cset) >= thresh:
            best = c
            break
    return best


def evaluate(results, verbose=True):
    with open(GT_DIR / "rings.json") as f:
        rings = json.load(f)
    with open(GT_DIR / "confounders.json") as f:
        confounders = json.load(f)

    flagged = [r for r in results if r["flagged"]]
    ring_hits = sum(1 for r in rings.values() if best_match(set(r["members"]), flagged) is not None)
    conf_hits = sum(1 for c in confounders.values() if best_match(set(c["members"]), flagged) is not None)

    recall = ring_hits / len(rings) if rings else float("nan")
    fp_rate = conf_hits / len(confounders) if confounders else float("nan")

    report = {
        "n_rings": len(rings), "rings_detected": ring_hits, "ring_recall": recall,
        "n_confounders": len(confounders), "confounders_wrongly_flagged": conf_hits, "confounder_fp_rate": fp_rate,
    }
    with open(PROCESSED_DIR / "eval_report.json", "w") as f:
        json.dump(report, f, indent=2)

    if verbose:
        print(f"\nCOD collusion ring recall: {recall:.1%} ({ring_hits}/{len(rings)})")
        print(f"COD confounder false-positive rate: {fp_rate:.1%} ({conf_hits}/{len(confounders)})")

    return report


if __name__ == "__main__":
    results = run()
    evaluate(results)
