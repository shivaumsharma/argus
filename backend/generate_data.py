"""
Synthetic data generator for the Promo/Referral Abuse-Ring Sentinel.

Produces:
  data/raw/accounts.csv
  data/raw/sessions.csv
  data/raw/referrals.csv
  data/raw/payment_instruments.csv
  data/raw/orders.csv

  data/ground_truth/rings.json        -- planted fraud rings (hard + soft signal)
  data/ground_truth/confounders.json  -- planted legitimate lookalike clusters
  data/ground_truth/labels.csv        -- user_id -> cluster_type / cluster_id (flat, for eval)

Ground truth is NEVER read by the detection pipeline -- it exists solely for
Day 4's evaluation harness (precision/recall against rings, false-positive
rate against confounders).
"""

import argparse
import json
import random
import string
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

# A fresh seed, never used during threshold tuning or debugging this session --
# SEED=42 was used throughout development (Days 1-7, the 40/40/40 scale-up, and
# every debugging iteration), so a held-out claim on that data is weaker than it
# looks even without explicit retuning. This one has not been looked at before
# Stage 5's thresholds and Stage 3's Louvain resolution were already frozen.
SEED = 20260828
random.seed(SEED)
np.random.seed(SEED)

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
GT_DIR = ROOT / "data" / "ground_truth"
RAW_DIR.mkdir(parents=True, exist_ok=True)
GT_DIR.mkdir(parents=True, exist_ok=True)

TODAY = datetime(2026, 8, 27)
START = datetime(2025, 9, 1)
SPAN_DAYS = (TODAY - START).days

TARGET_TOTAL_ACCOUNTS = 7500

EMAIL_DOMAINS = ["gmail.com", "yahoo.com", "outlook.com", "rediffmail.com", "hotmail.com"]

# --------------------------------------------------------------------------
# Real-statistics grounding for device-sharing probabilities. NOT applied to
# the frozen SEED=20260828 dataset by default -- USE_GROUNDED_DEVICE_SHARING
# defaults to False specifically so `python -m backend.generate_data` keeps
# reproducing the exact frozen dataset byte-for-byte (verified). Flip it and
# use a genuinely fresh, never-used seed for the next full freeze-and
# -reevaluate cycle; per this project's eval integrity protocol, that's the
# only way these values are allowed to affect any reported headline number.
#
# Real sources, fetched and verified via web search before use, not assumed:
#   - IAMAI-KANTAR "Internet in India Report 2025" (Jan 2025, ~100,000-consumer
#     survey across 400+ towns and 1,000+ villages): 18% of Indian internet
#     users go online through someone else's mobile device, ~80% of them rural.
#   - NSO Comprehensive Annual Modular Survey (CAMS), Round 79, 2022-23: "a
#     majority of Indian phone users share their phone with a family member,
#     and are not exclusive users of the device."
#
# Current frozen values were invented, not grounded: household=0.5 (close to
# defensible given the NSO "majority" finding, left as-is), hostel=0.0 (the
# function's own docstring already claims "rarely shared device" but the code
# never implemented any sharing at all -- a real gap, not just an arbitrary
# choice), background=0.0 (ordinary accounts never share a device at all,
# which is the least realistic of the three -- real device-sharing is not
# confined to planted confounder archetypes). Raising these makes the
# detection problem *more* honest, not easier, per the same logic already
# applied to backend/cod_collusion/'s COD refusal rate.
USE_GROUNDED_DEVICE_SHARING = False
GROUNDED_HOUSEHOLD_DEVICE_SHARE_PROB = 0.55   # NSO CAMS "majority" finding; modest rise from the current 0.5
GROUNDED_HOSTEL_DEVICE_SHARE_PROB = 0.15      # roughly the 18% IAMAI-KANTAR national average
# GROUNDED_BACKGROUND_DEVICE_SHARE_PROB is declared but deliberately NOT wired into
# gen_background() yet: household/hostel archetypes already generate members in a
# shared group, so adding a shared-device draw is a one-line probability change.
# Background accounts are generated independently, one at a time, with no grouping
# structure at all -- giving them realistic device-sharing means pairing a fraction
# of otherwise-unrelated background accounts into small device-sharing clusters,
# which is a real structural change (new pairing logic, not a probability tweak)
# and a larger blast radius than the household/hostel fix. Flagged here as a
# recommended next step, not rushed in to check a box.
GROUNDED_BACKGROUND_DEVICE_SHARE_PROB = 0.18  # the 18% IAMAI-KANTAR figure, for whenever that structural change is made

