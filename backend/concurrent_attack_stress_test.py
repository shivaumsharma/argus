"""
Concurrent multi-ring attack stress test -- does detection hold up when several
sophisticated, evasive rings operate at the same time, not one at a time?

Every adversarial test built so far (adversarial_stress_test.py, the
recommendation engine's attack_generator.py) injects exactly ONE evasive ring
into a disposable copy of the dataset and asks whether it is caught. That
structurally cannot surface an interference effect -- e.g. two simultaneous
rings' graph edges accidentally merging Stage 3's Louvain communities, or the
added graph mass shifting a legitimate confounder's cluster boundary. This
script injects several evasive rings AT ONCE and checks both directions: is
each individual ring still caught (or not), and does adding several of them
together wrongly flag any of the dataset's real, planted, legitimate
confounders as a side effect.

Two evasion strategies, deliberately different, both reusing already-built,
already-validated generation logic rather than inventing something new for
this test alone:

  - "masks hard signals": no shared device or instrument at all -- the only
    edge Stage 1 can find is the referral chain / IP overlap, with organic
    -looking timing. This is exactly backend/adversarial_recommender's
    attack_generator.generate_variant(), reused unchanged, called several
    times with different seeds for genuine variety (not the same ring
    repeated).
  - "masks soft signals": DOES share a device (the hard signal Stage 2 exists
    to catch), but dials its behavioral/temporal features -- signup spread,
    order-value diversity, post-signup engagement -- to simultaneously clear
    all three of Stage 5's organic checks, the same organic-knob-targeting
    technique attack_generator.py already uses, applied to the device branch
    instead of the soft-signal branch (a genuinely different, not yet
    exercised, evasion path through evaluate_cluster()).

Isolation: injected into a disposable tempdir copy of data/raw/, run through
the unmodified Stage 1-5 pipeline, cleaned up in a `finally` block. Never
touches data/raw/, data/frozen_snapshot/, or the frozen eval snapshot.

Run: python -m backend.concurrent_attack_stress_test
"""

import random
import shutil
import string
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from .adversarial_recommender import attack_generator
from .pipeline.clustering import dedupe_candidates, stage2_hard_clusters, stage3_soft_clusters
from .pipeline.confounder_filter import evaluate_cluster
from .pipeline.data_io import GT_DIR, RAW_DIR, load_data
from .pipeline.eval import best_match
from .pipeline.features import build_lookups, compute_features
from .pipeline.graph_build import build_graph, hard_signal_subgraph

TODAY = datetime(2026, 8, 28)
RING_SIZE = 7
N_HARD_MASKING = 4   # no shared device/instrument -- soft-signal-only evasion
N_SOFT_MASKING = 4   # shared device, but organic-mimicking behavior
MASTER_SEED = 86358735  # fresh, never used before this script -- checked against and
                         # registered in data/adversarial_recommender/used_seeds.json's manifest


def _rand_phone():
    return "+91" + str(random.choice([6, 7, 8, 9])) + "".join(random.choices(string.digits, k=9))


def _rand_pincode():
    return str(random.randint(1, 8)) + "".join(random.choices(string.digits, k=5))


def _rand_device_id():
    return "dfp_" + "".join(random.choices("0123456789abcdef", k=16))


def _rand_instrument_hash():
    return "upi_" + "".join(random.choices(string.ascii_lowercase + string.digits, k=10)) + "@" + random.choice(
        ["okhdfcbank", "oksbi", "okicici", "okaxis"]
    )


def _rand_ip():
    return f"{random.randint(1,223)}.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(2,254)}"


