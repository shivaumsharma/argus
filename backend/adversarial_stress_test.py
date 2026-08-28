"""
Adversarial stress test -- finds where detection actually breaks, on purpose.

Every planted ring so far shares *some* hard-to-fake signal: a device, an
instrument, a tight signup burst, templated order values. This script builds
one additional ring engineered specifically to avoid all of that: no shared
device, no shared instrument, no shared IP subnet, referral claims spread
over days instead of hours, order values with organic-looking variance, and
genuine ongoing engagement instead of going dormant after the claim. The
only thing connecting these accounts is a referral chain -- exactly the kind
of link an organic "I told my friend" chain also produces.

This is not part of the standard eval (it never touches the tuned dataset or
its ground truth) -- it's injected into a disposable copy of the real
dataset, run through the unmodified Stages 1-5, and the result is reported
honestly, whichever way it comes out. See docs/ARCHITECTURE.md's Known
Limitations section for how this is used.

Run: python -m backend.adversarial_stress_test
"""

import random
import shutil
import string
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from .pipeline.clustering import dedupe_candidates, stage2_hard_clusters, stage3_soft_clusters
from .pipeline.confounder_filter import evaluate_cluster
from .pipeline.data_io import RAW_DIR, load_data
from .pipeline.features import build_lookups, compute_features
from .pipeline.graph_build import build_graph, hard_signal_subgraph

random.seed(7)
np.random.seed(7)

RING_SIZE = 8
TODAY = datetime(2026, 8, 28)


def rand_phone():
    return "+91" + str(random.choice([6, 7, 8, 9])) + "".join(random.choices(string.digits, k=9))


def rand_pincode():
    return str(random.randint(1, 8)) + "".join(random.choices(string.digits, k=5))


def rand_device_id():
    return "dfp_" + "".join(random.choices("0123456789abcdef", k=16))


def rand_instrument_hash():
    return "upi_" + "".join(random.choices(string.ascii_lowercase + string.digits, k=10)) + "@" + random.choice(
        ["okhdfcbank", "oksbi", "okicici", "okaxis"]
    )


def rand_ip():
    return f"{random.randint(1,223)}.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(2,254)}"


def build_adversarial_ring():
    """A referral chain with every avoidable tell removed. Each member gets its
    own device, own instrument, own IP subnet -- the only edge Stage 1 can find
    at all is the referral link itself, and even that is timed and spread to
    look exactly like an organic word-of-mouth chain."""
    accounts, sessions, referrals, instruments, orders = [], [], [], [], []
    uid_of = lambda i: f"UADV{i:03d}"
    code_of = lambda i: f"REFADV{i:03d}"

    start = TODAY - timedelta(days=random.uniform(200, 300))
    prev_uid = None
    order_id_counter = 1
    session_id_counter = 1
    referral_id_counter = 1

    for i in range(RING_SIZE):
        uid = uid_of(i)
        # organic-looking spread: days to weeks between each new signup, not hours
        signup = start + timedelta(days=i * random.uniform(3, 14) + random.uniform(-2, 2))
        device = rand_device_id()
        ip = rand_ip()
        instrument = rand_instrument_hash()
        pincode = rand_pincode()

        referred_by = prev_uid
        referral_code_used = code_of(i - 1) if referred_by else ""

        accounts.append({
            "user_id": uid, "signup_date": signup.strftime("%Y-%m-%d"), "phone_number": rand_phone(),
            "email": f"adv{i}@gmail.com", "device_fingerprint_id": device, "ip_address_at_signup": ip,
            "referral_code_used": referral_code_used, "referred_by_user_id": referred_by or "",
            "kyc_status": random.choices(["verified", "pending"], weights=[0.8, 0.2])[0], "home_pincode": pincode,
        })
        instruments.append({"user_id": uid, "instrument_hash": instrument, "instrument_first_seen_date": signup.strftime("%Y-%m-%d")})
        sessions.append({"session_id": f"SADV{session_id_counter:04d}", "user_id": uid, "device_fingerprint_id": device,
                          "ip_address": ip, "timestamp": signup.strftime("%Y-%m-%d %H:%M:%S"), "action_type": "signup"})
        session_id_counter += 1

        if referred_by:
            # organic claim timing: half a day to two weeks, not "within hours"
            claim_ts = signup + timedelta(days=random.uniform(0.5, 14))
            referrals.append({
                "referral_id": f"RFADV{referral_id_counter:03d}", "referrer_user_id": referred_by,
                "referred_user_id": uid, "bonus_amount": round(random.uniform(50, 300), 2),
                "bonus_status": random.choices(["paid", "pending"], weights=[0.85, 0.15])[0],
                "claim_date": claim_ts.strftime("%Y-%m-%d"),
            })
            referral_id_counter += 1
            sessions.append({"session_id": f"SADV{session_id_counter:04d}", "user_id": uid, "device_fingerprint_id": device,
                              "ip_address": ip, "timestamp": claim_ts.strftime("%Y-%m-%d %H:%M:%S"), "action_type": "referral_claim"})
            session_id_counter += 1

        # genuine ongoing engagement -- organic order-value variance, spread over months,
        # continuing well past any claim (no claim-then-dormant pattern)
        n_orders = random.randint(3, 9)
        ts = signup
        for _ in range(n_orders):
            ts = ts + timedelta(days=np.random.exponential(20) + 2)
            if ts > TODAY:
                break
            value = max(99, np.random.normal(650, 350))
            orders.append({"user_id": uid, "order_id": f"OADV{order_id_counter:04d}", "order_value": round(value, 2),
                            "order_date": ts.strftime("%Y-%m-%d"), "delivery_pincode": pincode})
            order_id_counter += 1
            sessions.append({"session_id": f"SADV{session_id_counter:04d}", "user_id": uid, "device_fingerprint_id": device,
                              "ip_address": ip, "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"), "action_type": "order_placed"})
            session_id_counter += 1

        n_logins = random.randint(4, 14)
        ts = signup
        for _ in range(n_logins):
            ts = ts + timedelta(days=np.random.exponential(15) + 1)
            if ts > TODAY:
                break
            sessions.append({"session_id": f"SADV{session_id_counter:04d}", "user_id": uid, "device_fingerprint_id": device,
                              "ip_address": ip, "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"), "action_type": "login"})
            session_id_counter += 1

        prev_uid = uid

    return accounts, sessions, referrals, instruments, orders, [uid_of(i) for i in range(RING_SIZE)]


