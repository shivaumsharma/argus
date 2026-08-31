"""
Time-drift simulation -- every eval in this project so far is a single point
in time. This asks: does detection hold up as fraud tactics evolve across
successive periods, or does it decay?

Design, reusing already-built generator logic rather than parallel code:
each period injects a ring population built from the SAME two functions
already proven elsewhere this session -- attack_generator.generate_variant()
for the no-shared-device population, concurrent_attack_stress_test.py's
build_soft_masking_ring() for the shared-device population -- fed
progressively less-suspicious knob targets. The knobs only move for a
population that was STILL being caught in the previous period (recall > 0);
once a population reaches 0% recall it stops evolving, because a real
adversary that has already fully evaded has no further pressure to change --
this is what makes the schedule a genuine per-period *adaptation* to the
prior period's measured outcome, not a pre-baked ramp.

Non-negotiable, never relaxed: Stage 1-5 (backend/pipeline/*.py) is called
completely unmodified, with NO overrides, in every single period. Nothing
here retrains anything or applies an adversarial-recommender-style
threshold change mid-simulation -- the entire point is isolating "does
static detection logic decay against an adapting adversary" from "did the
detection logic itself improve," and conflating the two would erase the
result this test exists to produce.

Isolation: the real, frozen data/raw/ background and confounders are reused
read-only, injected into a fresh disposable tempdir copy every period, never
modified. A confounder false-positive count uses the same baseline-control
method as concurrent_attack_stress_test.py, computed once (the background is
identical every period, so the baseline doesn't need re-running each time).

Run: python -m backend.time_drift_simulation
"""

import json
import random
import shutil
import string
import tempfile
from datetime import timedelta
from pathlib import Path

import numpy as np

from .adversarial_recommender import attack_generator
from .adversarial_stress_test import TODAY
from .concurrent_attack_stress_test import RING_SIZE, _flagged_confounder_ids, build_soft_masking_ring, inject
from .pipeline.clustering import dedupe_candidates, stage2_hard_clusters, stage3_soft_clusters
from .pipeline.confounder_filter import evaluate_cluster
from .pipeline.data_io import GT_DIR, RAW_DIR, load_data
from .pipeline.eval import best_match
from .pipeline.features import build_lookups, compute_features
from .pipeline.graph_build import build_graph, hard_signal_subgraph

N_PERIODS = 4
RINGS_PER_POPULATION = 8   # per period, per population (no-device / shared-device)
MASTER_SEED = 55019283  # candidate starting point; run() checks it (and increments past any
                         # collision) against used_seeds.json before use, per this project's manifest discipline

# Real production thresholds (the eventual convergence point for a fully-adapted
# adversary on the shared-device population -- these are
# backend/pipeline/confounder_filter.py's actual values, not invented for this test).
PROD_SPREAD_OUT_DAYS = 21
PROD_DIVERSE_ORDER_CV = 0.28
PROD_ENGAGED_SESSIONS = 1.5

# Period-1 (naive, obviously-fraudulent) starting point for the shared-device
# population -- deliberately well inside the suspicious range on every knob.
START_SPREAD_OUT_DAYS = 3
START_DIVERSE_ORDER_CV = 0.05
START_ENGAGED_SESSIONS = 0.2


def _rand_phone():
    return "+91" + str(random.choice([6, 7, 8, 9])) + "".join(random.choices(string.digits, k=9))


def _rand_pincode():
    return str(random.randint(1, 8)) + "".join(random.choices(string.digits, k=5))


def _rand_device_id():
    return "dfp_" + "".join(random.choices("0123456789abcdef", k=16))


def _rand_ip():
    return f"{random.randint(1,223)}.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(2,254)}"


