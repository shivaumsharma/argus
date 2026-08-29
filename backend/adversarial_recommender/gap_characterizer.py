"""
Stage 2 -- Gap Characterizer.

For an attack that evaded detection, identifies exactly which threshold let
it through -- reusing Stage 4's feature scoring (compute_features) and Stage
5's filter (evaluate_cluster) completely unchanged. No new introspection
tooling: the pipeline already computes organic_score/suspicion_score and
every sub-check that fed them, so this just reads that output and asks
"which single threshold, moved the smallest amount, would flip the verdict."

Honest by construction: if the evading attack passes 3 of 3 organic checks
(not just the minimum 2 needed to clear), no single-parameter change closes
the gap -- tightening any one check still leaves organic_score at 2, still
enough to clear. That case is reported as exactly that, not forced into a
recommendation that wouldn't actually work. This mirrors
docs/ARCHITECTURE.md's own documented limitation: "an adversary patient
enough to fake the confounder signals is, by construction, indistinguishable
from the confounders those signals exist to protect."
"""

import shutil
import tempfile
from pathlib import Path

import pandas as pd

from ..pipeline.clustering import dedupe_candidates, stage2_hard_clusters, stage3_soft_clusters
from ..pipeline.confounder_filter import (
    DIVERSE_ORDER_CV,
    ENGAGED_SESSIONS,
    SOFT_CLEAR_ORGANIC_THRESHOLD,
    SPREAD_OUT_DAYS,
    evaluate_cluster,
)
from ..pipeline.data_io import RAW_DIR, load_data
from ..pipeline.features import build_lookups, compute_features
from ..pipeline.graph_build import build_graph, hard_signal_subgraph

# feature_key -> (threshold constant, "above"/"below" the threshold counts as organic)
_ORGANIC_CHECKS = {
    "spread_out_days": ("signup_span_days", SPREAD_OUT_DAYS, "above"),
    "diverse_order_cv": ("order_value_cv", DIVERSE_ORDER_CV, "above"),
    "engaged_sessions": ("post_signup_engagement", ENGAGED_SESSIONS, "above"),
}


def _inject_into_disposable(attack: dict) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="sentinel_recommender_"))
    for name, key in [
        ("accounts.csv", "accounts"), ("sessions.csv", "sessions"), ("referrals.csv", "referrals"),
        ("payment_instruments.csv", "instruments"), ("orders.csv", "orders"),
    ]:
        existing = pd.read_csv(RAW_DIR / name, dtype=str)
        combined = pd.concat([existing, pd.DataFrame(attack[key]).astype(str)], ignore_index=True)
        combined.to_csv(tmp / name, index=False)
    return tmp


def characterize(attack: dict, verbose=True) -> dict:
    """Injects the attack into a disposable copy of the REAL frozen data/raw/
    (read-only source; writes only to a tempdir cleaned up before returning),
    runs the unmodified pipeline, and characterizes the result. Returns a dict
    with 'evaded' (bool) and, if evaded, 'gap' (the single-parameter fix, or
    None if no single-parameter fix exists) plus the full feature/verdict detail."""
    tmp = _inject_into_disposable(attack)
    try:
        data = load_data(raw_dir=tmp)
        G = build_graph(data)
        H = hard_signal_subgraph(G)
        member_set = set(attack["members"])

        hard_clusters = stage2_hard_clusters(H)
        soft_clusters = stage3_soft_clusters(G)
        candidates = dedupe_candidates(hard_clusters, soft_clusters)
        device_by_user, instrument_by_user = build_lookups(data)

        best = None
        for members, stage in candidates:
            overlap = member_set & members
            if len(overlap) >= len(member_set) // 2:
                feats = compute_features(G, members, data, device_by_user, instrument_by_user)
                verdict = evaluate_cluster(feats)
                if best is None or len(overlap) > len(member_set & best[0]):
                    best = (members, stage, feats, verdict)

        if best is None:
            return {"evaded": True, "reason": "not_clustered", "gap": None,
                    "detail": "Stage 2/3 never grouped this attack into a candidate cluster at all -- "
                             "structurally invisible, not a threshold gap."}

        members, stage, feats, verdict = best
        if verdict["flagged"]:
            return {"evaded": False, "reason": "caught", "gap": None, "features": feats, "verdict": verdict}

        # evaded -- characterize which organic check has the smallest margin
        margins = {}
        for param, (feat_key, threshold, direction) in _ORGANIC_CHECKS.items():
            value = feats.get(feat_key)
            if value is None:
                continue
            margin = (value - threshold) if direction == "above" else (threshold - value)
            if margin >= 0:  # this check is one of the ones that passed (contributed to organic_score)
                margins[param] = {"feature": feat_key, "value": value, "threshold": threshold, "margin": margin}

        organic_score = verdict["organic_score"]
        gap = None
        if margins and organic_score - 1 < SOFT_CLEAR_ORGANIC_THRESHOLD:
            # tightening the loosest-margin passing check would drop organic_score below the
            # clear threshold -- a real, single-parameter fix exists
            tightest_param = min(margins, key=lambda p: margins[p]["margin"])
            gap = {"gap_parameter": tightest_param, **margins[tightest_param]}

        result = {
            "evaded": True, "reason": "clustered_not_flagged", "gap": gap,
            "organic_score": organic_score, "passing_checks": margins,
            "features": feats, "verdict": verdict, "cluster_size": len(members), "detection_stage": stage,
        }
        if verbose:
            if gap:
                print(f"  Gap found: {gap['gap_parameter']} (value={gap['value']:.3f}, threshold={gap['threshold']}, "
                      f"margin={gap['margin']:.3f}) -- the loosest of {len(margins)} passing organic checks.")
            else:
                print(f"  No single-parameter gap: organic_score={organic_score}/3 "
                      f"({len(margins)} checks passing) -- tightening any one check still clears the "
                      f"organic threshold ({SOFT_CLEAR_ORGANIC_THRESHOLD}). This evasion needs >=2 "
                      f"simultaneous changes to close, which is out of scope for a single bounded "
                      f"recommendation (see recommendation_drafter.py).")
        return result
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
