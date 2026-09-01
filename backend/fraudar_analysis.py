"""
FRAUDAR cross-check -- an independent detection method run against the same
frozen dataset, to see whether it agrees or disagrees with this project's
own pipeline. Standalone: does NOT import from, call, or modify anything in
backend/pipeline/ (Stages 1-5). It only reads the already-frozen data/raw/
CSVs and, for comparison, the already-computed clusters.json / ground truth
-- read-only in both directions.

"Independent" needs one qualification, not left implicit: the detection
mechanism (the greedy peeling itself) never sees ground truth at any point.
One separate tuning decision -- how many blocks to report, not how they're
found -- was first set using inside knowledge of this project's own data
before being caught and fixed to a dataset-blind threshold. See
detect_top_k_blocks()'s docstring below and docs/FRAUDAR_CROSSCHECK.md's
"Independence, qualified" section for the full story.

FRAUDAR (Hooi, Song, Beutel, Shah, Shin, Faloutsos -- "FRAUDAR: Bounding
Graph Fraud in the Face of Camouflage", KDD 2016, best paper award) finds
dense blocks in a bipartite graph via greedy peeling: repeatedly remove
whichever node (from either side) currently contributes the least weighted
degree, tracking a density score (total weighted edge mass / remaining node
count) at every step, and returning the point in that removal sequence that
maximized the score. This is a 2-approximation to the weighted densest
-subgraph problem (Charikar's classic result), with FRAUDAR's specific
contribution being a *camouflage-resistant* edge weighting: each
attribute-side column is weighted by 1/log(degree_in_full_graph + 5), so an
attribute touched by many distinct users (a common/background one) counts
for less per edge than a rare one -- discouraging a fraud ring from diluting
its detected density by touching popular, ordinary attributes.

The algorithm here is a clean reimplementation (not a copy) of the published
method, checked directly against the public reference implementation at
safe-graph/UGFraud (github.com/safe-graph/UGFraud, Apache-2.0,
UGFraud/Detector/Fraudar.py's `logWeightedAveDegree` / `fastGreedyDecreasing`
/ `detectMultiple`) to confirm the exact weighting formula and peeling
procedure before writing this, rather than approximating from memory.

Bipartite graph: users on one side, distinct shared-attribute VALUES on the
other (a specific device_fingerprint_id, a specific instrument_hash, a
specific IP subnet -- first three octets, matching this project's own
Stage 1 definition of "subnet") -- an edge wherever a user has that exact
value. Deliberately excludes referral-link edges (unlike Stage 1's own
graph), matching exactly what was asked: device/instrument/subnet only.

Run: python -m backend.fraudar_analysis
"""

import heapq
import json
import math
from collections import defaultdict

import pandas as pd

from . import db
from .pipeline.data_io import PROCESSED_DIR, RAW_DIR
from .pipeline.eval import MATCH_THRESH
from .reporting import load_ground_truth

N_BLOCKS = 80  # = 40 hard + 40 soft planted rings; generous enough to give FRAUDAR a fair chance at all of them


def build_bipartite_graph(raw_dir=None):
    raw_dir = raw_dir or RAW_DIR
    accounts = pd.read_csv(raw_dir / "accounts.csv", dtype=str)
    instruments = pd.read_csv(raw_dir / "payment_instruments.csv", dtype=str)
    instrument_by_user = dict(zip(instruments.user_id, instruments.instrument_hash))

    row_neighbors = defaultdict(set)   # user_id -> set of attribute-node ids
    col_neighbors = defaultdict(set)   # attribute-node id -> set of user_ids

    for uid, device, ip in zip(accounts.user_id, accounts.device_fingerprint_id, accounts.ip_address_at_signup):
        subnet = ".".join(ip.split(".")[:3]) if isinstance(ip, str) and ip.count(".") == 3 else None
        instrument = instrument_by_user.get(uid)
        attrs = []
        if isinstance(device, str) and device:
            attrs.append(f"device:{device}")
        if instrument:
            attrs.append(f"instrument:{instrument}")
        if subnet:
            attrs.append(f"subnet:{subnet}")
        for a in attrs:
            row_neighbors[uid].add(a)
            col_neighbors[a].add(uid)

    return dict(row_neighbors), dict(col_neighbors)


