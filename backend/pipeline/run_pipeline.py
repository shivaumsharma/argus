"""Orchestrates Stages 1-5 end to end and writes data/processed/clusters.json."""

import json
import time

from .. import db
from .clustering import dedupe_candidates, stage2_hard_clusters, stage3_soft_clusters
from .confounder_filter import evaluate_cluster
from .data_io import PROCESSED_DIR, load_data
from .features import build_lookups, compute_features
from .graph_build import build_graph, hard_signal_subgraph


def run(resolution: float = None, verbose: bool = True):
    t0 = time.time()
    data = load_data()

    G = build_graph(data)
    H = hard_signal_subgraph(G)

    hard_clusters = stage2_hard_clusters(H)
    from .clustering import LOUVAIN_RESOLUTION
    soft_clusters = stage3_soft_clusters(G, resolution=resolution or LOUVAIN_RESOLUTION)
    candidates = dedupe_candidates(hard_clusters, soft_clusters)

    device_by_user, instrument_by_user = build_lookups(data)

    results = []
    for i, (members, stage) in enumerate(candidates):
        feats = compute_features(G, members, data, device_by_user, instrument_by_user)
        verdict = evaluate_cluster(feats)
        results.append({
            "cluster_id": f"C{i + 1:04d}",
            "detection_stage": stage,
            "members": sorted(members),
            "features": feats,
            "flagged": verdict["flagged"],
            "filter_reason": verdict["reason"],
            "organic_score": verdict["organic_score"],
            "suspicion_score": verdict["suspicion_score"],
        })

    with open(PROCESSED_DIR / "clusters.json", "w") as f:
        json.dump(results, f, indent=2)
    db.write_clusters(results)

    elapsed = time.time() - t0
    if verbose:
        n_flagged = sum(1 for r in results if r["flagged"])
        print(f"Graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges "
              f"(hard subgraph: {H.number_of_edges()} edges)")
        print(f"Stage 2 (hard connected components): {len(hard_clusters)} candidates")
        print(f"Stage 3 (Louvain, full graph, resolution={resolution or LOUVAIN_RESOLUTION}): {len(soft_clusters)} candidates")
        print(f"Deduped candidate clusters: {len(candidates)}")
        print(f"Flagged after Stage 5 confounder filter: {n_flagged} / {len(results)}")
        print(f"Pipeline runtime: {elapsed:.2f}s")
        print(f"Written -> {PROCESSED_DIR / 'clusters.json'}")

    return results


if __name__ == "__main__":
    run()