# --------------------------------------------------------------------------
# Global state
# --------------------------------------------------------------------------

counters = {"user": 0, "session": 0, "referral": 0, "order": 0}
accounts, sessions, referrals, payment_instruments, orders = [], [], [], [], []
accounts_by_uid = {}
referral_codes = {}  # uid -> own referral code


def next_id(prefix, key, width=6):
    counters[key] += 1
    return f"{prefix}{counters[key]:0{width}d}"


# --------------------------------------------------------------------------
# Random field helpers
# --------------------------------------------------------------------------

def rand_phone():
    return "+91" + str(random.choice([6, 7, 8, 9])) + "".join(random.choices(string.digits, k=9))


def rand_pincode():
    return str(random.randint(1, 8)) + "".join(random.choices(string.digits, k=5))


def rand_device_id():
    return "dfp_" + "".join(random.choices("0123456789abcdef", k=16))


def rand_instrument_hash():
    if random.random() < 0.6:
        handle = "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
        bank = random.choice(["okhdfcbank", "oksbi", "okicici", "okaxis", "ybl", "paytm"])
        return f"upi_{handle}@{bank}"
    return "card_" + "".join(random.choices(string.digits, k=4)) + "_" + "".join(
        random.choices("0123456789abcdef", k=10)
    )


def rand_subnet():
    return f"{random.randint(1, 223)}.{random.randint(0, 255)}.{random.randint(0, 255)}"


def rand_ip(subnet=None):
    subnet = subnet or rand_subnet()
    return f"{subnet}.{random.randint(2, 254)}"


# --------------------------------------------------------------------------
# Row builders
# --------------------------------------------------------------------------

def session_row(uid, device_id, ip, ts, action_type):
    return {
        "session_id": next_id("S", "session"),
        "user_id": uid,
        "device_fingerprint_id": device_id,
        "ip_address": ip,
        "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
        "action_type": action_type,
    }


def order_row(uid, ts, value, pincode):
    # `order_value` here is a raw GMV figure -- this dataset does not model a
    # settlement/fee layer on top of it. If that layer is ever added: credit-card
    # MDR in India typically runs 1.5-2.5% (~2% is a defensible midpoint --
    # Razorpay's own blog, cross-checked against getswipe.in/justt.ai/au.bank.in),
    # plus 18% GST charged on the MDR/platform fee itself, not on the transaction
    # value (Razorpay's own blog; standard GST rate on services). Both verified via
    # web search before citing here, not assumed. Recorded as a documented gap,
    # not implemented speculatively -- nothing downstream (ring detection, eval,
    # cost-threshold sensitivity) currently needs settlement-adjusted amounts,
    # and adding one would be a generator change requiring its own freeze cycle.
    return {
        "user_id": uid,
        "order_id": next_id("O", "order"),
        "order_value": round(max(value, 49.0), 2),
        "order_date": ts.strftime("%Y-%m-%d"),
        "delivery_pincode": pincode,
    }


