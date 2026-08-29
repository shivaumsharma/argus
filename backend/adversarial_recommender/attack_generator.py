"""
Stage 1 -- Attack Generator.

Round 1 reuses backend.adversarial_stress_test's existing, already-validated
evasion ring UNCHANGED (build_adversarial_ring()) -- it already demonstrates
a real gap (Stage 3 clusters it, Stage 5 doesn't flag it), so this doesn't
rebuild it from scratch.

Round 2+ generate a new variant informed by what got through in the
previous round, following the round-over-round methodology of "A
multi-rounded adversarial scenario for graph-based promo fraud detection"
(Springer, Social Network Analysis and Mining, published online Dec 28,
2025, DOI 10.1007/s13278-025-01566-0 -- cited by venue/date/DOI, verified
directly before writing this; author list not independently confirmed, so
not asserted here). That paper's core idea is a "generator function" that
governs how the adversarial graph evolves between rounds; here, the
generator function is: take the parameter the PREVIOUS round's
recommendation proposed changing, and dial this round's ring to sit just
barely on the organic side of that NEW proposed threshold -- testing
whether an adversary that adapts to the last fix still gets through, which
is the whole point of a multi-round scenario instead of a single static test.

Every attack ring here is injected into a disposable copy of the dataset
and never touches data/raw/, data/frozen_snapshot/, or data/app.db directly
-- see governance.py for the one path that's allowed to touch real files,
and even that only writes to its own disposable directories.
"""

import random
import string
from datetime import datetime, timedelta

import numpy as np

from ..adversarial_stress_test import build_adversarial_ring as _round1_ring
from ..pipeline.confounder_filter import TUNABLE_PARAMETERS

TODAY = datetime(2026, 8, 28)
RING_SIZE = 8

# Which behavioral knob each targetable gap_parameter maps to, and how to compute
# a ring-generation target value that sits `margin` above/below a given threshold
# value on the organic side (i.e., an adversary who has learned roughly where the
# line is and aims just past it).
ORGANIC_KNOBS = {
    "spread_out_days": {"direction": "above", "margin": 1.5},
    "diverse_order_cv": {"direction": "above", "margin": 0.02},
    "engaged_sessions": {"direction": "above", "margin": 0.3},
}


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


def generate_round1():
    """Reuses the existing, already-validated evasion ring unchanged."""
    accounts, sessions, referrals, instruments, orders, ring_uids = _round1_ring()
    return {
        "attack_id": "ROUND1_BASE",
        "description": "Referral-chain-only ring, no shared device/instrument/subnet, organic timing/CV/"
                       "engagement (backend/adversarial_stress_test.py, reused unchanged).",
        "accounts": accounts, "sessions": sessions, "referrals": referrals,
        "instruments": instruments, "orders": orders, "members": ring_uids,
    }