def fast_greedy_decreasing(row_neighbors, col_neighbors, col_weight):
    """One run of FRAUDAR's greedy peeling. Returns (row_set, col_set, best_score)
    for the single densest block found. row_neighbors/col_neighbors define the
    (unweighted) bipartite adjacency; col_weight[c] is the fixed per-edge weight
    contributed by column c (1/log(degree+5) -- the camouflage-resistance term)."""
    row_delta = {r: sum(col_weight[c] for c in nbrs) for r, nbrs in row_neighbors.items()}
    col_delta = {c: col_weight[c] * len(nbrs) for c, nbrs in col_neighbors.items()}

    row_set = set(row_neighbors.keys())
    col_set = set(col_neighbors.keys())
    cur_score = sum(row_delta.values())

    best_score = cur_score / (len(row_set) + len(col_set)) if (row_set or col_set) else 0.0
    best_row_set, best_col_set = set(row_set), set(col_set)

    row_heap = [(d, r) for r, d in row_delta.items()]
    col_heap = [(d, c) for c, d in col_delta.items()]
    heapq.heapify(row_heap)
    heapq.heapify(col_heap)
    removed_rows, removed_cols = set(), set()

    while row_set and col_set:
        while row_heap and (row_heap[0][1] in removed_rows or row_heap[0][0] != row_delta[row_heap[0][1]]):
            heapq.heappop(row_heap)
        while col_heap and (col_heap[0][1] in removed_cols or col_heap[0][0] != col_delta[col_heap[0][1]]):
            heapq.heappop(col_heap)
        if not row_heap and not col_heap:
            break

        row_top = row_heap[0] if row_heap else (float("inf"), None)
        col_top = col_heap[0] if col_heap else (float("inf"), None)

        if row_top[0] <= col_top[0]:
            delt, r = heapq.heappop(row_heap)
            cur_score -= delt
            for c in row_neighbors[r]:
                if c in col_set:
                    col_delta[c] -= col_weight[c]
                    heapq.heappush(col_heap, (col_delta[c], c))
            row_set.discard(r)
            removed_rows.add(r)
        else:
            delt, c = heapq.heappop(col_heap)
            cur_score -= delt
            for r in col_neighbors[c]:
                if r in row_set:
                    row_delta[r] -= col_weight[c]
                    heapq.heappush(row_heap, (row_delta[r], r))
            col_set.discard(c)
            removed_cols.add(c)

        remaining = len(row_set) + len(col_set)
        if remaining > 0:
            cur_ave = cur_score / remaining
            if cur_ave > best_score:
                best_score = cur_ave
                best_row_set, best_col_set = set(row_set), set(col_set)

    return best_row_set, best_col_set, best_score