def make_account(signup_date, device_id=None, ip=None, instrument_hash=None,
                  referred_by=None, referral_code_used=None, pincode=None):
    uid = next_id("U", "user")
    device_id = device_id or rand_device_id()
    ip = ip or rand_ip()
    pincode = pincode or rand_pincode()
    kyc_status = random.choices(["verified", "pending", "unverified"], weights=[0.75, 0.15, 0.10])[0]

    account = {
        "user_id": uid,
        "signup_date": signup_date.strftime("%Y-%m-%d"),
        "phone_number": rand_phone(),
        "email": f"user{uid[1:]}@{random.choice(EMAIL_DOMAINS)}",
        "device_fingerprint_id": device_id,
        "ip_address_at_signup": ip,
        "referral_code_used": referral_code_used or "",
        "referred_by_user_id": referred_by or "",
        "kyc_status": kyc_status,
        "home_pincode": pincode,
    }
    accounts.append(account)
    accounts_by_uid[uid] = account
    referral_codes[uid] = "REF" + uid[1:]

    instrument_hash = instrument_hash or rand_instrument_hash()
    payment_instruments.append({
        "user_id": uid,
        "instrument_hash": instrument_hash,
        "instrument_first_seen_date": signup_date.strftime("%Y-%m-%d"),
    })

    sessions.append(session_row(uid, device_id, ip, signup_date, "signup"))
    return account


def add_referral(referrer_uid, referred_uid, claim_ts, status_weights=(0.8, 0.15, 0.05)):
    referrals.append({
        "referral_id": next_id("RF", "referral"),
        "referrer_user_id": referrer_uid,
        "referred_user_id": referred_uid,
        "bonus_amount": round(random.uniform(50, 300), 2),
        "bonus_status": random.choices(["paid", "pending", "clawed_back"], weights=list(status_weights))[0],
        "claim_date": claim_ts.strftime("%Y-%m-%d"),
    })


def rand_signup_within_span(max_days=None):
    max_days = SPAN_DAYS if max_days is None else max_days
    return START + timedelta(days=random.uniform(0, max_days))


# --------------------------------------------------------------------------
# Background (ordinary, unconnected) accounts
# --------------------------------------------------------------------------

def gen_background(n):
    uids = []
    for _ in range(n):
        signup = rand_signup_within_span()
        acct = make_account(signup)
        uid = acct["user_id"]
        uids.append(uid)

        n_logins = random.randint(2, 15)
        ts = signup
        for _ in range(n_logins):
            ts = ts + timedelta(days=np.random.exponential(20) + 1, hours=random.uniform(0, 23))
            if ts > TODAY:
                break
            sessions.append(session_row(uid, acct["device_fingerprint_id"], acct["ip_address_at_signup"], ts, "login"))

        n_orders = np.random.poisson(2.5)
        ts = signup
        for _ in range(n_orders):
            ts = ts + timedelta(days=np.random.exponential(30) + 1)
            if ts > TODAY:
                break
            value = np.random.normal(650, 300)
            orders.append(order_row(uid, ts, value, acct["home_pincode"]))
            sessions.append(session_row(uid, acct["device_fingerprint_id"], acct["ip_address_at_signup"], ts, "order_placed"))
    return uids


def add_organic_referrals(background_uids, fraction=0.08):
    """Sparse, non-clustered referral links among ordinary users -- realistic noise."""
    signup_dt = {uid: datetime.strptime(accounts_by_uid[uid]["signup_date"], "%Y-%m-%d") for uid in background_uids}
    ordered = sorted(background_uids, key=lambda u: signup_dt[u])
    # A precomputed index dict, not ordered.index(uid) inside the loop -- list.index() is O(n)
    # per call, making this O(n_chosen x n_background) overall (quadratic in background account
    # count). Found by scale_stress_test.py: this alone accounted for most of the superlinear
    # generation-time growth at 50x scale. Pure lookup optimization, no change to which referrer
    # gets picked or to any random-number-generator call sequence.
    index_of = {uid: i for i, uid in enumerate(ordered)}
    n = int(len(background_uids) * fraction)
    chosen = random.sample(background_uids, min(n, len(background_uids)))
    for uid in chosen:
        signup = signup_dt[uid]
        idx = index_of[uid]
        earlier = ordered[:idx]
        if not earlier:
            continue
        referrer = random.choice(earlier[-500:] if len(earlier) > 500 else earlier)
        acct = accounts_by_uid[uid]
        acct["referred_by_user_id"] = referrer
        acct["referral_code_used"] = referral_codes[referrer]
        claim_ts = min(signup + timedelta(days=random.uniform(0.5, 15)), TODAY)
        add_referral(referrer, uid, claim_ts)
        sessions.append(session_row(uid, acct["device_fingerprint_id"], acct["ip_address_at_signup"], claim_ts, "referral_claim"))