def generate_variant(round_number: int, seed: int, targets: dict = None):
    """Round 2+. `targets` maps gap_parameter -> threshold_value for one or more
    of the three organic knobs (from the previous round's characterized gap(s)
    and drafted recommendation(s)): each targeted knob is dialed to sit just
    barely past its NEW proposed threshold, on the organic side -- an
    adversary adapting to the last round's fix. Passing all three at once
    probes the tightest simultaneous evasion possible. Any knob not targeted
    falls back to the same random ranges as round 1."""
    random.seed(seed)
    np.random.seed(seed)
    targets = targets or {}

    spread_days_target = 8 * (RING_SIZE - 1)  # default matches round 1's random.uniform(3,14) scale roughly
    order_cv_target = 0.48  # round 1's rough empirical CV
    engagement_target = 14.75  # round 1's rough empirical post-signup engagement

    for target_param, threshold_value in targets.items():
        knob = ORGANIC_KNOBS.get(target_param)
        if knob is None or threshold_value is None:
            continue
        target = threshold_value + knob["margin"]
        if target_param == "spread_out_days":
            spread_days_target = target
        elif target_param == "diverse_order_cv":
            order_cv_target = target
        elif target_param == "engaged_sessions":
            engagement_target = target

    accounts, sessions, referrals, instruments, orders = [], [], [], [], []
    uid_of = lambda i: f"UADVR{round_number}{i:03d}"
    code_of = lambda i: f"REFADVR{round_number}{i:03d}"

    start = TODAY - timedelta(days=random.uniform(200, 300))
    prev_uid = None
    order_id_counter = session_id_counter = referral_id_counter = 1
    per_gap = spread_days_target / max(RING_SIZE - 1, 1)

    for i in range(RING_SIZE):
        uid = uid_of(i)
        signup = start + timedelta(days=i * per_gap + random.uniform(-0.5, 0.5))
        device = _rand_device_id()
        ip = _rand_ip()
        instrument = _rand_instrument_hash()
        pincode = _rand_pincode()
        referred_by = prev_uid
        referral_code_used = code_of(i - 1) if referred_by else ""

        accounts.append({
            "user_id": uid, "signup_date": signup.strftime("%Y-%m-%d"), "phone_number": _rand_phone(),
            "email": f"advr{round_number}_{i}@gmail.com", "device_fingerprint_id": device,
            "ip_address_at_signup": ip, "referral_code_used": referral_code_used,
            "referred_by_user_id": referred_by or "",
            "kyc_status": random.choices(["verified", "pending"], weights=[0.8, 0.2])[0], "home_pincode": pincode,
        })
        instruments.append({"user_id": uid, "instrument_hash": instrument,
                            "instrument_first_seen_date": signup.strftime("%Y-%m-%d")})
        sessions.append({"session_id": f"SADVR{round_number}{session_id_counter:04d}", "user_id": uid,
                         "device_fingerprint_id": device, "ip_address": ip,
                         "timestamp": signup.strftime("%Y-%m-%d %H:%M:%S"), "action_type": "signup"})
        session_id_counter += 1

        if referred_by:
            claim_ts = signup + timedelta(days=random.uniform(0.5, 14))
            referrals.append({
                "referral_id": f"RFADVR{round_number}{referral_id_counter:03d}", "referrer_user_id": referred_by,
                "referred_user_id": uid, "bonus_amount": round(random.uniform(50, 300), 2),
                "bonus_status": random.choices(["paid", "pending"], weights=[0.85, 0.15])[0],
                "claim_date": claim_ts.strftime("%Y-%m-%d"),
            })
            referral_id_counter += 1
            sessions.append({"session_id": f"SADVR{round_number}{session_id_counter:04d}", "user_id": uid,
                             "device_fingerprint_id": device, "ip_address": ip,
                             "timestamp": claim_ts.strftime("%Y-%m-%d %H:%M:%S"), "action_type": "referral_claim"})
            session_id_counter += 1

        n_orders = random.randint(4, 9)
        mean_val = 650.0
        ts = signup
        for _ in range(n_orders):
            ts = ts + timedelta(days=np.random.exponential(20) + 2)
            if ts > TODAY:
                break
            z = np.random.normal(0, 1)
            value = max(99, mean_val * (1 + order_cv_target * z))
            orders.append({"user_id": uid, "order_id": f"OADVR{round_number}{order_id_counter:04d}",
                           "order_value": round(value, 2), "order_date": ts.strftime("%Y-%m-%d"),
                           "delivery_pincode": pincode})
            order_id_counter += 1
            sessions.append({"session_id": f"SADVR{round_number}{session_id_counter:04d}", "user_id": uid,
                             "device_fingerprint_id": device, "ip_address": ip,
                             "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"), "action_type": "order_placed"})
            session_id_counter += 1

        n_logins = max(1, round(engagement_target * random.uniform(0.7, 1.3)))
        ts = signup
        for _ in range(n_logins):
            ts = ts + timedelta(days=np.random.exponential(15) + 1)
            if ts > TODAY:
                break
            sessions.append({"session_id": f"SADVR{round_number}{session_id_counter:04d}", "user_id": uid,
                             "device_fingerprint_id": device, "ip_address": ip,
                             "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"), "action_type": "login"})
            session_id_counter += 1

        prev_uid = uid

    members = [uid_of(i) for i in range(RING_SIZE)]
    if targets:
        target_desc = ", ".join(
            f"{p} just past {v + ORGANIC_KNOBS[p]['margin']:.3f} (round-{round_number-1} proposed threshold {v:.3f})"
            for p, v in targets.items() if p in ORGANIC_KNOBS
        )
    else:
        target_desc = "baseline organic ranges (no prior gap to adapt to)"
    desc = f"Round {round_number} variant: same referral-chain-only shape as round 1, targeting {target_desc}."
    tag = "_".join(sorted(targets.keys())) if targets else "BASE"
    return {
        "attack_id": f"ROUND{round_number}_{tag}",
        "description": desc,
        "accounts": accounts, "sessions": sessions, "referrals": referrals,
        "instruments": instruments, "orders": orders, "members": members,
    }