def build_soft_masking_ring(tag: str, seed: int, span_days: float = 23.0,
                            order_cv_target: float = 0.30, engagement_target: float = 1.8):
    """Shares a device (the hard signal Stage 2 exists to catch) but dials
    signup spread, order-value CV, and post-signup engagement to all clear
    Stage 5's organic checks at once -- the same organic-knob targeting
    attack_generator.py uses, aimed at DEVICE_CLEAR_ORGANIC_THRESHOLD (3)
    instead of the soft-only branch. Real evasion strategy: a farmer who
    reuses one device/kit for cost reasons but fakes organic usage patterns
    on top of it, rather than avoiding a shared device altogether.

    Defaults (span_days=23, order_cv=0.30, engagement=1.8) sit just past the
    real production thresholds (21 / 0.28 / 1.5) -- this test's original use.
    time_drift_simulation.py reuses this same function with earlier-period,
    still-suspicious target values instead of new generator code."""
    random.seed(seed)
    np.random.seed(seed)

    accounts, sessions, referrals, instruments, orders = [], [], [], [], []
    uid_of = lambda i: f"U{tag}{i:03d}"
    shared_device = _rand_device_id()
    start = TODAY - timedelta(days=random.uniform(200, 300))
    per_gap = span_days / max(RING_SIZE - 1, 1)
    order_id = session_id = 1

    for i in range(RING_SIZE):
        uid = uid_of(i)
        signup = start + timedelta(days=i * per_gap + random.uniform(-0.4, 0.4))
        ip = _rand_ip()
        instrument = _rand_instrument_hash()  # distinct instruments -- only the device is shared
        pincode = _rand_pincode()

        accounts.append({
            "user_id": uid, "signup_date": signup.strftime("%Y-%m-%d"), "phone_number": _rand_phone(),
            "email": f"{tag.lower()}{i}@gmail.com", "device_fingerprint_id": shared_device,
            "ip_address_at_signup": ip, "referral_code_used": "", "referred_by_user_id": "",
            "kyc_status": random.choices(["verified", "pending"], weights=[0.8, 0.2])[0], "home_pincode": pincode,
        })
        instruments.append({"user_id": uid, "instrument_hash": instrument,
                            "instrument_first_seen_date": signup.strftime("%Y-%m-%d")})
        sessions.append({"session_id": f"S{tag}{session_id:04d}", "user_id": uid,
                         "device_fingerprint_id": shared_device, "ip_address": ip,
                         "timestamp": signup.strftime("%Y-%m-%d %H:%M:%S"), "action_type": "signup"})
        session_id += 1

        n_orders = random.randint(4, 9)
        mean_val = 650.0
        ts = signup
        for _ in range(n_orders):
            ts = ts + timedelta(days=np.random.exponential(20) + 2)
            if ts > TODAY:
                break
            z = np.random.normal(0, 1)
            value = max(99, mean_val * (1 + order_cv_target * z))
            orders.append({"user_id": uid, "order_id": f"O{tag}{order_id:04d}", "order_value": round(value, 2),
                           "order_date": ts.strftime("%Y-%m-%d"), "delivery_pincode": pincode})
            order_id += 1
            sessions.append({"session_id": f"S{tag}{session_id:04d}", "user_id": uid,
                             "device_fingerprint_id": shared_device, "ip_address": ip,
                             "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"), "action_type": "order_placed"})
            session_id += 1

        n_logins = max(1, round(engagement_target * random.uniform(0.8, 1.4) * 6))
        ts = signup
        for _ in range(n_logins):
            ts = ts + timedelta(days=np.random.exponential(12) + 1)
            if ts > TODAY:
                break
            sessions.append({"session_id": f"S{tag}{session_id:04d}", "user_id": uid,
                             "device_fingerprint_id": shared_device, "ip_address": ip,
                             "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"), "action_type": "login"})
            session_id += 1

    return {
        "attack_id": tag, "strategy": "masks_soft_signals",
        "description": f"Shared device ({shared_device}), but signup span ~{span_days:.0f}d, order CV "
                       f"target {order_cv_target}, engagement target {engagement_target} -- dialed to clear "
                       f"all three of Stage 5's organic checks on the device branch at once.",
        "accounts": accounts, "sessions": sessions, "referrals": referrals,
        "instruments": instruments, "orders": orders, "members": [uid_of(i) for i in range(RING_SIZE)],
    }


def build_hard_masking_ring(tag: str, seed: int):
    """No shared device or instrument at all -- reuses attack_generator.generate_variant()
    completely unchanged (the same already-validated evasion logic behind the
    adversarial recommender's round 2+), just re-namespaced so several of these can be
    injected into the same cohort without id collisions."""
    targets = {"spread_out_days": 21, "diverse_order_cv": 0.28, "engaged_sessions": 1.5}
    raw = attack_generator.generate_variant(round_number=1, seed=seed, targets=targets)

    def renamespace(rows, id_keys):
        out = []
        for row in rows:
            row = dict(row)
            for k in id_keys:
                if k in row and row[k]:
                    row[k] = f"{tag}_{row[k]}"
            out.append(row)
        return out

    accounts = renamespace(raw["accounts"], ["user_id", "referred_by_user_id"])
    for a in accounts:
        a["referral_code_used"] = f"{tag}_{a['referral_code_used']}" if a["referral_code_used"] else ""
    referrals = []
    for r in raw["referrals"]:
        r = dict(r)
        r["referral_id"] = f"{tag}_{r['referral_id']}"
        r["referrer_user_id"] = f"{tag}_{r['referrer_user_id']}"
        r["referred_user_id"] = f"{tag}_{r['referred_user_id']}"
        referrals.append(r)
    sessions = renamespace(raw["sessions"], ["session_id", "user_id"])
    instruments = renamespace(raw["instruments"], ["user_id"])
    orders = renamespace(raw["orders"], ["order_id", "user_id"])
    members = [f"{tag}_{m}" for m in raw["members"]]

    return {
        "attack_id": tag, "strategy": "masks_hard_signals",
        "description": f"Re-namespaced attack_generator.generate_variant() (seed={seed}), unchanged evasion "
                       f"logic: no shared device/instrument, referral-chain-only, organic-mimicking timing.",
        "accounts": accounts, "sessions": sessions, "referrals": referrals,
        "instruments": instruments, "orders": orders, "members": members,
    }