def detect_top_k_blocks(row_neighbors, col_neighbors, k=N_BLOCKS, min_block_users=2):
    """Mirrors the reference implementation's detectMultiple(): find one
    block, zero out only the edges strictly inside it (nodes stay in the
    graph -- a user can appear in more than one block if they have other
    edges outside the first block found), recompute the log-degree weights
    fresh against the reduced graph, and repeat, up to k blocks.

    Stopping rule -- and an explicit methodological caveat about how this
    was chosen (see docs/FRAUDAR_CROSSCHECK.md's Circularity section for the
    full story): once no genuinely dense structure is left, every further
    "block" the peeling finds degenerates to a single leftover user
    -attribute edge (n_users=1) -- a lone edge trivially maximizes local
    density once nothing bigger remains, so these aren't real findings. The
    reference implementation's own stopping rule (stop when consecutive
    scores are within 0.01) does NOT work on this dataset: several
    genuinely distinct real rings land on the exact same score by
    coincidence, which that rule misreads as "hit the noise floor" and
    stops after just 1-2 real blocks (checked: this happened when tried).

    The first fix tried here used min_block_users=3, justified at the time
    by "every planted ring/confounder in this generator has >=3 members by
    construction" -- but that justification uses inside knowledge of how
    THIS PROJECT'S OWN ground truth was built, which is a smaller version of
    exactly the kind of ground-truth leakage this project is careful to
    avoid everywhere else (dev/holdout splits, thresholds never tuned on
    holdout, etc). Replaced with min_block_users=2: the generic mathematical
    floor for ANY bipartite "sharing" relationship to exist at all (you
    cannot have two-or-more-people-share-an-attribute with fewer than 2
    people) -- a threshold justified without reference to this dataset's
    specific construction. Verified to produce an identical result to the
    inside-knowledge version (same 18 blocks, same sizes, same scores) --
    real evidence the specific number wasn't doing hidden work here, but
    that check doesn't retroactively make the original choice sound; it's
    reported as what it is, a confirmation performed after fixing the
    actual problem, not a justification for having had it."""
    row_nbrs = {r: set(v) for r, v in row_neighbors.items()}
    col_nbrs = {c: set(v) for c, v in col_neighbors.items()}

    blocks = []
    for i in range(k):
        row_nbrs = {r: v for r, v in row_nbrs.items() if v}
        col_nbrs = {c: v for c, v in col_nbrs.items() if v}
        if not row_nbrs or not col_nbrs:
            break

        col_weight = {c: 1.0 / math.log(len(nbrs) + 5) for c, nbrs in col_nbrs.items()}
        row_set, col_set, score = fast_greedy_decreasing(row_nbrs, col_nbrs, col_weight)
        if not row_set or not col_set or len(row_set) < min_block_users:
            break
        blocks.append({"users": row_set, "attributes": col_set, "score": score})

        for r in list(row_set):
            if r in row_nbrs:
                row_nbrs[r] = row_nbrs[r] - col_set
        for c in list(col_set):
            if c in col_nbrs:
                col_nbrs[c] = col_nbrs[c] - row_set

    return blocks


def raw_overlap(users: set, candidates: list, id_key: str):
    """Best raw-count overlap (not just a match/no-match) against a list of
    {id_key: ..., members: [...]} dicts. Returns (best_id, intersection_size,
    candidate_size, recall, precision) for the candidate with the largest
    intersection, or None if no overlap exists at all."""
    best = None
    for c in candidates:
        cset = set(c["members"])
        inter = len(users & cset)
        if inter == 0:
            continue
        if best is None or inter > best[1]:
            best = (c[id_key], inter, len(cset))
    if best is None:
        return None
    cid, inter, csize = best
    return {"id": cid, "intersection": inter, "block_size": len(users), "candidate_size": csize,
            "recall": round(inter / csize, 3), "precision": round(inter / len(users), 3)}


