"""Cross-cutting queries joining ground truth with pipeline output -- used by the dashboard and API."""

import json
from pathlib import Path

from . import db
from .pipeline.data_io import GT_DIR, PROCESSED_DIR
from .pipeline.eval import best_match

ROOT = Path(__file__).resolve().parents[1]
COD_GT_DIR = ROOT / "data" / "cod" / "ground_truth"
COD_PROCESSED_DIR = ROOT / "data" / "cod" / "processed"


def load_ground_truth():
    with open(GT_DIR / "rings.json") as f:
        rings = json.load(f)
    with open(GT_DIR / "confounders.json") as f:
        confounders = json.load(f)
    return rings, confounders


def load_cod_ground_truth():
    """COD's ring/confounder ground truth is smaller and flatter than the primary
    dataset's -- no "type"/"difficulty" tiering, since this loss type is a proof-of-reuse,
    not tuned to the same easy/hard resolution (see docs/SECOND_LOSS_TYPE.md)."""
    with open(COD_GT_DIR / "rings.json") as f:
        rings = json.load(f)
    with open(COD_GT_DIR / "confounders.json") as f:
        confounders = json.load(f)
    return rings, confounders


def load_cod_clusters():
    path = COD_PROCESSED_DIR / "clusters.json"
    if not path.exists():
        return []
    with open(path) as f:
        return json.load(f)


def load_eval_report():
    path = PROCESSED_DIR / "eval_report.json"
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def _confounder_callout_rows(confounders: dict, all_clusters: list) -> list:
    """For every planted legitimate cluster: was it wrongly flagged, and if it was ever
    considered a candidate at all, why did (or didn't) it survive the Stage 5 filter?"""
    flagged = [c for c in all_clusters if c["flagged"]]

    rows = []
    for cid, conf in confounders.items():
        members = set(conf["members"])
        flagged_match = best_match(members, flagged)
        any_match = best_match(members, all_clusters)
        rows.append({
            "confounder_id": cid,
            "type": conf.get("type", "shared_address"),
            "difficulty": conf.get("difficulty", "n/a"),
            "size": len(members),
            "description": conf["description"],
            "wrongly_flagged": flagged_match is not None,
            "matched_cluster_id": (flagged_match or any_match)["cluster_id"] if (flagged_match or any_match) else None,
            "filter_reason": (flagged_match or any_match)["filter_reason"] if (flagged_match or any_match) else None,
            "features": (flagged_match or any_match)["features"] if (flagged_match or any_match) else None,
            "surfaced_as_candidate": any_match is not None,
        })
    return rows


def confounder_callout_rows():
    _, confounders = load_ground_truth()
    return _confounder_callout_rows(confounders, db.get_all_clusters())


def cod_confounder_callout_rows():
    _, confounders = load_cod_ground_truth()
    return _confounder_callout_rows(confounders, load_cod_clusters())


def _ring_recall_rows(rings: dict, all_clusters: list) -> list:
    flagged = [c for c in all_clusters if c["flagged"]]

    rows = []
    for rid, ring in rings.items():
        members = set(ring["members"])
        match = best_match(members, flagged)
        rows.append({
            "ring_id": rid,
            "type": ring.get("type", "cod_ring"),
            "difficulty": ring.get("difficulty", "n/a"),
            "size": len(members),
            "description": ring["description"],
            "detected": match is not None,
            "matched_cluster_id": match["cluster_id"] if match else None,
        })
    return rows


def ring_recall_rows():
    rings, _ = load_ground_truth()
    return _ring_recall_rows(rings, db.get_all_clusters())


def cod_ring_recall_rows():
    rings, _ = load_cod_ground_truth()
    return _ring_recall_rows(rings, load_cod_clusters())