# --------------------------------------------------------------------------
# Planted fraud rings
# --------------------------------------------------------------------------

def gen_hard_ring(size):
    """Shared device_fingerprint_id and/or shared instrument_hash. Signup burst,
    templated order values, claim-then-dormant."""
    share_device = random.random() < 0.7
    share_instrument = (not share_device) or random.random() < 0.5
    shared_device = rand_device_id() if share_device else None
    shared_instrument = rand_instrument_hash() if share_instrument else None

    subnet = rand_subnet()
    burst_start = rand_signup_within_span(SPAN_DAYS - 30)
    order_template = round(random.uniform(150, 2500), 2)

    members = []
    hub = None
    for i in range(size):
        signup = burst_start + timedelta(hours=random.uniform(0, 72))
        device_id = shared_device or rand_device_id()
        ip = rand_ip(subnet)
        instrument = shared_instrument
        referred_by = hub if (hub and random.random() < 0.8) else None
        code = referral_codes.get(referred_by, "") if referred_by else ""

        acct = make_account(signup, device_id=device_id, ip=ip, instrument_hash=instrument,
                             referred_by=referred_by, referral_code_used=code)
        uid = acct["user_id"]
        members.append(uid)
        if hub is None:
            hub = uid

        if referred_by:
            claim_ts = signup + timedelta(hours=random.uniform(0.1, 6))
            add_referral(referred_by, uid, claim_ts, status_weights=(0.85, 0.15, 0.0))
            sessions.append(session_row(uid, device_id, ip, claim_ts, "referral_claim"))

        # 1-2 near-identical orders, then dormant
        ts = signup
        for _ in range(random.randint(1, 2)):
            ts = ts + timedelta(hours=random.uniform(1, 24))
            value = order_template + random.uniform(-15, 15)
            orders.append(order_row(uid, ts, value, acct["home_pincode"]))
            sessions.append(session_row(uid, device_id, ip, ts, "order_placed"))
        if random.random() < 0.15:
            ts2 = signup + timedelta(days=random.uniform(5, 20))
            if ts2 <= TODAY:
                sessions.append(session_row(uid, device_id, ip, ts2, "login"))
    return members