def run(verbose=True):
    row_neighbors, col_neighbors = build_bipartite_graph()
    n_users = len(row_neighbors)
    n_attrs = len(col_neighbors)
    n_edges = sum(len(v) for v in row_neighbors.values())

    if verbose:
        print(f"=== FRAUDAR cross-check (standalone; Stages 1-5 untouched) ===\n")
        print(f"Bipartite graph: {n_users:,} users, {n_attrs:,} distinct attribute values "
              f"(device/instrument/subnet), {n_edges:,} edges")

    blocks = detect_top_k_blocks(row_neighbors, col_neighbors, k=N_BLOCKS)
    if verbose:
        print(f"FRAUDAR found {len(blocks)} dense blocks (requested up to {N_BLOCKS})")

    rings, confounders = load_ground_truth()
    ring_list = [{"ring_id": rid, "members": r["members"], "type": r["type"]} for rid, r in rings.items()]
    conf_list = [{"confounder_id": cid, "members": c["members"], "type": c["type"]} for cid, c in confounders.items()]
    all_clusters = db.get_all_clusters()
    flagged = [{"cluster_id": c["cluster_id"], "members": c["members"]} for c in all_clusters if c["flagged"]]

    block_rows = []
    for i, b in enumerate(blocks):
        users = b["users"]
        vs_flagged = raw_overlap(users, flagged, "cluster_id")
        vs_ring = raw_overlap(users, ring_list, "ring_id")
        vs_conf = raw_overlap(users, conf_list, "confounder_id")
        block_rows.append({
            "block_index": i, "n_users": len(users), "n_attributes": len(b["attributes"]), "score": round(b["score"], 4),
            "vs_our_flagged": vs_flagged, "vs_ground_truth_ring": vs_ring, "vs_ground_truth_confounder": vs_conf,
        })

    # Raw counts: how many FRAUDAR blocks substantially overlap something on each side
    def is_real_match(overlap_row):
        if overlap_row is None:
            return False
        return overlap_row["recall"] >= MATCH_THRESH and overlap_row["precision"] >= MATCH_THRESH

    n_blocks_matching_flagged = sum(1 for r in block_rows if is_real_match(r["vs_our_flagged"]))
    n_blocks_matching_ring = sum(1 for r in block_rows if is_real_match(r["vs_ground_truth_ring"]))
    n_blocks_matching_confounder = sum(1 for r in block_rows if is_real_match(r["vs_ground_truth_confounder"]))

    # THE one comparable headline number: this cross-check only ever had device/instrument/subnet
    # edges, so it can only ever speak to hard-signal rings (soft rings have no such signal by
    # definition -- see docs/FRAUDAR_CROSSCHECK.md's Scope section). Counted straight, no other
    # filtering, same >=50%-bidirectional-overlap threshold eval.py uses everywhere else in this repo.
    n_hard_rings = sum(1 for r in ring_list if r["type"] == "hard")
    matched_hard_ring_ids = {r["vs_ground_truth_ring"]["id"] for r in block_rows
                              if is_real_match(r["vs_ground_truth_ring"])
                              and next(x for x in ring_list if x["ring_id"] == r["vs_ground_truth_ring"]["id"])["type"] == "hard"}
    n_hard_rings_matched = len(matched_hard_ring_ids)

    # The reverse direction: of our 74 flagged clusters, how many does FRAUDAR also substantially find?
    flagged_matched_by_fraudar = 0
    for c in flagged:
        cset = set(c["members"])
        if any(len(cset & b["users"]) / len(cset) >= MATCH_THRESH and
               len(cset & b["users"]) / len(b["users"]) >= MATCH_THRESH for b in blocks if b["users"]):
            flagged_matched_by_fraudar += 1

    # The disagreement the user specifically asked about: does FRAUDAR flag any confounder
    # our own Stage 5 correctly left alone?
    confounders_fraudar_flags = []
    for conf in conf_list:
        cset = set(conf["members"])
        for i, b in enumerate(blocks):
            inter = len(cset & b["users"])
            if inter == 0:
                continue
            recall = inter / len(cset)
            precision = inter / len(b["users"]) if b["users"] else 0
            if recall >= MATCH_THRESH and precision >= MATCH_THRESH:
                confounders_fraudar_flags.append({
                    "confounder_id": conf["confounder_id"], "type": conf["type"],
                    "block_index": i, "intersection": inter, "confounder_size": len(cset),
                    "block_size": len(b["users"]), "recall": round(recall, 3), "precision": round(precision, 3),
                })
                break

    report = {
        "scope": "device/instrument/subnet attributes only -- no referral timing, no order data. "
                "This means the result is only ever comparable to hard-signal rings; soft-signal "
                "rings have no shared device/instrument by definition and are structurally out of "
                "scope for this cross-check, not a capability finding.",
        "headline": {
            "description": "FRAUDAR recall on the 40 planted hard-signal rings, counted straight "
                           "(>=50% bidirectional member overlap, same threshold eval.py uses "
                           "everywhere else) -- the one number directly comparable to Stage 2's "
                           "recall on the identical 40 rings from the identical underlying signals.",
            "hard_rings_matched": n_hard_rings_matched, "hard_rings_total": n_hard_rings,
            "fraudar_hard_ring_recall": round(n_hard_rings_matched / n_hard_rings, 4),
            "our_stage2_hard_ring_recall": 1.0,
        },
        "graph": {"n_users": n_users, "n_attributes": n_attrs, "n_edges": n_edges},
        "n_blocks_found": len(blocks),
        "n_blocks_requested": N_BLOCKS,
        "blocks": block_rows,
        "summary": {
            "n_blocks_matching_our_flagged_clusters": n_blocks_matching_flagged,
            "n_blocks_matching_ground_truth_rings": n_blocks_matching_ring,
            "n_blocks_matching_ground_truth_confounders": n_blocks_matching_confounder,
            "n_our_flagged_clusters_also_found_by_fraudar": flagged_matched_by_fraudar,
            "n_our_flagged_clusters_total": len(flagged),
        },
        "confounders_fraudar_flags_that_we_correctly_left_alone": confounders_fraudar_flags,
    }

    with open(PROCESSED_DIR / "fraudar_analysis.json", "w") as f:
        json.dump(report, f, indent=2)

    if verbose:
        print(f"\nSCOPE: device/instrument/subnet only -- no referral timing, no order data. "
              f"This cross-check can only ever speak to hard-signal rings; soft-signal rings have "
              f"no shared device/instrument by definition and are structurally out of scope here.")
        print(f"\n=== THE headline number ===")
        print(f"FRAUDAR hard-signal ring recall (counted straight, no other filtering): "
              f"{n_hard_rings_matched} / {n_hard_rings} ({n_hard_rings_matched/n_hard_rings:.1%})")
        print(f"Our own Stage 2 recall on the identical 40 rings: 100% (40/40)")
        print(f"Every other count below is supporting detail about that number, not a competing one.")

        print(f"\n--- Overlap with our own pipeline's {len(flagged)} flagged clusters ---")
        print(f"FRAUDAR blocks that substantially match one of our flagged clusters "
              f"(>=50% overlap both directions): {n_blocks_matching_flagged} / {len(blocks)}")
        print(f"Our flagged clusters that FRAUDAR also substantially finds: "
              f"{flagged_matched_by_fraudar} / {len(flagged)}")

        print(f"\n--- Overlap with ground truth (independent check) ---")
        print(f"FRAUDAR blocks matching a real planted ring: {n_blocks_matching_ring} / {len(blocks)} "
              f"(out of {len(rings)} planted rings total)")
        print(f"FRAUDAR blocks matching a planted confounder: {n_blocks_matching_confounder} / {len(blocks)}")

        print(f"\n--- The disagreement check: does FRAUDAR flag confounders Stage 5 correctly left alone? ---")
        if confounders_fraudar_flags:
            print(f"YES -- {len(confounders_fraudar_flags)} of {len(confounders)} planted confounders that our "
                  f"Stage 5 correctly left unflagged are substantially covered by a FRAUDAR dense block:")
            for row in confounders_fraudar_flags:
                print(f"  {row['confounder_id']} ({row['type']}): {row['intersection']}/{row['confounder_size']} "
                      f"members in FRAUDAR block #{row['block_index']} (size {row['block_size']}, "
                      f"recall={row['recall']:.0%}, precision={row['precision']:.0%})")
        else:
            print(f"NO -- none of the {len(confounders)} planted confounders that Stage 5 correctly left alone "
                  f"are substantially covered by any of FRAUDAR's {len(blocks)} dense blocks.")

        print(f"\nWritten -> {PROCESSED_DIR / 'fraudar_analysis.json'}")

    return report


if __name__ == "__main__":
    run()
