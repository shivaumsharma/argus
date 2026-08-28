"""
Live injection -- drop a brand-new synthetic ring into the actual dataset
during a demo and watch it get flagged in real time, instead of asking an
audience to trust a pre-baked result.

Unlike adversarial_stress_test.py and demo_failure_injection.py (which run
against a disposable copy of the data), this module appends real rows to
data/raw/*.csv and reruns the real pipeline -- the injected ring becomes a
genuine part of the live dataset, exactly as if it had been in the original
generation.

Run standalone: python -m backend.live_injection [hard|soft] [size]
"""

import random
import string
import sys
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from .llm_investigate import investigate_single
from .pipeline.data_io import RAW_DIR
from .pipeline.run_pipeline import run as run_pipeline

TODAY = datetime(2026, 8, 28)


def _rand_phone():
    return "+91" + str(random.choice([6, 7, 8, 9])) + "".join(random.choices(string.digits, k=9))


def _rand_pincode():
    return str(random.randint(1, 8)) + "".join(random.choices(string.digits, k=5))


def _rand_device_id():
    return "dfp_" + "".join(random.choices("0123456789abcdef", k=16))


def _rand_instrument_hash():
    return "upi_" + "".join(random.choices(string.ascii_lowercase + string.digits, k=10)) + "@" + random.choice(
        ["okhdfcbank", "oksbi", "okicici", "okaxis", "ybl"]
    )


def _rand_subnet():
    return f"{random.randint(1, 223)}.{random.randint(0, 255)}.{random.randint(0, 255)}"


def _next_user_index() -> int:
    accounts = pd.read_csv(RAW_DIR / "accounts.csv", dtype=str, usecols=["user_id"])
    nums = accounts.user_id.str.extract(r"U0*(\d+)")[0].dropna().astype(int)
    return int(nums.max()) + 1 if len(nums) else 1


def generate_new_ring(kind: str, size: int, start_index: int):
    """Builds one brand-new ring (hard-signal or soft-signal) with the same behavioral
    signature as the planted rings in generate_data.py, anchored to "just now" so it reads
    as a live event rather than backdated synthetic history."""
    accounts, sessions, referrals, instruments, orders = [], [], [], [], []
    uid_of = lambda i: f"U{start_index + i:06d}"
    ref_code_of = lambda uid: "REF" + uid[1:]

    subnet = _rand_subnet()
    burst_start = TODAY - timedelta(hours=random.uniform(1, 36))  # "just happened"
    order_template = round(random.uniform(150, 2500), 2)

    shared_device = _rand_device_id() if kind == "hard" else None
    shared_instrument = _rand_instrument_hash() if (kind == "hard" and random.random() < 0.6) else None

    members = []
    prev_uid = None
    hub_uid = None
    for i in range(size):
        uid = uid_of(i)
        if kind == "hard":
            signup = burst_start + timedelta(hours=random.uniform(0, 60))
            device = shared_device or _rand_device_id()
            instrument = shared_instrument
        else:
            signup = burst_start + timedelta(hours=i * random.uniform(0.5, 4))
            device = _rand_device_id()
            instrument = _rand_instrument_hash()
        ip = f"{subnet}.{random.randint(2, 254)}"
        pincode = _rand_pincode()

        referred_by = (hub_uid if kind == "hard" else prev_uid) if (i > 0 and random.random() < 0.85) else None
        accounts.append({
            "user_id": uid, "signup_date": signup.strftime("%Y-%m-%d"), "phone_number": _rand_phone(),
            "email": f"user{uid[1:]}@gmail.com", "device_fingerprint_id": device, "ip_address_at_signup": ip,
            "referral_code_used": ref_code_of(referred_by) if referred_by else "",
            "referred_by_user_id": referred_by or "", "kyc_status": "pending", "home_pincode": pincode,
        })
        instruments.append({"user_id": uid, "instrument_hash": instrument or _rand_instrument_hash(),
                             "instrument_first_seen_date": signup.strftime("%Y-%m-%d")})
        sessions.append({"session_id": f"SINJ{start_index}{i:03d}0", "user_id": uid, "device_fingerprint_id": device,
                          "ip_address": ip, "timestamp": signup.strftime("%Y-%m-%d %H:%M:%S"), "action_type": "signup"})
        members.append(uid)
        if hub_uid is None:
            hub_uid = uid

        if referred_by:
            claim_ts = signup + timedelta(hours=random.uniform(0.1, 6))
            referrals.append({
                "referral_id": f"RINJ{start_index}{i:03d}", "referrer_user_id": referred_by, "referred_user_id": uid,
                "bonus_amount": round(random.uniform(50, 300), 2), "bonus_status": "paid",
                "claim_date": claim_ts.strftime("%Y-%m-%d"),
            })
            sessions.append({"session_id": f"SINJ{start_index}{i:03d}1", "user_id": uid, "device_fingerprint_id": device,
                              "ip_address": ip, "timestamp": claim_ts.strftime("%Y-%m-%d %H:%M:%S"), "action_type": "referral_claim"})

        ts = signup
        for j in range(random.randint(1, 2)):
            ts = ts + timedelta(hours=random.uniform(1, 20))
            value = order_template + random.uniform(-15, 15)
            orders.append({"user_id": uid, "order_id": f"OINJ{start_index}{i:03d}{j}", "order_value": round(max(value, 49), 2),
                            "order_date": ts.strftime("%Y-%m-%d"), "delivery_pincode": pincode})
            sessions.append({"session_id": f"SINJ{start_index}{i:03d}{2+j}", "user_id": uid, "device_fingerprint_id": device,
                              "ip_address": ip, "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"), "action_type": "order_placed"})
        prev_uid = uid

    return accounts, sessions, referrals, instruments, orders, members