def build_cohort():
    rng = random.Random(MASTER_SEED)
    rings = []
    for i in range(N_HARD_MASKING):
        tag = f"CHM{i:02d}"
        rings.append(build_hard_masking_ring(tag, seed=rng.randint(10_000, 99_999)))
    for i in range(N_SOFT_MASKING):
        tag = f"CSM{i:02d}"
        rings.append(build_soft_masking_ring(tag, seed=rng.randint(10_000, 99_999)))
    return rings


def inject(src_dir: Path, dst_dir: Path, rings: list):
    dst_dir.mkdir(parents=True, exist_ok=True)
    for name, key in [
        ("accounts.csv", "accounts"), ("sessions.csv", "sessions"), ("referrals.csv", "referrals"),
        ("payment_instruments.csv", "instruments"), ("orders.csv", "orders"),
    ]:
        existing = pd.read_csv(src_dir / name, dtype=str)
        new_rows = [row for ring in rings for row in ring[key]]
        combined = pd.concat([existing, pd.DataFrame(new_rows).astype(str)], ignore_index=True)
        combined.to_csv(dst_dir / name, index=False)


def _flagged_confounder_ids(raw_dir: Path, confounders: dict) -> set:
    """Runs the unmodified Stage 1-5 pipeline against `raw_dir` and returns the set of
    confounder ids wrongly flagged. Used both for the "N rings injected" cohort and,
    critically, for a zero-rings baseline pass -- without that baseline, this test
    would misattribute the dataset's one pre-existing known false positive (the
    "tight household" confounder, already flagged with nothing injected at all) to
    "interference," when it isn't."""
    data = load_data(raw_dir=raw_dir)
    G = build_graph(data)
    H = hard_signal_subgraph(G)
    hard_clusters = stage2_hard_clusters(H)
    soft_clusters = stage3_soft_clusters(G)
    candidates = dedupe_candidates(hard_clusters, soft_clusters)
    device_by_user, instrument_by_user = build_lookups(data)

    flagged = []
    for members, stage in candidates:
        feats = compute_features(G, members, data, device_by_user, instrument_by_user)
        verdict = evaluate_cluster(feats)
        if verdict["flagged"]:
            flagged.append({"members": sorted(members), "detection_stage": stage})

    hit_ids = set()
    for cid, c in confounders.items():
        if best_match(set(c["members"]), flagged):
            hit_ids.add(cid)
    return hit_ids


