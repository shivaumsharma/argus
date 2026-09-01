"""
Supernode / graph explosion stress test.

Full spec: inject a synthetic shared attribute connecting a swept range of
otherwise-unrelated, genuinely organic accounts (N = 50/200/1000/5000) into a
disposable copy of the real frozen dataset, run the unmodified Stage 1-5
pipeline, and report raw counts on two separate questions: (1) does Stage 1's
edge construction / Stage 2's hard-signal clustering merge them into one
giant candidate cluster at all, and how expensive is that; (2) does Stage 5's
confounder filter correctly clear it as organic, or wrongly flag thousands of
real legitimate accounts as one giant "fraud ring"? If either breaks, a
degree-cap mitigation (`graph_build.build_graph`'s new
`max_shared_attribute_group_size` parameter -- skip building edges for any
shared-attribute group above the cap, the same judgment already applied to
Amazon's excluded net_usu relation in external_validation/run.py) is tested
and reported before/after.

The N accounts are real, existing, genuinely organic BACKGROUND accounts
from the frozen dataset (drawn from data/ground_truth/labels.csv's
"background" class) -- not new synthetic ones -- with only their
device_fingerprint_id (accounts.csv and every one of their own sessions.csv
rows, for internal consistency) overwritten to one shared value in a
disposable copy. Everything else about them (real signup dates spread
across the whole observation window, real order/session history) stays
exactly as generated. This is deliberately the worst case for a false
positive: if Stage 5 ever wrongly flags this group, it is flagging accounts
that are, in every other respect, indistinguishable from any ordinary
customer -- never touches data/raw/ itself, same disposable-tempdir pattern
as adversarial_stress_test.py.

Run: python -m backend.supernode_stress_test
"""

import json
import random
import shutil
import tempfile
import time
from pathlib import Path

import pandas as pd

from .pipeline.clustering import dedupe_candidates, stage2_hard_clusters, stage3_soft_clusters
from .pipeline.confounder_filter import evaluate_cluster
from .pipeline.data_io import GT_DIR, PROCESSED_DIR, RAW_DIR, load_data
from .pipeline.features import build_lookups, compute_features
from .pipeline.graph_build import build_graph, hard_signal_subgraph

SWEEP_SIZES = (50, 200, 1000, 5000)
SUPERNODE_DEVICE_ID = "dfp_SUPERNODE_STRESS_TEST_INJECTED"
DEGREE_CAP_DEFAULT = 100  # a real household/hostel confounder tops out at ~25 members in this
                          # dataset's own generator (gen_hostel draws 12-25); 100 is a generous
                          # margin above the largest legitimate shared-device group this project's
                          # own ground truth ever plants, chosen the same dataset-blind way
                          # FRAUDAR's min_block_users=2 was (a structural floor/ceiling, not
                          # reverse-engineered from this specific test's own N values).


def _pick_background_uids(n, seed=7):
    labels = pd.read_csv(GT_DIR / "labels.csv", dtype=str)
    background = labels[labels["cluster_type"] == "background"]["user_id"].tolist()
    rng = random.Random(seed)
    if n > len(background):
        raise ValueError(f"Requested {n} background accounts, only {len(background)} exist in the frozen dataset.")
    return rng.sample(background, n)


def inject(src_dir: Path, dst_dir: Path, n: int, seed=7):
    dst_dir.mkdir(parents=True, exist_ok=True)
    target_uids = set(_pick_background_uids(n, seed=seed))

    accounts = pd.read_csv(src_dir / "accounts.csv", dtype=str)
    accounts.loc[accounts["user_id"].isin(target_uids), "device_fingerprint_id"] = SUPERNODE_DEVICE_ID
    accounts.to_csv(dst_dir / "accounts.csv", index=False)

    for name in ("referrals.csv", "payment_instruments.csv", "orders.csv"):
        shutil.copy(src_dir / name, dst_dir / name)

    # sessions.csv also records device_fingerprint_id per session row -- kept internally
    # consistent so every injected account's own session history shows the same device its
    # accounts.csv row does, not a stale one contradicting it.
    sessions = pd.read_csv(src_dir / "sessions.csv", dtype=str)
    sessions.loc[sessions["user_id"].isin(target_uids), "device_fingerprint_id"] = SUPERNODE_DEVICE_ID
    sessions.to_csv(dst_dir / "sessions.csv", index=False)

    return sorted(target_uids)