def build_naive_to_evasive_ring(tag: str, seed: int, sophistication: float) -> dict:
    """No shared device/instrument, referral-chain-only -- but unlike
    attack_generator.generate_variant() (which was purpose-built for an
    already-evasive attack and hardcodes organic-range claim timing and
    continuous engagement no matter what target is passed -- confirmed by
    running it: even at the most "suspicious" knob values, its rings never
    reach suspicion_score above 2/4, because fast-claim and dormancy can
    never trigger by construction), this generator's EVERY suspicion-relevant
    parameter is driven by one continuous `sophistication` scalar in [0, 1]:

      0.0 = naive, obviously fraudulent -- mirrors generate_data.py's own
            easy-mode gen_soft_ring(hard_mode=False): burst signup, fast
            claim (0.2-4h), tightly templated orders, goes dormant right
            after claiming.
      1.0 = fully evasive -- converges on attack_generator.generate_variant()'s
            already-proven organic-mimicking shape: spread signup, diverse
            orders, slow/organic claim timing, continuous engagement for
            months.

    This is what lets a single population actually start catchable and
    decay toward evasion, instead of starting at 0% recall with nowhere to
    decay from (the bug this replaced)."""
    random.seed(seed)
    np.random.seed(seed)
    s = max(0.0, min(1.0, sophistication))

    spread_days = 4.0 + s * (22.5 - 4.0)           # 4 (burst) -> 22.5 (past the 21-day organic threshold)
    order_cv = 0.05 + s * (0.30 - 0.05)            # 0.05 (templated) -> 0.30 (past the 0.28 diverse threshold)
    claim_hours_lo = 0.2 + s * (12.0 - 0.2)
    claim_hours_hi = 4.0 + s * (336.0 - 4.0)
    continues_engaging_prob = s                     # 0 = always goes dormant after claiming; 1 = never does

    accounts, sessions, referrals, instruments, orders = [], [], [], [], []
    uid_of = lambda i: f"U{tag}{i:03d}"
    code_of = lambda i: f"REF{tag}{i:03d}"
    start = TODAY - timedelta(days=random.uniform(200, 300))
    per_gap = spread_days / max(RING_SIZE - 1, 1)
    order_id = session_id = referral_id = 1
    prev_uid = None

    for i in range(RING_SIZE):
        uid = uid_of(i)
        signup = start + timedelta(days=i * per_gap + random.uniform(-0.3, 0.3))
        device, ip, pincode = _rand_device_id(), _rand_ip(), _rand_pincode()
        referred_by = prev_uid
        code = code_of(i - 1) if referred_by else ""

        accounts.append({
            "user_id": uid, "signup_date": signup.strftime("%Y-%m-%d"), "phone_number": _rand_phone(),
            "email": f"{tag.lower()}{i}@gmail.com", "device_fingerprint_id": device,
            "ip_address_at_signup": ip, "referral_code_used": code, "referred_by_user_id": referred_by or "",
            "kyc_status": random.choices(["verified", "pending"], weights=[0.8, 0.2])[0], "home_pincode": pincode,
        })
        sessions.append({"session_id": f"S{tag}{session_id:04d}", "user_id": uid, "device_fingerprint_id": device,
                         "ip_address": ip, "timestamp": signup.strftime("%Y-%m-%d %H:%M:%S"), "action_type": "signup"})
        session_id += 1

        if referred_by:
            claim_ts = signup + timedelta(hours=random.uniform(claim_hours_lo, claim_hours_hi))
            referrals.append({
                "referral_id": f"RF{tag}{referral_id:03d}", "referrer_user_id": referred_by,
                "referred_user_id": uid, "bonus_amount": round(random.uniform(50, 300), 2),
                "bonus_status": random.choices(["paid", "pending"], weights=[0.85, 0.15])[0],
                "claim_date": claim_ts.strftime("%Y-%m-%d"),
            })
            referral_id += 1
            sessions.append({"session_id": f"S{tag}{session_id:04d}", "user_id": uid, "device_fingerprint_id": device,
                             "ip_address": ip, "timestamp": claim_ts.strftime("%Y-%m-%d %H:%M:%S"), "action_type": "referral_claim"})
            session_id += 1

        mean_val = 650.0
        n_initial = random.randint(1, 2)
        ts = signup
        for _ in range(n_initial):
            ts = ts + timedelta(hours=random.uniform(1, 24))
            z = np.random.normal(0, 1)
            value = max(99, mean_val * (1 + order_cv * z))
            orders.append({"user_id": uid, "order_id": f"O{tag}{order_id:04d}", "order_value": round(value, 2),
                           "order_date": ts.strftime("%Y-%m-%d"), "delivery_pincode": pincode})
            order_id += 1
            sessions.append({"session_id": f"S{tag}{session_id:04d}", "user_id": uid, "device_fingerprint_id": device,
                             "ip_address": ip, "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"), "action_type": "order_placed"})
            session_id += 1

        if random.random() < continues_engaging_prob:
            n_orders = random.randint(3, 8)
            for _ in range(n_orders):
                ts = ts + timedelta(days=np.random.exponential(20) + 2)
                if ts > TODAY:
                    break
                z = np.random.normal(0, 1)
                value = max(99, mean_val * (1 + order_cv * z))
                orders.append({"user_id": uid, "order_id": f"O{tag}{order_id:04d}", "order_value": round(value, 2),
                               "order_date": ts.strftime("%Y-%m-%d"), "delivery_pincode": pincode})
                order_id += 1
                sessions.append({"session_id": f"S{tag}{session_id:04d}", "user_id": uid, "device_fingerprint_id": device,
                                 "ip_address": ip, "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"), "action_type": "order_placed"})
                session_id += 1
            n_logins = random.randint(4, 12)
            ts = signup
            for _ in range(n_logins):
                ts = ts + timedelta(days=np.random.exponential(12) + 1)
                if ts > TODAY:
                    break
                sessions.append({"session_id": f"S{tag}{session_id:04d}", "user_id": uid, "device_fingerprint_id": device,
                                 "ip_address": ip, "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"), "action_type": "login"})
                session_id += 1
        prev_uid = uid

    return {
        "attack_id": tag, "population": "no_shared_device", "sophistication": round(s, 3),
        "description": f"sophistication={s:.2f}: spread~{spread_days:.1f}d, order_cv~{order_cv:.2f}, "
                       f"claim {claim_hours_lo:.1f}-{claim_hours_hi:.1f}h, continues_engaging_prob={s:.2f}.",
        "accounts": accounts, "sessions": sessions, "referrals": referrals,
        "instruments": instruments, "orders": orders, "members": [uid_of(i) for i in range(RING_SIZE)],
    }


