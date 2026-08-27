"""
Day 4 -- evaluation harness.

Reports, at the cluster level, against ground truth that the detector never sees:
  - ring detection precision/recall, split hard-signal (Stage 2) vs soft-signal-only (Stage 3)
  - confounder false-positive rate (the honesty check the BRD's bar demands)
  - a held-out split: matching thresholds were tuned only by eyeballing the dev
    split; the headline numbers below are computed on the held-out split.
"""

import json
import random

from .data_io import GT_DIR, PROCESSED_DIR

MATCH_THRESH = 0.5  # a candidate cluster "recovers" a ground-truth cluster if overlap >= this in both directions
HOLDOUT_SEED = 7
HOLDOUT_FRACTION = 0.3


def load_ground_truth():
    with open(GT_DIR / "rings.json") as f:
        rings = json.load(f)
    with open(GT_DIR / "confounders.json") as f:
        confounders = json.load(f)
    return rings, confounders


def split_holdout(ids: list, fraction=HOLDOUT_FRACTION, seed=HOLDOUT_SEED):
    ids = sorted(ids)
    rng = random.Random(seed)
    shuffled = ids[:]
    rng.shuffle(shuffled)
    n_holdout = max(1, int(len(shuffled) * fraction))
    holdout = set(shuffled[:n_holdout])
    dev = set(shuffled[n_holdout:])
    return dev, holdout


def best_match(members: set, flagged_clusters: list):
    """Return the flagged cluster with the highest bidirectional overlap against `members`, or None."""
    best, best_score = None, 0.0
    for c in flagged_clusters:
        cset = set(c["members"])
        inter = len(members & cset)
        if inter == 0:
            continue
        recall = inter / len(members)     # fraction of the true cluster recovered
        precision = inter / len(cset)     # fraction of the flagged cluster that is true cluster
        score = min(recall, precision)
        if recall >= MATCH_THRESH and precision >= MATCH_THRESH and score > best_score:
            best, best_score = c, score
    return best


def evaluate(clusters_path=None, verbose=True):
    rings, confounders = load_ground_truth()
    with open(clusters_path or (PROCESSED_DIR / "clusters.json")) as f:
        all_clusters = json.load(f)
    flagged = [c for c in all_clusters if c["flagged"]]

    ring_dev, ring_holdout = split_holdout(list(rings.keys()))
    conf_dev, conf_holdout = split_holdout(list(confounders.keys()))

    def score_rings(ring_ids, label):
        rows = []
        for rid in ring_ids:
            ring = rings[rid]
            members = set(ring["members"])
            match = best_match(members, flagged)
            rows.append({
                "ring_id": rid, "type": ring["type"], "size": len(members),
                "detected": match is not None,
                "matched_cluster": match["cluster_id"] if match else None,
                "matched_stage": match["detection_stage"] if match else None,
            })
        tp = sum(1 for r in rows if r["detected"])
        recall = tp / len(rows) if rows else float("nan")
        return rows, recall

    def score_confounders(conf_ids, label):
        rows = []
        for cid in conf_ids:
            conf = confounders[cid]
            members = set(conf["members"])
            match = best_match(members, flagged)
            rows.append({
                "confounder_id": cid, "type": conf["type"], "size": len(members),
                "wrongly_flagged": match is not None,
                "matched_cluster": match["cluster_id"] if match else None,
            })
        fp = sum(1 for r in rows if r["wrongly_flagged"])
        fp_rate = fp / len(rows) if rows else float("nan")
        return rows, fp_rate

    def cluster_precision(ring_ids, conf_ids):
        """Of the flagged clusters that overlap this split's ground truth universe at all,
        what fraction are true rings vs. false alarms (confounder or unmatched noise)?"""
        universe = set(ring_ids) | set(conf_ids)
        member_pool = set()
        for rid in ring_ids:
            member_pool |= set(rings[rid]["members"])
        for cid in conf_ids:
            member_pool |= set(confounders[cid]["members"])

        relevant_flagged = [c for c in flagged if set(c["members"]) & member_pool]
        tp, fp = 0, 0
        for c in relevant_flagged:
            cset = set(c["members"])
            is_true_ring = False
            for rid in ring_ids:
                rset = set(rings[rid]["members"])
                inter = len(cset & rset)
                if inter and inter / len(rset) >= MATCH_THRESH and inter / len(cset) >= MATCH_THRESH:
                    is_true_ring = True
                    break
            if is_true_ring:
                tp += 1
            else:
                fp += 1
        precision = tp / (tp + fp) if (tp + fp) else float("nan")
        return precision, tp, fp, len(relevant_flagged)

    report = {"dev": {}, "holdout": {}, "overall": {}}

    for label, (r_ids, c_ids) in [
        ("dev", (ring_dev, conf_dev)),
        ("holdout", (ring_holdout, conf_holdout)),
        ("overall", (list(rings.keys()), list(confounders.keys()))),
    ]:
        hard_rows, hard_recall = score_rings([r for r in r_ids if rings[r]["type"] == "hard"], label)
        soft_rows, soft_recall = score_rings([r for r in r_ids if rings[r]["type"] == "soft"], label)
        conf_rows, conf_fp_rate = score_confounders(c_ids, label)
        precision, tp, fp, n_relevant = cluster_precision(r_ids, c_ids)

        report[label] = {
            "n_rings_hard": len(hard_rows), "hard_signal_recall": hard_recall,
            "n_rings_soft": len(soft_rows), "soft_signal_recall": soft_recall,
            "n_confounders": len(conf_rows), "confounder_false_positive_rate": conf_fp_rate,
            "cluster_precision": precision, "cluster_tp": tp, "cluster_fp": fp, "n_flagged_relevant": n_relevant,
            "ring_detail": hard_rows + soft_rows,
            "confounder_detail": conf_rows,
        }

    with open(PROCESSED_DIR / "eval_report.json", "w") as f:
        json.dump(report, f, indent=2)

    if verbose:
        for label in ["dev", "holdout", "overall"]:
            r = report[label]
            print(f"\n=== {label.upper()} ===")
            print(f"  Hard-signal ring recall:   {r['hard_signal_recall']:.2%}  ({r['n_rings_hard']} rings)")
            print(f"  Soft-signal ring recall:   {r['soft_signal_recall']:.2%}  ({r['n_rings_soft']} rings)")
            print(f"  Confounder false-pos rate: {r['confounder_false_positive_rate']:.2%}  ({r['n_confounders']} confounders)")
            print(f"  Cluster-level precision:   {r['cluster_precision']:.2%}  (tp={r['cluster_tp']}, fp={r['cluster_fp']})")
        print(f"\nWritten -> {PROCESSED_DIR / 'eval_report.json'}")

    return report


if __name__ == "__main__":
    evaluate()