def run_one(n, degree_cap=None, verbose=True):
    tmp = Path(tempfile.mkdtemp(prefix=f"sentinel_supernode_{n}_"))
    try:
        target_uids = inject(RAW_DIR, tmp, n)
        data = load_data(raw_dir=tmp, verbose=False)

        t0 = time.time()
        G = build_graph(data, max_shared_attribute_group_size=degree_cap)
        t_graph = time.time() - t0
        H = hard_signal_subgraph(G)

        target_set = set(target_uids)
        sub = G.subgraph(target_uids)
        n_edges_among_targets = sub.number_of_edges()

        t0 = time.time()
        hard_clusters = stage2_hard_clusters(H)
        soft_clusters = stage3_soft_clusters(G)
        t_cluster = time.time() - t0
        candidates = dedupe_candidates(hard_clusters, soft_clusters)
        device_by_user, instrument_by_user = build_lookups(data)

        merged_cluster = None
        for members, stage in candidates:
            overlap = target_set & members
            if len(overlap) >= max(2, n // 2):  # substantially the same injected group
                merged_cluster = (stage, members, overlap)
                break

        result = {
            "n": n, "degree_cap": degree_cap,
            "graph_build_seconds": round(t_graph, 4),
            "clustering_seconds": round(t_cluster, 4),
            "n_edges_among_injected_accounts": n_edges_among_targets,
            "uncapped_clique_edges_would_be": n * (n - 1) // 2,
            "merged_into_one_cluster": merged_cluster is not None,
        }

        if merged_cluster:
            stage, members, overlap = merged_cluster
            feats = compute_features(G, members, data, device_by_user, instrument_by_user)
            verdict = evaluate_cluster(feats)
            result.update({
                "cluster_stage": stage, "cluster_size": len(members),
                "injected_accounts_captured": len(overlap),
                "flagged": verdict["flagged"], "organic_score": verdict["organic_score"],
                "suspicion_score": verdict["suspicion_score"], "reason": verdict["reason"],
                "features": {k: feats[k] for k in ("signup_span_days", "order_value_cv",
                                                     "post_signup_engagement", "claim_then_dormant_frac",
                                                     "bonus_claim_velocity_hours")},
            })
        if verbose:
            cap_note = f" (degree_cap={degree_cap})" if degree_cap else ""
            print(f"\n=== N={n}{cap_note} ===")
            print(f"  Graph build: {t_graph:.4f}s | Clustering: {t_cluster:.4f}s")
            print(f"  Edges among injected accounts: {n_edges_among_targets:,} "
                  f"(uncapped clique would be {result['uncapped_clique_edges_would_be']:,})")
            if merged_cluster:
                print(f"  Merged into one {result['cluster_stage']}-signal cluster of {result['cluster_size']:,} "
                      f"members ({result['injected_accounts_captured']}/{n} injected accounts captured)")
                print(f"  Stage 5 verdict: flagged={result['flagged']} (organic={result['organic_score']}/3, "
                      f"suspicion={result['suspicion_score']}/4)")
                print(f"  Reason: {result['reason']}")
                if result["flagged"]:
                    print(f"  *** FALSE POSITIVE: {result['injected_accounts_captured']} genuinely organic "
                          f"accounts wrongly flagged as one fraud ring ***")
            else:
                print(f"  Did not merge into one dominant candidate cluster.")
        return result
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run(verbose=True):
    if verbose:
        print("=== Supernode stress test: uncapped (current production behavior) ===")
    results = [run_one(n, verbose=verbose) for n in SWEEP_SIZES]

    any_false_positive = any(r.get("flagged") for r in results)
    # Absolute wall-clock time, not just a power-law-fit heuristic: any single supernode adding
    # more than 10 real seconds to what is otherwise a ~2-second pipeline run (see the primary
    # pipeline's own measured runtime) is a genuine problem regardless of exactly what exponent
    # its scaling curve fits -- checking both graph construction and clustering, since clustering
    # (Louvain) turned out to be the far larger cost once real numbers were measured, not
    # graph-build as originally guessed.
    max_stage_seconds = max(r["graph_build_seconds"] + r["clustering_seconds"] for r in results)
    quadratic_blowup_confirmed = max_stage_seconds > 10.0

    mitigation_results = []
    if any_false_positive or quadratic_blowup_confirmed:
        if verbose:
            reason = []
            if any_false_positive:
                reason.append("a real false positive")
            if quadratic_blowup_confirmed:
                reason.append(f"a single supernode adding {max_stage_seconds:.1f}s to what is otherwise "
                               f"a ~2s pipeline run")
            print(f"\n\n=== Problem confirmed ({' and '.join(reason)}) -- testing degree-cap mitigation "
                  f"(cap={DEGREE_CAP_DEFAULT}) ===")
        mitigation_results = [run_one(n, degree_cap=DEGREE_CAP_DEFAULT, verbose=verbose) for n in SWEEP_SIZES]
    elif verbose:
        print(f"\n\nNo problem confirmed (no false positive, max added stage time "
              f"{max_stage_seconds:.1f}s) -- mitigation not tested, nothing to mitigate.")

    report = {
        "sweep_sizes": list(SWEEP_SIZES), "uncapped_sweep": results,
        "any_false_positive": any_false_positive, "quadratic_blowup_confirmed": quadratic_blowup_confirmed,
        "degree_cap_tested": DEGREE_CAP_DEFAULT if mitigation_results else None,
        "mitigation_sweep": mitigation_results,
    }
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    with open(PROCESSED_DIR / "supernode_stress_test.json", "w") as f:
        json.dump(report, f, indent=2, default=str)
    if verbose:
        print(f"\nWritten -> {PROCESSED_DIR / 'supernode_stress_test.json'}")
    return report


if __name__ == "__main__":
    run()
