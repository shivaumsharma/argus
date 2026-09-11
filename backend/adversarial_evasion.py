"""
Adversarial evasion via graph fragmentation -- a structural attack axis this
project hadn't tested yet. Every prior adversarial test varies WHAT a ring
looks like once formed: attack_generator.py drops the shared hard signal
entirely (soft-only evasion), concurrent_attack_stress_test.py's
build_soft_masking_ring() keeps one shared device but fakes organic timing/
spending (behavioral evasion), time_drift_simulation.py escalates those same
behavioral knobs across periods. None of them vary the SHAPE of the sharing
graph itself while holding ring size and behavior fixed.

Three tactics tested, isolated from each other so each one's real effect is
attributable, not blended together:

1. SPARSIFY EDGES: instead of N accounts all sharing ONE device (a single
   dense clique, Stage 2's easiest case), split the same N accounts into K
   independent pods, each sharing its OWN device internally, zero edge
   between pods -- "run K small device/kit setups instead of one big one."
2. MIMIC LEGITIMATE DENSITY: at the point of complete atomization (pod
   size 1 -- no shared device at all), does giving the group one other real
   -world attribute in common (an IP subnet, the way accounts on the same
   physical network naturally would) let it hide as an ordinary shared
   -infrastructure cluster?
3. SPREAD ACTIVITY OVER TIME: layered on top of (2) -- accounts atomized,
   subnet-linked, AND their signups spread across ~33 days instead of
   launched together.

Behavior is held deliberately, obviously suspicious throughout in all three
(2-day signup burst per pod, templated order values, a fast referral claim
followed by total silence -- the complete claim-then-dormant archetype,
including the referral_claim session Stage 4 actually reads
claim_then_dormant_frac / bonus_claim_velocity_hours from, not just the
order-timing half of it) so any recall change is attributable to the
structural/temporal tactic being tested, not to also faking organic
behavior -- that axis (dialing behavior toward genuinely organic-looking)
is already covered by concurrent_attack_stress_test.py's
build_soft_masking_ring() and time_drift_simulation.py.

Real result, none of it assumed going in:
- Tactic 1 alone does NOT work as evasion -- recall holds at 100% all the
  way down to 2-member pods. Stage 5 scores each candidate cluster on its
  own behavioral merits regardless of size, so a small pod with blatant
  behavior is exactly as catchable as a large one.
- At complete atomization (pod size 1) with NO other shared attribute at
  all, recall drops to 0% -- a real limitation, but not a new one: the
  same zero-shared-attribute blind spot already disclosed for isolated
  Elliptic transactions and this project's own stated architecture limits,
  now confirmed directly in this system's own primary domain rather than
  assumed to transfer.
- Tactics 2 and 3 both fail to hold that evasion once tested: an IP-subnet
  -only link between the atomized accounts is enough for Stage 3's
  EXISTING Louvain clustering (already built, zero code change) to recover
  100% recall -- and spreading the same accounts' signups across ~33 days
  on top of that does not undo it. The floor is genuinely zero shared
  attributes of any kind, not "zero shared HARD signal."

No countermeasure was tuned, because none of the three tactics tested
actually degraded detection short of that theoretical floor -- reported as
a real robustness finding, not manufactured by picking an easy attack to
beat. Full numbers in data/processed/adversarial_evasion.json.

Isolation: identical pattern to concurrent_attack_stress_test.py -- injected
into a disposable tempdir copy of data/raw/, unmodified Stage 1-5 pipeline,
cleaned up in a `finally` block. Never touches data/raw/ or the frozen
snapshot.

Run: python -m backend.adversarial_evasion
"""

import json
import random
import shutil
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from .concurrent_attack_stress_test import _rand_instrument_hash, _rand_ip, _rand_pincode, _rand_phone, _rand_device_id
from .pipeline.clustering import dedupe_candidates, stage2_hard_clusters, stage3_soft_clusters
from .pipeline.confounder_filter import evaluate_cluster
from .pipeline.data_io import RAW_DIR, load_data
from .pipeline.eval import best_match
from .pipeline.features import build_lookups, compute_features
from .pipeline.graph_build import build_graph, hard_signal_subgraph