def gen_soft_ring(size, hard_mode=False):
    """No shared device/instrument. Shared IP subnet + referral-chain timing +
    templated order values. claim-then-dormant. Only catchable via weighted community
    detection (Stage 3), not hard-signal connected components (Stage 2).

    hard_mode=True loosens every parameter (slower referral claims, wider signup
    spread, noisier order templating, more follow-up activity) to simulate a more
    patient/careful ring -- the genuinely harder case the soft-signal stage may miss."""
    subnet = rand_subnet()
    burst_start = rand_signup_within_span(SPAN_DAYS - 30)
    order_template = round(random.uniform(150, 2500), 2)

    gap_hours = (4, 20) if hard_mode else (0.5, 4)
    claim_hours = (6, 36) if hard_mode else (0.2, 4)
    order_noise = order_template * 0.12 if hard_mode else 15
    followup_chance = 0.4 if hard_mode else 0.15

    members = []
    prev = None
    for i in range(size):
        signup = burst_start + timedelta(hours=i * random.uniform(*gap_hours))
        device_id = rand_device_id()
        ip = rand_ip(subnet)
        instrument = rand_instrument_hash()
        referred_by = prev if (prev and random.random() < 0.85) else None
        code = referral_codes.get(referred_by, "") if referred_by else ""

        acct = make_account(signup, device_id=device_id, ip=ip, instrument_hash=instrument,
                             referred_by=referred_by, referral_code_used=code)
        uid = acct["user_id"]
        members.append(uid)

        if referred_by:
            claim_ts = signup + timedelta(hours=random.uniform(*claim_hours))
            add_referral(referred_by, uid, claim_ts, status_weights=(0.85, 0.15, 0.0))
            sessions.append(session_row(uid, device_id, ip, claim_ts, "referral_claim"))

        ts = signup
        for _ in range(random.randint(1, 2)):
            ts = ts + timedelta(hours=random.uniform(1, 24))
            value = order_template + random.uniform(-order_noise, order_noise)
            orders.append(order_row(uid, ts, value, acct["home_pincode"]))
            sessions.append(session_row(uid, device_id, ip, ts, "order_placed"))
        if random.random() < followup_chance:
            n_followups = random.randint(1, 3) if hard_mode else 1
            ts2 = signup
            for _ in range(n_followups):
                ts2 = ts2 + timedelta(days=random.uniform(5, 25))
                if ts2 <= TODAY:
                    sessions.append(session_row(uid, device_id, ip, ts2, "login"))
        prev = uid
    return members


# --------------------------------------------------------------------------
# Planted legitimate confounder clusters
# --------------------------------------------------------------------------

def gen_household(size, tight=False):
    """Shared device (family tablet) or shared IP. Organic, spread-out activity
    over months, diverse order values, no referral-timing pattern.

    tight=True compresses the signup window and order-value diversity toward the
    low end of "still organic" -- a genuinely borderline household (everyone signed
    up during one weekend setting up the new tablet) that stress-tests Stage 5.

    Device-share probability is 0.5 by default (invented). USE_GROUNDED_DEVICE_SHARING
    swaps it for GROUNDED_HOUSEHOLD_DEVICE_SHARE_PROB (0.55), grounded in the NSO CAMS
    "majority of Indian phone users share their phone with a family member" finding --
    see the constant's definition near the top of this file for the full citation.
    Off by default so the frozen SEED=20260828 dataset stays byte-identical; flip it
    only as part of a fresh freeze-and-reevaluate cycle."""
    share_prob = GROUNDED_HOUSEHOLD_DEVICE_SHARE_PROB if USE_GROUNDED_DEVICE_SHARING else 0.5
    shared_device = rand_device_id() if random.random() < share_prob else None
    subnet = rand_subnet()
    span_days = 25 if tight else 180
    start = rand_signup_within_span(SPAN_DAYS - span_days - 20)

    members = []
    for _ in range(size):
        signup = start + timedelta(days=random.uniform(0, span_days))
        device_id = shared_device or rand_device_id()
        ip = rand_ip(subnet)
        acct = make_account(signup, device_id=device_id, ip=ip)
        uid = acct["user_id"]
        members.append(uid)
        n_orders_range = (2, 6) if tight else (3, 12)
        n_logins_range = (3, 10) if tight else (5, 25)
        _add_organic_activity(acct, signup, n_orders_range=n_orders_range, n_logins_range=n_logins_range)
    return members


