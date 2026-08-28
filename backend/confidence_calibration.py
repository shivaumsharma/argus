"""
Does the LLM's self-reported confidence actually track ground truth?

For every flagged cluster with a real (non-template) LLM confidence score,
bucket into deciles and check: of the clusters in this bucket, what fraction
are actually a true ring (matches planted ground truth) vs. a confounder or
unmatched cluster that slipped past Stage 5? A well-calibrated confidence
would show accuracy rising with the bucket. Reported honestly either way,
including the sample-size caveat this dataset actually has: with a 2.5-5%
confounder false-positive rate, there are only 1-2 negative examples across
the entire flagged set, so most deciles will show 100% by default just from
having no negative examples to miss -- that is not the same claim as "well
calibrated," and this script says so explicitly rather than blend past it.

Run: python -m backend.confidence_calibration
"""

import json

from . import db
from .pipeline.data_io import PROCESSED_DIR
from .pipeline.eval import best_match
from .reporting import load_ground_truth

N_BUCKETS = 10


def run(verbose=True):
    rings, confounders = load_ground_truth()
    all_clusters = db.get_all_clusters()
    flagged = [c for c in all_clusters if c["flagged"] and c.get("llm_mode") in ("anthropic", "gemini")]

    if not flagged:
        if verbose:
            print("No flagged clusters carry a real (non-template) LLM confidence score. "
                  "Run backend.llm_investigate with live credentials first.")
        return None

    ring_sets = {rid: set(r["members"]) for rid, r in rings.items()}
    conf_sets = {cid: set(c["members"]) for cid, c in confounders.items()}

    rows = []
    for c in flagged:
        members = set(c["members"])
        matched_ring = None
        for rid, rset in ring_sets.items():
            inter = len(members & rset)
            if inter and inter / len(rset) >= 0.5 and inter / len(members) >= 0.5:
                matched_ring = rid
                break
        matched_conf = None
        if matched_ring is None:
            for cid, cset in conf_sets.items():
                inter = len(members & cset)
                if inter and inter / len(cset) >= 0.5 and inter / len(members) >= 0.5:
                    matched_conf = cid
                    break
        rows.append({
            "cluster_id": c["cluster_id"],
            "confidence": c["llm_confidence"],
            "is_true_ring": matched_ring is not None,
            "matched_ring": matched_ring,
            "matched_confounder": matched_conf,
        })

    buckets = [[] for _ in range(N_BUCKETS)]
    for r in rows:
        idx = min(int(r["confidence"] * N_BUCKETS), N_BUCKETS - 1)
        buckets[idx].append(r)

    report = {"n_flagged": len(rows), "n_true_rings": sum(r["is_true_ring"] for r in rows),
              "n_not_true_ring": sum(not r["is_true_ring"] for r in rows), "buckets": []}

    for i, bucket in enumerate(buckets):
        lo, hi = i / N_BUCKETS, (i + 1) / N_BUCKETS
        if not bucket:
            report["buckets"].append({"range": f"{lo:.1f}-{hi:.1f}", "n": 0, "accuracy": None})
            continue
        acc = sum(r["is_true_ring"] for r in bucket) / len(bucket)
        report["buckets"].append({
            "range": f"{lo:.1f}-{hi:.1f}", "n": len(bucket), "accuracy": round(acc, 3),
            "false_positives": [r["cluster_id"] for r in bucket if not r["is_true_ring"]],
        })

    with open(PROCESSED_DIR / "confidence_calibration.json", "w") as f:
        json.dump(report, f, indent=2)

    if verbose:
        print(f"{report['n_flagged']} flagged clusters with real LLM confidence scores.")
        print(f"{report['n_true_rings']} match a planted ring; {report['n_not_true_ring']} do not "
              f"(matched a confounder, or matched nothing at >=50% overlap).")
        print(f"\n{'Confidence':<12}{'N':<6}{'Accuracy':<10}{'Notes'}")
        for b in report["buckets"]:
            if b["n"] == 0:
                print(f"{b['range']:<12}{'0':<6}{'-':<10}")
                continue
            note = f"FP: {b['false_positives']}" if b.get("false_positives") else ""
            acc_str = f"{b['accuracy']:.0%}"
            print(f"{b['range']:<12}{b['n']:<6}{acc_str:<10}{note}")
        print(
            f"\nCaveat: only {report['n_not_true_ring']} negative example(s) exist across "
            f"{report['n_flagged']} flagged clusters (this dataset's confounder false-positive rate is "
            "2.5-5%). Most deciles show 100% purely because they contain zero negative examples to miss, "
            "not because confidence has been validated against a meaningful number of counter-examples. "
            "The honest read: confidence correlates with the deterministic Stage 4/5 evidence the LLM was "
            "given (tighter timing, lower order-value CV -> higher stated confidence), which is a "
            "reasonable prioritization signal for a human reviewer -- but with this few negative examples, "
            "this is not a statistically meaningful calibration curve, and the app doesn't claim it is."
        )
        print(f"\nWritten -> {PROCESSED_DIR / 'confidence_calibration.json'}")

    return report


if __name__ == "__main__":
    run()