def _append(name: str, rows: list):
    if not rows:
        return
    existing = pd.read_csv(RAW_DIR / name, dtype=str)
    combined = pd.concat([existing, pd.DataFrame(rows).astype(str)], ignore_index=True)
    combined.to_csv(RAW_DIR / name, index=False)


def inject_and_detect(kind: str = "hard", size: int = 10, verbose: bool = True):
    """Appends a new ring to the live dataset, reruns the full deterministic pipeline, finds
    which candidate cluster the new ring landed in, and investigates just that one cluster."""
    start_index = _next_user_index()
    accounts, sessions, referrals, instruments, orders, members = generate_new_ring(kind, size, start_index)
    if verbose:
        print(f"Injecting a {size}-account {kind}-signal ring ({members[0]}..{members[-1]})...")

    _append("accounts.csv", accounts)
    _append("sessions.csv", sessions)
    _append("referrals.csv", referrals)
    _append("payment_instruments.csv", instruments)
    _append("orders.csv", orders)

    results = run_pipeline(verbose=verbose)
    member_set = set(members)
    matched = None
    for c in results:
        overlap = member_set & set(c["members"])
        if len(overlap) >= max(2, size // 2):
            matched = c
            break

    outcome = {"members": members, "kind": kind, "size": size, "matched_cluster": matched}
    if matched is None:
        outcome["status"] = "not_clustered"
        if verbose:
            print("The injected ring did not form a candidate cluster.")
        return outcome

    if not matched["flagged"]:
        outcome["status"] = "clustered_not_flagged"
        outcome["filter_reason"] = matched["filter_reason"]
        if verbose:
            print(f"Clustered as {matched['cluster_id']} but NOT flagged: {matched['filter_reason']}")
        return outcome

    case = investigate_single(matched, verbose=verbose)
    outcome["status"] = "flagged"
    outcome["case"] = case
    if verbose:
        print(f"Flagged as {matched['cluster_id']} -> {case['recommended_action']} (confidence {case['confidence']:.2f})")
    return outcome


if __name__ == "__main__":
    kind_arg = sys.argv[1] if len(sys.argv) > 1 else "hard"
    size_arg = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    inject_and_detect(kind_arg, size_arg)
