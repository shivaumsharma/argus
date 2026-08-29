"""
Stage 5 support -- the re-freeze/fresh-seed/re-eval sequence that runs after
a human's FIRST approval, before a recommendation can reach final review.

This formalizes the same discipline this project already uses for its
primary eval numbers (SEED=20260828: freeze parameters, generate one
dataset with a seed never used before, run the pipeline and eval exactly
once, report that run as-is) as a reusable process for this subsystem too
-- not a separate, looser standard. There is no separate "BRD Section 18"
document in this repo; this module IS that discipline, applied here.

Hard boundary, restated because it must not be relaxed: this module only
ever writes to its own disposable directory (data/adversarial_recommender/fresh_runs/<seed>/,
cleaned up after each run) and to the `recommendations` table via db.py.
It never touches data/raw/, data/frozen_snapshot/, data/processed/clusters.json,
or backend/pipeline/*.py. The proposed parameter override is applied only
in-memory, as a keyword argument to the real evaluate_cluster() -- the
source file is never edited by any code path in this package.
"""

import json
import random
import shutil
import time
from pathlib import Path

from .. import generate_data
from ..pipeline.clustering import dedupe_candidates, stage2_hard_clusters, stage3_soft_clusters
from ..pipeline.confounder_filter import evaluate_cluster
from ..pipeline.data_io import load_data
from ..pipeline.eval import best_match
from ..pipeline.features import build_lookups, compute_features
from ..pipeline.graph_build import build_graph, hard_signal_subgraph

ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = ROOT / "data" / "adversarial_recommender"
SEED_MANIFEST = STATE_DIR / "used_seeds.json"
FRESH_RUNS_DIR = STATE_DIR / "fresh_runs"

# Seeds already known to be used elsewhere in this project, seeded into the manifest the
# first time it's created, so a "fresh" seed here can never collide with an existing claim.
_KNOWN_PRIOR_SEEDS = [20260828, 2026828, 90210, 7]


def _load_seed_manifest() -> list:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if not SEED_MANIFEST.exists():
        SEED_MANIFEST.write_text(json.dumps(_KNOWN_PRIOR_SEEDS))
        return list(_KNOWN_PRIOR_SEEDS)
    return json.loads(SEED_MANIFEST.read_text())


def pick_fresh_seed() -> int:
    used = _load_seed_manifest()
    rng = random.Random()
    while True:
        candidate = rng.randint(10_000_000, 99_999_999)
        if candidate not in used:
            break
    used.append(candidate)
    SEED_MANIFEST.write_text(json.dumps(used))
    return candidate


def _run_pipeline_on(raw_dir: Path, gt_dir: Path, override_param: str = None, override_value=None):
    data = load_data(raw_dir=raw_dir)
    G = build_graph(data)
    H = hard_signal_subgraph(G)
    hard_clusters = stage2_hard_clusters(H)
    soft_clusters = stage3_soft_clusters(G)
    candidates = dedupe_candidates(hard_clusters, soft_clusters)
    device_by_user, instrument_by_user = build_lookups(data)

    kwargs = {override_param: override_value} if override_param else {}
    flagged = []
    for members, stage in candidates:
        feats = compute_features(G, members, data, device_by_user, instrument_by_user)
        verdict = evaluate_cluster(feats, **kwargs)
        if verdict["flagged"]:
            flagged.append({"members": sorted(members), "detection_stage": stage})

    rings = json.loads((gt_dir / "rings.json").read_text())
    confounders = json.loads((gt_dir / "confounders.json").read_text())

    hard_rings = {k: v for k, v in rings.items() if v["type"] == "hard"}
    soft_rings = {k: v for k, v in rings.items() if v["type"] == "soft"}
    hard_recall = sum(1 for r in hard_rings.values() if best_match(set(r["members"]), flagged)) / max(len(hard_rings), 1)
    soft_recall = sum(1 for r in soft_rings.values() if best_match(set(r["members"]), flagged)) / max(len(soft_rings), 1)
    conf_fp = sum(1 for c in confounders.values() if best_match(set(c["members"]), flagged))
    conf_fp_rate = conf_fp / max(len(confounders), 1)

    return {
        "n_hard_rings": len(hard_rings), "n_soft_rings": len(soft_rings), "n_confounders": len(confounders),
        "hard_recall": round(hard_recall, 4), "soft_recall": round(soft_recall, 4),
        "confounder_fp": conf_fp, "confounder_fp_rate": round(conf_fp_rate, 4),
        "n_flagged": len(flagged),
    }


def revalidate(gap_parameter: str, proposed_value, verbose: bool = True) -> dict:
    """The full Stage 5 governance sequence: freeze the proposed change, generate
    ONE fresh dataset with a seed never used before, run the pipeline and eval
    exactly once with and without the change, on that same fresh dataset, and
    return both results side by side. Disposable directory is removed after."""
    seed = pick_fresh_seed()
    run_dir = FRESH_RUNS_DIR / str(seed)
    raw_dir, gt_dir = run_dir / "raw", run_dir / "gt"

    if verbose:
        print(f"  Freezing proposed change ({gap_parameter} -> {proposed_value}); "
              f"generating one fresh dataset, seed={seed} (never used before)...")

    t0 = time.time()
    try:
        generate_data.generate(scale=1, raw_dir=raw_dir, gt_dir=gt_dir, seed=seed, verbose=False)
        baseline = _run_pipeline_on(raw_dir, gt_dir)
        proposed = _run_pipeline_on(raw_dir, gt_dir, override_param=gap_parameter, override_value=proposed_value)
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)

    elapsed = time.time() - t0
    report = {
        "fresh_seed": seed, "elapsed_sec": round(elapsed, 1),
        "baseline": baseline, "proposed": proposed,
        "hard_recall_delta": round(proposed["hard_recall"] - baseline["hard_recall"], 4),
        "soft_recall_delta": round(proposed["soft_recall"] - baseline["soft_recall"], 4),
        "confounder_fp_delta": proposed["confounder_fp"] - baseline["confounder_fp"],
    }
    if verbose:
        print(f"  Fresh-seed run complete ({elapsed:.1f}s). Baseline vs proposed on this never-before-seen data:")
        print(f"    Hard recall:  {baseline['hard_recall']:.1%} -> {proposed['hard_recall']:.1%}")
        print(f"    Soft recall:  {baseline['soft_recall']:.1%} -> {proposed['soft_recall']:.1%}")
        print(f"    Confounder FP: {baseline['confounder_fp']}/{baseline['n_confounders']} -> "
              f"{proposed['confounder_fp']}/{proposed['n_confounders']}")
    return report