def build_no_device_population(period: int, n: int, seed_base: int, sophistication: float) -> list:
    rings = []
    for i in range(n):
        tag = f"P{period}ND{i:02d}"
        rings.append(build_naive_to_evasive_ring(tag, seed=seed_base + i, sophistication=sophistication))
    return rings


def build_shared_device_population(period: int, n: int, seed_base: int, knobs: dict) -> list:
    """Shared device -- concurrent_attack_stress_test.build_soft_masking_ring(),
    reused unchanged, just fed this period's knob state instead of its own
    defaults."""
    rings = []
    for i in range(n):
        tag = f"P{period}SD{i:02d}"
        margin_spread = attack_generator.ORGANIC_KNOBS["spread_out_days"]["margin"]
        margin_cv = attack_generator.ORGANIC_KNOBS["diverse_order_cv"]["margin"]
        margin_eng = attack_generator.ORGANIC_KNOBS["engaged_sessions"]["margin"]
        ring = build_soft_masking_ring(
            tag, seed=seed_base + i,
            span_days=knobs["spread_out_days"] + margin_spread,
            order_cv_target=knobs["diverse_order_cv"] + margin_cv,
            engagement_target=knobs["engaged_sessions"] + margin_eng,
        )
        ring["attack_id"], ring["population"] = tag, "shared_device"
        rings.append(ring)
    return rings