def inject(src_dir: Path, dst_dir: Path):
    dst_dir.mkdir(parents=True, exist_ok=True)
    accounts, sessions, referrals, instruments, orders, ring_uids = build_adversarial_ring()

    for name, new_rows in [
        ("accounts.csv", accounts), ("sessions.csv", sessions), ("referrals.csv", referrals),
        ("payment_instruments.csv", instruments), ("orders.csv", orders),
    ]:
        existing = pd.read_csv(src_dir / name, dtype=str)
        combined = pd.concat([existing, pd.DataFrame(new_rows).astype(str)], ignore_index=True)
        combined.to_csv(dst_dir / name, index=False)

    return ring_uids


def run():
    tmp = Path(tempfile.mkdtemp(prefix="sentinel_adversarial_"))
    try:
        print(f"Injecting a {RING_SIZE}-account adversarial ring into a disposable copy of the dataset...")
        print("  Design: no shared device, no shared instrument, no shared IP subnet.")
        print("  Referral chain claims spread 0.5-14 days after signup (not hours).")
        print("  Order values organic-variance (mean 650, std 350), not templated.")
        print("  Ongoing engagement continues for months -- no claim-then-dormant pattern.")
        ring_uids = inject(RAW_DIR, tmp)
        print(f"  Injected accounts: {ring_uids}")

        data = load_data(raw_dir=tmp)
        G = build_graph(data)
        H = hard_signal_subgraph(G)

        ring_set = set(ring_uids)
        sub = G.subgraph(ring_uids)
        print(f"\nGraph edges among the injected ring: {sub.number_of_edges()} "
              f"(signals: {sorted(set().union(*[d['signals'] for _, _, d in sub.edges(data=True)])) if sub.number_of_edges() else 'none'})")

        hard_clusters = stage2_hard_clusters(H)
        soft_clusters = stage3_soft_clusters(G)
        candidates = dedupe_candidates(hard_clusters, soft_clusters)
        device_by_user, instrument_by_user = build_lookups(data)

        matches = []
        for members, stage in candidates:
            overlap = ring_set & members
            if len(overlap) >= 2:
                feats = compute_features(G, members, data, device_by_user, instrument_by_user)
                verdict = evaluate_cluster(feats)
                matches.append((stage, members, overlap, feats, verdict))

        print(f"\nCandidate clusters overlapping the injected ring: {len(matches)}")
        if not matches:
            print("RESULT: the ring never became a candidate cluster at all -- Stage 2/3 never grouped it.")
            print("This is the honest limitation: a ring connected by nothing but a plausible-looking")
            print("referral chain, with organic timing and spending, is structurally indistinguishable")
            print("from a real word-of-mouth chain. There is no edge pattern here for a graph-clustering")
            print("approach to catch, by construction.")
        else:
            for stage, members, overlap, feats, verdict in matches:
                print(f"\n  Stage: {stage} signal | cluster size {len(members)} | ring members captured: {len(overlap)}/{RING_SIZE}")
                print(f"  Flagged: {verdict['flagged']} | reason: {verdict['reason']}")
                print(f"  Features: signup_span_days={feats['signup_span_days']}, order_value_cv={feats['order_value_cv']}, "
                      f"post_signup_engagement={feats['post_signup_engagement']}")
            if not any(v["flagged"] for _, _, _, _, v in matches):
                print("\nRESULT: the ring was surfaced as a candidate cluster but Stage 5 correctly-per-its-own-logic")
                print("read the spread-out timing and organic engagement as legitimate and did NOT flag it.")
                print("This is the honest limitation: an adversary patient enough to mimic organic behavior")
                print("defeats the confounder filter by design -- Stage 5's whole job is to trust exactly")
                print("the signals this ring was built to fake.")
            else:
                print("\nRESULT: caught anyway -- the referral-chain topology alone was enough for Louvain to")
                print("separate it and for Stage 5's suspicion score to still clear the bar.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    run()
