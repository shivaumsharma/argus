"""
Isolates the real cause of the FRAUDAR hard-signal recall drop (15/40 -> 5/40,
37.5% -> 12.5%) reported in docs/FRAUDAR_CROSSCHECK.md, which explicitly left
this unresolved: "this test has not run multiple seeds to separate 'more
confounder density' from ordinary seed-to-seed variance as the cause."

Two changes happened together in the same re-freeze: the seed changed
(20260828 -> 51238923) AND USE_GROUNDED_DEVICE_SHARING flipped False -> True.
Conflating them means the drop could be either. This isolates them by holding
one fixed while varying the other, generating three disposable datasets (never
touching data/raw/ or data/ground_truth/) in a tempdir, cleaned up in `finally`
-- same disposable-dir pattern as adversarial_stress_test.py:

  A. seed=20260828, grounding=OFF  -- reproduces the ORIGINAL pre-refreeze dataset
  B. seed=51238923, grounding=OFF  -- isolates the SEED-ONLY effect (holds grounding fixed)
  C. seed=51238923, grounding=ON   -- the CURRENT committed dataset (isolates the
                                       grounding-only effect vs. B, holding seed fixed)

A vs B isolates ordinary seed-to-seed variance. B vs C isolates the grounding
recalibration's own effect, with the seed held constant. FRAUDAR's own
detection mechanism (fast_greedy_decreasing / detect_top_k_blocks) is reused
completely unchanged from fraudar_analysis.py -- only which raw_dir/gt_dir it
reads from changes.

Run: python -m backend.fraudar_seed_isolation
"""

import shutil
import tempfile
from pathlib import Path

from . import generate_data
from .fraudar_analysis import N_BLOCKS, build_bipartite_graph, detect_top_k_blocks, raw_overlap
from .pipeline.eval import MATCH_THRESH

VARIANTS = [
    {"label": "A: old seed, grounding OFF (original pre-refreeze dataset)", "seed": 20260828, "grounding": False},
    {"label": "B: new seed, grounding OFF (isolates seed-only effect)", "seed": 51238923, "grounding": False},
    {"label": "C: new seed, grounding ON (the current committed dataset)", "seed": 51238923, "grounding": True},
]


def run_variant(seed: int, grounding: bool, tmp_root: Path, verbose=True):
    raw_dir = tmp_root / f"raw_{seed}_{grounding}"
    gt_dir = tmp_root / f"gt_{seed}_{grounding}"
    raw_dir.mkdir(parents=True, exist_ok=True)
    gt_dir.mkdir(parents=True, exist_ok=True)

    original_flag = generate_data.USE_GROUNDED_DEVICE_SHARING
    generate_data.USE_GROUNDED_DEVICE_SHARING = grounding
    try:
        generate_data.generate(raw_dir=raw_dir, gt_dir=gt_dir, seed=seed, verbose=False)
    finally:
        generate_data.USE_GROUNDED_DEVICE_SHARING = original_flag

    row_neighbors, col_neighbors = build_bipartite_graph(raw_dir=raw_dir)
    n_users, n_attrs = len(row_neighbors), len(col_neighbors)
    n_edges = sum(len(v) for v in row_neighbors.values())

    blocks = detect_top_k_blocks(row_neighbors, col_neighbors, k=N_BLOCKS)

    import json
    with open(gt_dir / "rings.json") as f:
        rings = json.load(f)
    hard_rings = [{"ring_id": rid, "members": r["members"]} for rid, r in rings.items() if r["type"] == "hard"]

    def is_real_match(overlap_row):
        return overlap_row is not None and overlap_row["recall"] >= MATCH_THRESH and overlap_row["precision"] >= MATCH_THRESH

    matched_ids = set()
    for b in blocks:
        overlap = raw_overlap(b["users"], hard_rings, "ring_id")
        if is_real_match(overlap):
            matched_ids.add(overlap["id"])

    result = {
        "seed": seed, "grounding": grounding,
        "n_users": n_users, "n_attributes": n_attrs, "n_edges": n_edges,
        "n_blocks_found": len(blocks), "n_hard_rings_matched": len(matched_ids),
        "n_hard_rings_total": len(hard_rings),
        "recall": round(len(matched_ids) / len(hard_rings), 4) if hard_rings else None,
    }
    if verbose:
        print(f"  users={n_users:,} attrs={n_attrs:,} edges={n_edges:,} | blocks found={len(blocks)} | "
              f"hard-ring recall={len(matched_ids)}/{len(hard_rings)} ({result['recall']:.1%})")
    return result


def run(verbose=True):
    tmp_root = Path(tempfile.mkdtemp(prefix="fraudar_isolation_"))
    results = []
    try:
        for v in VARIANTS:
            if verbose:
                print(f"\n=== {v['label']} ===")
            r = run_variant(v["seed"], v["grounding"], tmp_root, verbose=verbose)
            r["label"] = v["label"]
            results.append(r)
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)

    a, b, c = results
    seed_effect = b["n_hard_rings_matched"] - a["n_hard_rings_matched"]
    grounding_effect = c["n_hard_rings_matched"] - b["n_hard_rings_matched"]
    total_drop = c["n_hard_rings_matched"] - a["n_hard_rings_matched"]

    if abs(grounding_effect) > abs(seed_effect):
        dominant_cause = "grounding recalibration"
    elif abs(seed_effect) > abs(grounding_effect):
        dominant_cause = "ordinary seed-to-seed variance"
    else:
        dominant_cause = "neither -- split exactly evenly between the two causes"

    finding = {
        "variants": results,
        "seed_effect_rings": seed_effect,
        "grounding_effect_rings": grounding_effect,
        "total_change_rings": total_drop,
        "dominant_cause": dominant_cause,
    }

    if verbose:
        print(f"\n=== Decomposition ===")
        print(f"A (old seed, grounding off):  {a['n_hard_rings_matched']}/{a['n_hard_rings_total']} matched, {a['n_blocks_found']} blocks")
        print(f"B (new seed, grounding off):  {b['n_hard_rings_matched']}/{b['n_hard_rings_total']} matched, {b['n_blocks_found']} blocks")
        print(f"C (new seed, grounding on):   {c['n_hard_rings_matched']}/{c['n_hard_rings_total']} matched, {c['n_blocks_found']} blocks")
        print(f"\nSeed-only effect (A->B):       {seed_effect:+d} rings matched")
        print(f"Grounding-only effect (B->C):  {grounding_effect:+d} rings matched")
        print(f"Total observed change (A->C):  {total_drop:+d} rings matched")
        print(f"\nDominant cause: {dominant_cause}")

    from .pipeline.data_io import PROCESSED_DIR
    import json as json_module
    with open(PROCESSED_DIR / "fraudar_seed_isolation.json", "w") as f:
        json_module.dump(finding, f, indent=2)
    if verbose:
        print(f"\nWritten -> {PROCESSED_DIR / 'fraudar_seed_isolation.json'}")
    return finding


if __name__ == "__main__":
    run()