def _run_pipeline(raw_dir: Path):
    data = load_data(raw_dir=raw_dir, verbose=False)
    G = build_graph(data)
    H = hard_signal_subgraph(G)
    hard_clusters = stage2_hard_clusters(H)
    soft_clusters = stage3_soft_clusters(G)
    candidates = dedupe_candidates(hard_clusters, soft_clusters)
    device_by_user, instrument_by_user = build_lookups(data)
    flagged = []
    for members, stage in candidates:
        feats = compute_features(G, members, data, device_by_user, instrument_by_user)
        verdict = evaluate_cluster(feats)  # unmodified, zero overrides -- Stage 1-5 frozen, every period
        if verdict["flagged"]:
            flagged.append({"members": sorted(members), "detection_stage": stage})
    return flagged


def run():
    print(f"=== Time-drift simulation: {N_PERIODS} periods, {RINGS_PER_POPULATION} rings/population/period ===\n")

    # Fresh seed, registered before use.
    seed_manifest_path = Path(__file__).resolve().parents[1] / "data" / "adversarial_recommender" / "used_seeds.json"
    used = json.loads(seed_manifest_path.read_text())
    seed = MASTER_SEED
    while seed in used:
        seed += 1
    used.append(seed)
    seed_manifest_path.write_text(json.dumps(used))
    print(f"Fresh seed: {seed} (registered in used_seeds.json)\n")

    # Confounder baseline computed once -- background/confounders are the same
    # real frozen data every period, so the zero-attack baseline doesn't change.
    confounders = json.loads((GT_DIR / "confounders.json").read_text())
    baseline_ids = _flagged_confounder_ids(RAW_DIR, confounders)
    print(f"Confounder false-positive baseline (0 rings injected, computed once): "
          f"{sorted(baseline_ids)} ({len(baseline_ids)}/{len(confounders)})\n")

    soph_nd = 0.0  # no-shared-device population: 0.0 = naive, 1.0 = fully evasive
    soph_step = 1.0 / (N_PERIODS - 1)

    knobs_sd = {"spread_out_days": START_SPREAD_OUT_DAYS, "diverse_order_cv": START_DIVERSE_ORDER_CV,
                "engaged_sessions": START_ENGAGED_SESSIONS}
    step_spread = (PROD_SPREAD_OUT_DAYS - START_SPREAD_OUT_DAYS) / (N_PERIODS - 1)
    step_cv = (PROD_DIVERSE_ORDER_CV - START_DIVERSE_ORDER_CV) / (N_PERIODS - 1)
    step_eng = (PROD_ENGAGED_SESSIONS - START_ENGAGED_SESSIONS) / (N_PERIODS - 1)

    period_reports = []

    for period in range(1, N_PERIODS + 1):
        print(f"--- Period {period}/{N_PERIODS} ---")
        print(f"  no-shared-device sophistication: {soph_nd:.2f}")
        print(f"  shared-device knobs (pretend-thresholds): {knobs_sd}")

        rings_nd = build_no_device_population(period, RINGS_PER_POPULATION, seed_base=seed + period * 100, sophistication=soph_nd)
        rings_sd = build_shared_device_population(period, RINGS_PER_POPULATION, seed_base=seed + period * 200, knobs=knobs_sd)
        all_rings = rings_nd + rings_sd

        tmp = Path(tempfile.mkdtemp(prefix=f"sentinel_timedrift_p{period}_"))
        try:
            inject(RAW_DIR, tmp, all_rings)
            flagged = _run_pipeline(tmp)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

        n_caught_nd = sum(1 for r in rings_nd if best_match(set(r["members"]), flagged))
        n_caught_sd = sum(1 for r in rings_sd if best_match(set(r["members"]), flagged))
        recall_nd = n_caught_nd / len(rings_nd)
        recall_sd = n_caught_sd / len(rings_sd)

        conf_ids_this_period = {cid for cid, c in confounders.items() if best_match(set(c["members"]), flagged)}
        new_interference = sorted(conf_ids_this_period - baseline_ids)
        conf_fp_rate = len(conf_ids_this_period) / len(confounders)

        print(f"  no-shared-device recall:  {n_caught_nd}/{len(rings_nd)} ({recall_nd:.0%})")
        print(f"  shared-device recall:     {n_caught_sd}/{len(rings_sd)} ({recall_sd:.0%})")
        print(f"  confounder FP rate:       {len(conf_ids_this_period)}/{len(confounders)} ({conf_fp_rate:.1%})"
              f"{' -- NEW interference: ' + str(new_interference) if new_interference else ''}\n")

        period_reports.append({
            "period": period, "sophistication_no_shared_device": round(soph_nd, 3), "knobs_shared_device": dict(knobs_sd),
            "n_rings_no_shared_device": len(rings_nd), "n_caught_no_shared_device": n_caught_nd, "recall_no_shared_device": round(recall_nd, 4),
            "n_rings_shared_device": len(rings_sd), "n_caught_shared_device": n_caught_sd, "recall_shared_device": round(recall_sd, 4),
            "n_confounders": len(confounders), "n_confounder_fp": len(conf_ids_this_period),
            "confounder_fp_rate": round(conf_fp_rate, 4), "new_interference_confounders": new_interference,
        })

        # Adapt for next period ONLY the populations still being caught -- an
        # adversary with 0% recall this period has no measured reason to change
        # further; this is what makes the schedule outcome-conditioned, not fixed.
        if recall_nd > 0:
            soph_nd = min(soph_nd + soph_step, 1.0)
        if recall_sd > 0:
            knobs_sd["spread_out_days"] = min(knobs_sd["spread_out_days"] + step_spread, PROD_SPREAD_OUT_DAYS)
            knobs_sd["diverse_order_cv"] = min(knobs_sd["diverse_order_cv"] + step_cv, PROD_DIVERSE_ORDER_CV)
            knobs_sd["engaged_sessions"] = min(knobs_sd["engaged_sessions"] + step_eng, PROD_ENGAGED_SESSIONS)

    # --- honest trend read ---
    nd_recalls = [p["recall_no_shared_device"] for p in period_reports]
    sd_recalls = [p["recall_shared_device"] for p in period_reports]
    fp_rates = [p["confounder_fp_rate"] for p in period_reports]

    def trend(series):
        if series[-1] < series[0] - 1e-9:
            return "decaying"
        if all(abs(v - series[0]) < 1e-9 for v in series):
            return "flat"
        return "not monotonic / inconclusive at this period count"

    result = {
        "seed": seed, "n_periods": N_PERIODS, "rings_per_population_per_period": RINGS_PER_POPULATION,
        "periods": period_reports,
        "trend_no_shared_device": trend(nd_recalls), "trend_shared_device": trend(sd_recalls),
        "trend_confounder_fp_rate": trend(fp_rates),
    }

    print("=== Per-period summary (raw, never blended across periods) ===")
    print(f"{'Period':<8}{'ND recall':<14}{'SD recall':<14}{'Confounder FP':<16}")
    for p in period_reports:
        print(f"{p['period']:<8}{p['recall_no_shared_device']:<14.0%}{p['recall_shared_device']:<14.0%}"
              f"{p['confounder_fp_rate']:<16.1%}")
    print(f"\nTrend, no-shared-device recall:  {result['trend_no_shared_device']}")
    print(f"Trend, shared-device recall:     {result['trend_shared_device']}")
    print(f"Trend, confounder FP rate:       {result['trend_confounder_fp_rate']}")

    out_path = Path(__file__).resolve().parents[1] / "data" / "processed" / "time_drift_simulation.json"
    out_path.write_text(json.dumps(result, indent=2))
    print(f"\nWritten -> {out_path}")
    return result


if __name__ == "__main__":
    run()
