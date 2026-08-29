"""
Scale stress test: does this actually survive more than a demo-sized cohort?

Reruns the exact same pipeline (backend/pipeline/) at 10x and 50x the frozen
dataset's account count (75,000 and 375,000 accounts) and reports the real,
measured runtime curve for every stage -- not an assertion that it scales,
an actual timed answer.

Safety: this NEVER touches the frozen dataset. Generation for each scale
runs in its own subprocess via `python -m backend.generate_data --scale N
--raw-dir ... --gt-dir ...`, writing only to data/scale_test/<N>x/ -- a
clean, isolated output directory per scale, never data/raw/. Pipeline
timing then loads directly from that directory (`load_data(raw_dir=...)`)
and calls the same Stage 1-5 functions used everywhere else in this repo,
unchanged -- it never calls db.write_clusters() or writes to
data/processed/clusters.json, so data/app.db (the live dashboard's backing
store) is never touched either. The 1x baseline reported alongside 10x/50x
is the real frozen dataset's own pipeline timing, measured fresh here
rather than assumed.

Ring/confounder counts scale proportionally with account count (40 hard +
40 soft rings + 40 confounders at 1x -> 400+400+400 at 10x, etc.) rather
than holding them fixed while only background noise grows -- a fixed fraud
rate as volume grows is the more realistic assumption, and it also
exercises Stage 2-5 against proportionally more candidate clusters, not
just a bigger but structurally identical graph.

Run: python -m backend.scale_stress_test            # 10x and 50x
     python -m backend.scale_stress_test --scales 10  # just 10x, faster
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from .pipeline.clustering import dedupe_candidates, stage2_hard_clusters, stage3_soft_clusters
from .pipeline.confounder_filter import evaluate_cluster
from .pipeline.data_io import RAW_DIR as FROZEN_RAW_DIR
from .pipeline.data_io import PROCESSED_DIR, load_data
from .pipeline.features import build_lookups, compute_features
from .pipeline.graph_build import build_graph, hard_signal_subgraph

ROOT = Path(__file__).resolve().parents[1]
SCALE_TEST_DIR = ROOT / "data" / "scale_test"
SCALE_SEED = 90210  # deliberately different from the frozen SEED=20260828 -- this is a timing test, not an eval claim


def time_pipeline(raw_dir: Path):
    """Times each stage exactly as run_pipeline.py does, but never writes to
    the DB or data/processed/ -- pure in-memory timing against a given raw_dir."""
    t = {}

    t0 = time.time()
    data = load_data(raw_dir=raw_dir)
    t["load_data"] = time.time() - t0

    t0 = time.time()
    G = build_graph(data)
    H = hard_signal_subgraph(G)
    t["stage1_graph_build"] = time.time() - t0

    t0 = time.time()
    hard_clusters = stage2_hard_clusters(H)
    t["stage2_hard_clustering"] = time.time() - t0

    t0 = time.time()
    soft_clusters = stage3_soft_clusters(G)
    t["stage3_louvain"] = time.time() - t0

    candidates = dedupe_candidates(hard_clusters, soft_clusters)

    t0 = time.time()
    device_by_user, instrument_by_user = build_lookups(data)
    features_by_cluster = [compute_features(G, members, data, device_by_user, instrument_by_user)
                            for members, _stage in candidates]
    t["stage4_feature_scoring"] = time.time() - t0

    t0 = time.time()
    for feats in features_by_cluster:
        evaluate_cluster(feats)
    t["stage5_confounder_filter"] = time.time() - t0

    t["total_pipeline"] = sum(v for k, v in t.items() if k != "total_pipeline")

    return {
        "timings_sec": {k: round(v, 3) for k, v in t.items()},
        "n_accounts": len(data.accounts),
        "n_graph_nodes": G.number_of_nodes(),
        "n_graph_edges": G.number_of_edges(),
        "n_hard_subgraph_edges": H.number_of_edges(),
        "n_hard_clusters": len(hard_clusters),
        "n_soft_clusters": len(soft_clusters),
        "n_candidate_clusters": len(candidates),
    }


def run_scale(scale: int, verbose=True):
    scale_dir = SCALE_TEST_DIR / f"{scale}x"
    raw_dir = scale_dir / "raw"
    gt_dir = scale_dir / "gt"

    if verbose:
        print(f"\n=== {scale}x scale ({7500 * scale:,} target accounts) ===")

    t0 = time.time()
    result = subprocess.run(
        [sys.executable, "-m", "backend.generate_data", "--scale", str(scale),
         "--raw-dir", str(raw_dir), "--gt-dir", str(gt_dir), "--seed", str(SCALE_SEED)],
        capture_output=True, text=True, cwd=str(ROOT),
    )
    generation_time = time.time() - t0
    if result.returncode != 0:
        raise RuntimeError(f"Generation subprocess failed at scale={scale}:\n{result.stderr}")

    if verbose:
        print(f"Generation: {generation_time:.1f}s")

    pipeline_stats = time_pipeline(raw_dir)
    pipeline_stats["generation_time_sec"] = round(generation_time, 2)

    if verbose:
        print(f"Graph: {pipeline_stats['n_graph_nodes']:,} nodes, {pipeline_stats['n_graph_edges']:,} edges "
              f"(hard subgraph: {pipeline_stats['n_hard_subgraph_edges']:,} edges)")
        print(f"Candidate clusters: {pipeline_stats['n_candidate_clusters']:,} "
              f"({pipeline_stats['n_hard_clusters']:,} hard + {pipeline_stats['n_soft_clusters']:,} soft)")
        for stage, secs in pipeline_stats["timings_sec"].items():
            print(f"  {stage:<28}{secs:>8.2f}s")

    return pipeline_stats


def run(scales=(10, 50), verbose=True):
    results = {"1x": None, **{f"{s}x": None for s in scales}}

    # 1x baseline: the real frozen dataset, timed fresh here (read-only, never
    # writes anywhere -- load_data() only reads CSVs).
    if verbose:
        print("=== 1x scale (frozen dataset, 7,500 accounts) ===")
    results["1x"] = time_pipeline(FROZEN_RAW_DIR)
    results["1x"]["generation_time_sec"] = None  # not regenerated; this is the already-frozen dataset
    if verbose:
        for stage, secs in results["1x"]["timings_sec"].items():
            print(f"  {stage:<28}{secs:>8.2f}s")

    for scale in scales:
        results[f"{scale}x"] = run_scale(scale, verbose=verbose)

    with open(PROCESSED_DIR / "scale_stress_test.json", "w") as f:
        json.dump(results, f, indent=2)

    if verbose:
        labels = ["1x"] + [f"{s}x" for s in scales]
        print(f"\n=== Runtime curve summary ===")
        print(f"{'Scale':<8}{'Accounts':<12}{'Graph edges':<14}{'Candidates':<12}{'Stage 3 (Louvain)':<20}{'Total pipeline'}")
        for label in labels:
            r = results[label]
            print(f"{label:<8}{r['n_accounts']:<12,}{r['n_graph_edges']:<14,}{r['n_candidate_clusters']:<12,}"
                  f"{r['timings_sec']['stage3_louvain']:<20.2f}{r['timings_sec']['total_pipeline']:.2f}s")
        print(f"\nWritten -> {PROCESSED_DIR / 'scale_stress_test.json'}")
        print(f"Scale-test datasets -> {SCALE_TEST_DIR} (never touches data/raw/ or data/app.db)")

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--scales", type=int, nargs="+", default=[10, 50])
    args = parser.parse_args()
    run(scales=tuple(args.scales))