def run():
    import json
    rings = build_cohort()
    n_hard = sum(1 for r in rings if r["strategy"] == "masks_hard_signals")
    n_soft = sum(1 for r in rings if r["strategy"] == "masks_soft_signals")
    print(f"=== Concurrent multi-ring attack stress test ===")
    print(f"Injecting {len(rings)} evasive rings at once: {n_hard} masking hard signals "
          f"(no shared device/instrument), {n_soft} masking soft signals (shared device, "
          f"organic-mimicking behavior). Master seed: {MASTER_SEED}.\n")

    tmp = Path(tempfile.mkdtemp(prefix="sentinel_concurrent_"))
    try:
        inject(RAW_DIR, tmp, rings)
        data = load_data(raw_dir=tmp)
        G = build_graph(data)
        H = hard_signal_subgraph(G)

        hard_clusters = stage2_hard_clusters(H)
        soft_clusters = stage3_soft_clusters(G)
        candidates = dedupe_candidates(hard_clusters, soft_clusters)
        device_by_user, instrument_by_user = build_lookups(data)

        flagged = []
        all_evaluated = []
        for members, stage in candidates:
            feats = compute_features(G, members, data, device_by_user, instrument_by_user)
            verdict = evaluate_cluster(feats)
            all_evaluated.append({"members": members, "stage": stage, "verdict": verdict})
            if verdict["flagged"]:
                flagged.append({"members": sorted(members), "detection_stage": stage})

        print(f"Candidate clusters found by Stage 2/3: {len(candidates)}. Flagged by Stage 5: {len(flagged)}.\n")

        # --- per-ring outcome, raw, never blended ---
        print("--- Per-ring outcome ---")
        results = []
        for ring in rings:
            member_set = set(ring["members"])
            match = best_match(member_set, flagged)
            caught = match is not None
            # which stage found it as a candidate at all (whether or not Stage 5 flagged it)
            candidate_stage = None
            for c in all_evaluated:
                overlap = member_set & c["members"]
                if len(overlap) >= len(member_set) // 2:
                    candidate_stage = c["stage"]
                    break
            results.append({
                "attack_id": ring["attack_id"], "strategy": ring["strategy"], "caught": caught,
                "candidate_stage": candidate_stage,
            })
            status = f"CAUGHT (stage={match['detection_stage']})" if caught else \
                     (f"missed (clustered at stage={candidate_stage}, not flagged)" if candidate_stage else
                      "missed (never even clustered)")
            print(f"  {ring['attack_id']:8s} [{ring['strategy']:18s}] -- {status}")

        n_caught = sum(1 for r in results if r["caught"])
        print(f"\nRaw result: {n_caught}/{len(rings)} rings caught "
              f"({sum(1 for r in results if r['strategy']=='masks_hard_signals' and r['caught'])}/{n_hard} "
              f"masking hard signals, "
              f"{sum(1 for r in results if r['strategy']=='masks_soft_signals' and r['caught'])}/{n_soft} "
              f"masking soft signals).")

        # --- interference check: did adding several rings at once wrongly flag any
        # real, planted, legitimate confounder that this pipeline would NOT flag with
        # zero rings injected? A bare "is it flagged" check would misattribute this
        # dataset's one pre-existing known false positive (the "tight household"
        # confounder -- flagged even with nothing injected at all, see
        # ARCHITECTURE.md's Known Limitations) to "interference." A proper control
        # pass is required, not assumed. ---
        print("\n--- Interference check: real planted confounders (baseline-controlled) ---")
        confounders = json.loads((GT_DIR / "confounders.json").read_text())
        conf_ids_with_attacks = {cid for cid, c in confounders.items() if best_match(set(c["members"]), flagged)}

        baseline_tmp = Path(tempfile.mkdtemp(prefix="sentinel_concurrent_baseline_"))
        try:
            inject(RAW_DIR, baseline_tmp, [])  # zero rings -- a straight copy of RAW_DIR, the actual control
            conf_ids_baseline = _flagged_confounder_ids(baseline_tmp, confounders)
        finally:
            shutil.rmtree(baseline_tmp, ignore_errors=True)

        new_interference_ids = conf_ids_with_attacks - conf_ids_baseline
        print(f"Planted confounders in this dataset: {len(confounders)}.")
        print(f"  Flagged with ZERO rings injected (baseline control): {sorted(conf_ids_baseline)} "
              f"({len(conf_ids_baseline)})")
        print(f"  Flagged with {len(rings)} concurrent attacks injected: {sorted(conf_ids_with_attacks)} "
              f"({len(conf_ids_with_attacks)})")
        if new_interference_ids:
            for cid in sorted(new_interference_ids):
                c = confounders[cid]
                print(f"  NEW INTERFERENCE: {cid} ({c['type']}, {len(c['members'])} members) -- flagged only "
                      f"when the concurrent attacks were present, not in the zero-attack baseline.")
        else:
            print(f"  None. Every confounder flagged in the {len(rings)}-attack run was ALSO already flagged "
                  "in the zero-attack baseline -- no new interference effect found in this run, once the "
                  "dataset's one pre-existing known false positive is correctly controlled for.")

        report = {
            "master_seed": MASTER_SEED, "n_rings_injected": len(rings),
            "n_masking_hard_signals": n_hard, "n_masking_soft_signals": n_soft,
            "n_caught": n_caught, "per_ring": results,
            "n_confounders": len(confounders),
            "confounders_flagged_baseline": sorted(conf_ids_baseline),
            "confounders_flagged_with_attacks": sorted(conf_ids_with_attacks),
            "new_interference_confounders": sorted(new_interference_ids),
        }
        out_path = Path(__file__).resolve().parents[1] / "data" / "processed" / "concurrent_attack_stress_test.json"
        out_path.write_text(json.dumps(report, indent=2))
        print(f"\nWritten -> {out_path}")
        return report
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    run()