TODAY = datetime(2026, 9, 11)
RING_SIZE = 12
POD_COUNTS = (1, 2, 3, 4, 6)  # pod sizes: 12, 6, 4, 3, 2 members each
MASTER_SEED = 71940852  # fresh, never used before this script


def build_fragmented_ring(tag: str, seed: int, n_pods: int, ring_size: int = RING_SIZE,
                           shared_subnet: bool = False, stagger_days: float = 3.0):
    """`ring_size` accounts split into `n_pods` equal-as-possible pods. Each
    pod shares one pod-specific device internally (a clique of that pod's
    size); zero edges between pods -- Stage 1 never sees a hard-signal edge
    connecting two different pods at all. Behavior is uniformly, deliberately
    suspicious (2-day signup burst, near-identical order values, no activity
    after the bonus claim) so it would clear neither DEVICE_CLEAR_ORGANIC_
    THRESHOLD's spread/CV/engagement checks nor look remotely like a
    household -- the only question this generator exists to answer is
    whether the pod is even SEEN as a candidate cluster at all, not whether
    it looks organic once seen."""
    random.seed(seed)
    np.random.seed(seed)

    pod_sizes = [ring_size // n_pods + (1 if i < ring_size % n_pods else 0) for i in range(n_pods)]
    accounts, sessions, referrals, instruments, orders = [], [], [], [], []
    uid_of = lambda i: f"U{tag}{i:03d}"
    start = TODAY - timedelta(days=random.uniform(60, 200))
    member_idx = 0
    order_id = session_id = 1
    # A soft (IP-subnet) signal deliberately held constant across pods, tested separately from
    # the hard-signal fragmentation above -- e.g. pods run from the same physical network even
    # though each uses its own device, a realistic operational constraint, not a stretch.
    ring_subnet = f"{random.randint(1,223)}.{random.randint(0,255)}.{random.randint(0,255)}"

    for pod_i, pod_size in enumerate(pod_sizes):
        pod_device = _rand_device_id()
        pod_start = start + timedelta(days=pod_i * random.uniform(0, stagger_days))
        for _ in range(pod_size):
            uid = uid_of(member_idx)
            signup = pod_start + timedelta(hours=random.uniform(0, 48))  # 2-day burst, suspicious
            ip = f"{ring_subnet}.{random.randint(2,254)}" if shared_subnet else _rand_ip()
            instrument = _rand_instrument_hash()
            pincode = _rand_pincode()

            accounts.append({
                "user_id": uid, "signup_date": signup.strftime("%Y-%m-%d"), "phone_number": _rand_phone(),
                "email": f"{tag.lower()}{member_idx}@gmail.com", "device_fingerprint_id": pod_device,
                "ip_address_at_signup": ip, "referral_code_used": "", "referred_by_user_id": "",
                "kyc_status": "pending", "home_pincode": pincode,
            })
            instruments.append({"user_id": uid, "instrument_hash": instrument,
                                "instrument_first_seen_date": signup.strftime("%Y-%m-%d")})
            sessions.append({"session_id": f"S{tag}{session_id:04d}", "user_id": uid,
                             "device_fingerprint_id": pod_device, "ip_address": ip,
                             "timestamp": signup.strftime("%Y-%m-%d %H:%M:%S"), "action_type": "signup"})
            session_id += 1

            # Templated order (near-identical value, CV ~0.02) placed within hours of signup,
            # then a fast referral_claim, then silence -- the full claim-then-dormant archetype,
            # not just the order-timing half of it. claim_ts is derived purely from a session
            # row with action_type="referral_claim" (backend/pipeline/data_io.py), independent
            # of whether a referrals.csv row exists at all.
            order_ts = signup + timedelta(hours=random.uniform(1, 6))
            value = 499.0 * (1 + np.random.normal(0, 0.02))
            orders.append({"user_id": uid, "order_id": f"O{tag}{order_id:04d}", "order_value": round(value, 2),
                           "order_date": order_ts.strftime("%Y-%m-%d"), "delivery_pincode": pincode})
            order_id += 1
            sessions.append({"session_id": f"S{tag}{session_id:04d}", "user_id": uid,
                             "device_fingerprint_id": pod_device, "ip_address": ip,
                             "timestamp": order_ts.strftime("%Y-%m-%d %H:%M:%S"), "action_type": "order_placed"})
            session_id += 1

            claim_ts = order_ts + timedelta(hours=random.uniform(1, 5))  # fast claim -- <= FAST_CLAIM_HOURS
            sessions.append({"session_id": f"S{tag}{session_id:04d}", "user_id": uid,
                             "device_fingerprint_id": pod_device, "ip_address": ip,
                             "timestamp": claim_ts.strftime("%Y-%m-%d %H:%M:%S"), "action_type": "referral_claim"})
            session_id += 1
            # No further sessions after claim -- dormant by construction (claim_then_dormant_frac -> 1.0).
            member_idx += 1

    return {
        "attack_id": tag, "n_pods": n_pods, "pod_sizes": pod_sizes,
        "description": f"{ring_size} accounts split into {n_pods} pod(s) of size ~{ring_size // n_pods}, "
                       f"each pod sharing its own device, zero edges between pods. Behavior held "
                       f"deliberately suspicious throughout (2-day signup burst, templated order value, "
                       f"claim-then-dormant) so any recall change is attributable to graph shape alone.",
        "accounts": accounts, "sessions": sessions, "referrals": referrals,
        "instruments": instruments, "orders": orders, "members": [uid_of(i) for i in range(ring_size)],
    }


def inject(src_dir: Path, dst_dir: Path, ring: dict):
    import pandas as pd
    dst_dir.mkdir(parents=True, exist_ok=True)
    for name, key in [
        ("accounts.csv", "accounts"), ("sessions.csv", "sessions"), ("referrals.csv", "referrals"),
        ("payment_instruments.csv", "instruments"), ("orders.csv", "orders"),
    ]:
        existing = pd.read_csv(src_dir / name, dtype=str)
        combined = pd.concat([existing, pd.DataFrame(ring[key]).astype(str)], ignore_index=True)
        combined.to_csv(dst_dir / name, index=False)


def _run_pipeline(raw_dir: Path):
    """Unmodified Stage 1-5, called directly -- identical sequence to
    concurrent_attack_stress_test.py's own run(), not a new wrapper."""
    data = load_data(raw_dir=raw_dir)
    G = build_graph(data)
    H = hard_signal_subgraph(G)
    hard_clusters = stage2_hard_clusters(H)
    soft_clusters = stage3_soft_clusters(G)
    candidates = dedupe_candidates(hard_clusters, soft_clusters)
    device_by_user, instrument_by_user = build_lookups(data)

    flagged, all_evaluated = [], []
    for members, stage in candidates:
        feats = compute_features(G, members, data, device_by_user, instrument_by_user)
        verdict = evaluate_cluster(feats)
        all_evaluated.append({"members": members, "stage": stage, "features": feats, "verdict": verdict})
        if verdict["flagged"]:
            flagged.append({"members": sorted(members), "detection_stage": stage})
    return candidates, flagged, all_evaluated


def _score_ring(ring: dict, flagged: list, all_evaluated: list) -> dict:
    members = set(ring["members"])
    # Recall at the MEMBER level, not ring-level match/no-match: a fragmented
    # ring's pods are separate candidate clusters, so "caught" has to mean
    # "how many of the ring's real members ended up in ANY flagged cluster,"
    # not "was the whole ring matched as one blob" -- the latter is
    # structurally impossible once pods are disconnected from each other.
    captured = set()
    for f in flagged:
        captured |= (members & set(f["members"]))
    candidate_member_sets = [set(c["members"]) for c in all_evaluated]
    n_pods_as_candidates = sum(1 for cs in candidate_member_sets if cs & members and len(cs & members) >= 2)
    return {
        "n_members": len(members), "members_captured": len(captured),
        "recall": round(len(captured) / len(members), 4) if members else None,
        "n_pods_forming_a_candidate_cluster": n_pods_as_candidates,
    }


def sweep(pod_counts=POD_COUNTS, shared_subnet: bool = False, stagger_days: float = 3.0, verbose=True) -> list:
    rng = random.Random(MASTER_SEED)
    results = []
    for n_pods in pod_counts:
        tag = f"FRAG{n_pods:02d}{'S' if shared_subnet else ''}{'T' if stagger_days == 0 else ''}"
        ring = build_fragmented_ring(tag, seed=rng.randint(10_000, 99_999), n_pods=n_pods,
                                     shared_subnet=shared_subnet, stagger_days=stagger_days)
        tmp = Path(tempfile.mkdtemp(prefix="sentinel_evasion_"))
        try:
            inject(RAW_DIR, tmp, ring)
            candidates, flagged, all_evaluated = _run_pipeline(tmp)
            score = _score_ring(ring, flagged, all_evaluated)
            results.append({"n_pods": n_pods, "pod_size": ring["pod_sizes"][0],
                            "shared_subnet": shared_subnet, "stagger_days": stagger_days, **score})
            if verbose:
                print(f"  n_pods={n_pods:2d} (pod size ~{ring['pod_sizes'][0]}): "
                      f"recall={score['recall']:.1%} ({score['members_captured']}/{score['n_members']} members "
                      f"captured), {score['n_pods_forming_a_candidate_cluster']} pod(s) even seen as a candidate cluster")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return results


def run(verbose=True):
    if verbose:
        print("=== Adversarial evasion: graph fragmentation ===")
        print(f"{RING_SIZE} accounts total, split into pods sharing only their own device, zero "
              "hard-signal edges between pods. Behavior held uniformly suspicious throughout, so "
              "any recall change is attributable to graph shape alone.\n")
        print("Part 1 -- fragmenting into pairs and up (pod sizes 12/6/4/3/2), no other signal shared:")
    baseline = sweep(pod_counts=POD_COUNTS, shared_subnet=False, stagger_days=0, verbose=verbose)

    if verbose:
        print("\nPart 2 -- the true limiting case: full atomization (pod size 1 -- no shared device "
              "at all). Three isolated conditions, so the effect of each tactic can be told apart:")
        print("  (a) atomized, tight timing, no other shared signal:")
    atomized_tight_no_subnet = sweep(pod_counts=(RING_SIZE,), shared_subnet=False, stagger_days=0, verbose=verbose)
    if verbose:
        print("  (b) atomized, tight timing, shared IP subnet (existing Stage 3 soft-signal mechanism, no code change):")
    atomized_tight_subnet = sweep(pod_counts=(RING_SIZE,), shared_subnet=True, stagger_days=0, verbose=verbose)
    if verbose:
        print("  (c) atomized, ALSO spread over ~33 days, shared IP subnet -- fragmentation + time-spreading combined:")
    atomized_spread_subnet = sweep(pod_counts=(RING_SIZE,), shared_subnet=True, stagger_days=3.0, verbose=verbose)

    report = {"baseline": baseline, "atomized_tight_no_subnet": atomized_tight_no_subnet,
              "atomized_tight_subnet": atomized_tight_subnet, "atomized_spread_subnet": atomized_spread_subnet}
    from .pipeline.data_io import PROCESSED_DIR
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out_path = PROCESSED_DIR / "adversarial_evasion.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if verbose:
        print(f"\nWritten -> {out_path}")
    return report


if __name__ == "__main__":
    run()