def gen_hostel(size):
    """Same idea as household but larger, shared IP subnet (campus/hostel wifi),
    rarely shared device. Organic, spread-out activity.

    The docstring has always said "rarely shared device," but the code never
    actually modeled any sharing -- a real gap, not a deliberate choice. Behind
    USE_GROUNDED_DEVICE_SHARING, a subset of members now share one of a small
    number of devices within the hostel (roommates sharing a laptop/tablet) at
    GROUNDED_HOSTEL_DEVICE_SHARE_PROB (0.15, ~ the 18% IAMAI-KANTAR national
    device-sharing average -- see the constant's definition for the full
    citation). Off by default so the frozen dataset stays byte-identical."""
    subnet = rand_subnet()
    start = rand_signup_within_span(SPAN_DAYS - 250)
    shared_pool = [rand_device_id() for _ in range(max(1, size // 4))] if USE_GROUNDED_DEVICE_SHARING else []

    members = []
    for _ in range(size):
        signup = start + timedelta(days=random.uniform(0, 240))
        if USE_GROUNDED_DEVICE_SHARING and random.random() < GROUNDED_HOSTEL_DEVICE_SHARE_PROB:
            device_id = random.choice(shared_pool)
        else:
            device_id = rand_device_id()
        ip = rand_ip(subnet)
        acct = make_account(signup, device_id=device_id, ip=ip)
        uid = acct["user_id"]
        members.append(uid)
        _add_organic_activity(acct, signup, n_orders_range=(2, 10), n_logins_range=(4, 20))
    return members


def gen_influencer_tree(size):
    """One hub referrer, large fan-out spread over months (not a burst), each
    referred account shows genuine varied post-signup engagement."""
    hub_signup = rand_signup_within_span(SPAN_DAYS - 280)
    hub_acct = make_account(hub_signup)
    hub_uid = hub_acct["user_id"]
    members = [hub_uid]
    _add_organic_activity(hub_acct, hub_signup, n_orders_range=(3, 15), n_logins_range=(5, 30))

    for _ in range(size):
        signup = hub_signup + timedelta(days=random.uniform(1, 270))
        if signup > TODAY:
            signup = TODAY - timedelta(days=random.uniform(0, 5))
        acct = make_account(signup, referred_by=hub_uid, referral_code_used=referral_codes[hub_uid])
        uid = acct["user_id"]
        members.append(uid)

        claim_ts = min(signup + timedelta(days=random.uniform(0.1, 10)), TODAY)
        add_referral(hub_uid, uid, claim_ts)
        sessions.append(session_row(uid, acct["device_fingerprint_id"], acct["ip_address_at_signup"], claim_ts, "referral_claim"))
        _add_organic_activity(acct, signup, n_orders_range=(1, 10), n_logins_range=(2, 18))
    return members


def gen_office(size):
    """Same IP subnet only. Zero other shared attributes, independent unrelated
    purchase behavior, no referral links between members."""
    subnet = rand_subnet()
    members = []
    for _ in range(size):
        signup = rand_signup_within_span()
        device_id = rand_device_id()
        ip = rand_ip(subnet)
        acct = make_account(signup, device_id=device_id, ip=ip)
        uid = acct["user_id"]
        members.append(uid)
        _add_organic_activity(acct, signup, n_orders_range=(0, 8), n_logins_range=(2, 15))
    return members


def _add_organic_activity(acct, signup, n_orders_range, n_logins_range):
    uid = acct["user_id"]
    device_id, ip, pincode = acct["device_fingerprint_id"], acct["ip_address_at_signup"], acct["home_pincode"]

    n_logins = random.randint(*n_logins_range)
    ts = signup
    for _ in range(n_logins):
        ts = ts + timedelta(days=np.random.exponential(15) + 1, hours=random.uniform(0, 23))
        if ts > TODAY:
            break
        sessions.append(session_row(uid, device_id, ip, ts, "login"))

    n_orders = random.randint(*n_orders_range)
    ts = signup
    for _ in range(n_orders):
        ts = ts + timedelta(days=np.random.exponential(25) + 2)
        if ts > TODAY:
            break
        value = np.random.normal(700, 400)
        orders.append(order_row(uid, ts, value, pincode))
        sessions.append(session_row(uid, device_id, ip, ts, "order_placed"))


# --------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------

def _reset_state():
    """Clear module-level generation state so `generate()` can be called more than
    once in the same process without accounts/sessions/etc. accumulating across calls."""
    counters.update({"user": 0, "session": 0, "referral": 0, "order": 0})
    accounts.clear()
    sessions.clear()
    referrals.clear()
    payment_instruments.clear()
    orders.clear()
    accounts_by_uid.clear()
    referral_codes.clear()


def generate(scale: int = 1, raw_dir: Path = None, gt_dir: Path = None, seed: int = None, verbose: bool = True):
    """Generate a full synthetic cohort. scale=1 (default) reproduces the exact
    frozen dataset byte-for-byte (same seed, same counts, same output paths) --
    this is the only mode ever used for the primary eval numbers. scale=N
    multiplies every planted ring/confounder count and the background-noise
    target by N, for the scale stress test (backend/scale_stress_test.py),
    which always passes its own raw_dir/gt_dir so it never writes here."""
    raw_dir = raw_dir or RAW_DIR
    gt_dir = gt_dir or GT_DIR
    raw_dir.mkdir(parents=True, exist_ok=True)
    gt_dir.mkdir(parents=True, exist_ok=True)
    random.seed(seed if seed is not None else SEED)
    np.random.seed(seed if seed is not None else SEED)
    _reset_state()

    rings_gt = {}
    confounders_gt = {}
    labels = []  # user_id, cluster_type, cluster_id

    # --- Hard-signal rings ---
    n_hard = 40 * scale
    for i in range(1, n_hard + 1):
        size = random.randint(3, 15)
        members = gen_hard_ring(size)
        ring_id = f"RING_HARD_{i:02d}"
        rings_gt[ring_id] = {
            "type": "hard",
            "members": members,
            "description": "Shared device_fingerprint_id and/or instrument_hash across distinct accounts; "
                            "signup burst; templated order values; claim-then-dormant.",
        }
        labels += [{"user_id": u, "cluster_type": "ring_hard", "cluster_id": ring_id} for u in members]

    # --- Soft-signal rings --- (~40% run in hard_mode: slower/noisier, the genuinely hard case)
    n_soft = 40 * scale
    hard_mode_indices = {i for i in range(1, n_soft + 1) if i % 5 in (2, 4)}
    for i in range(1, n_soft + 1):
        size = random.randint(4, 15)
        hard_mode = i in hard_mode_indices
        members = gen_soft_ring(size, hard_mode=hard_mode)
        ring_id = f"RING_SOFT_{i:02d}"
        rings_gt[ring_id] = {
            "type": "soft",
            "difficulty": "hard" if hard_mode else "easy",
            "members": members,
            "description": ("Shared IP subnet + slow/loose referral-chain timing + noisier templated order "
                             "values; occasional follow-up activity. No shared device or instrument. Deliberately "
                             "harder to catch."
                             if hard_mode else
                             "Shared IP subnet + tight referral-chain timing (hours) + templated order values; "
                             "claim-then-dormant. No shared device or instrument."),
        }
        labels += [{"user_id": u, "cluster_type": "ring_soft", "cluster_id": ring_id} for u in members]

    # --- Confounders --- (a few households run "tight": borderline organic, stress-tests Stage 5)
    conf_specs = (
        [("household", gen_household, (3, 6), {"tight": True}) for _ in range(3 * scale)]
        + [("household", gen_household, (3, 6), {}) for _ in range(10 * scale)]
        + [("hostel", gen_hostel, (12, 25), {}) for _ in range(10 * scale)]
        + [("influencer", gen_influencer_tree, (25, 50), {}) for _ in range(7 * scale)]
        + [("office", gen_office, (15, 35), {}) for _ in range(10 * scale)]
    )
    conf_counters = {}
    for kind, fn, size_range, kwargs in conf_specs:
        conf_counters[kind] = conf_counters.get(kind, 0) + 1
        size = random.randint(*size_range)
        members = fn(size, **kwargs)
        conf_id = f"CONF_{kind.upper()}_{conf_counters[kind]:02d}"
        descriptions = {
            "household": "Shared device or IP (family), organic spread-out activity over months, diverse order values.",
            "hostel": "Shared IP subnet (campus/hostel wifi), organic spread-out activity, no referral-timing pattern.",
            "influencer": "One hub referrer with large organic fan-out spread over months; genuine varied post-signup engagement.",
            "office": "Shared IP subnet only (office wifi); zero other shared attributes; unrelated independent purchase behavior.",
        }
        difficulty = "tight" if kwargs.get("tight") else "easy"
        desc = descriptions[kind] + (" Deliberately borderline (compressed signup window)." if kwargs.get("tight") else "")
        confounders_gt[conf_id] = {"type": kind, "difficulty": difficulty, "members": members, "description": desc}
        labels += [{"user_id": u, "cluster_type": f"confounder_{kind}", "cluster_id": conf_id} for u in members]

    # --- Background noise ---
    planted_count = sum(len(v["members"]) for v in rings_gt.values()) + sum(len(v["members"]) for v in confounders_gt.values())
    n_background = max(TARGET_TOTAL_ACCOUNTS * scale - planted_count, 0)
    background_uids = gen_background(n_background)
    add_organic_referrals(background_uids)
    labels += [{"user_id": u, "cluster_type": "background", "cluster_id": ""} for u in background_uids]

    # --- Write raw CSVs ---
    pd.DataFrame(accounts).to_csv(raw_dir / "accounts.csv", index=False)
    pd.DataFrame(sessions).to_csv(raw_dir / "sessions.csv", index=False)
    pd.DataFrame(referrals).to_csv(raw_dir / "referrals.csv", index=False)
    pd.DataFrame(payment_instruments).to_csv(raw_dir / "payment_instruments.csv", index=False)
    pd.DataFrame(orders).to_csv(raw_dir / "orders.csv", index=False)

    # --- Write ground truth ---
    with open(gt_dir / "rings.json", "w") as f:
        json.dump(rings_gt, f, indent=2)
    with open(gt_dir / "confounders.json", "w") as f:
        json.dump(confounders_gt, f, indent=2)
    pd.DataFrame(labels).to_csv(gt_dir / "labels.csv", index=False)

    # --- Summary ---
    if verbose:
        print("=== Synthetic data generation complete ===")
        print(f"Total accounts:        {len(accounts)}")
        print(f"  Hard-signal rings:    {n_hard} rings, {sum(len(v['members']) for k,v in rings_gt.items() if v['type']=='hard')} accounts")
        print(f"  Soft-signal rings:    {n_soft} rings, {sum(len(v['members']) for k,v in rings_gt.items() if v['type']=='soft')} accounts")
        for kind in ["household", "hostel", "influencer", "office"]:
            n = sum(1 for v in confounders_gt.values() if v["type"] == kind)
            acc = sum(len(v["members"]) for v in confounders_gt.values() if v["type"] == kind)
            print(f"  Confounder ({kind}):{'':1} {n} clusters, {acc} accounts")
        print(f"  Background noise:     {n_background} accounts")
        print(f"Sessions:               {len(sessions)}")
        print(f"Referrals:              {len(referrals)}")
        print(f"Payment instruments:    {len(payment_instruments)}")
        print(f"Orders:                 {len(orders)}")
        print(f"\nRaw data ->        {raw_dir}")
        print(f"Ground truth ->    {gt_dir}")

    return {"n_accounts": len(accounts), "n_sessions": len(sessions), "n_referrals": len(referrals),
            "n_payment_instruments": len(payment_instruments), "n_orders": len(orders)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scale", type=int, default=1)
    parser.add_argument("--raw-dir", type=Path, default=None)
    parser.add_argument("--gt-dir", type=Path, default=None)
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()
    generate(scale=args.scale, raw_dir=args.raw_dir, gt_dir=args.gt_dir, seed=args.seed)


if __name__ == "__main__":
    main()
