"""
Second loss type, same architecture: COD (cash-on-delivery) serial-refusal
collusion -- accounts that repeatedly order high-value goods COD and refuse
delivery, clustered by shared address/phone patterns instead of shared
device/instrument. A separate, smaller, self-contained dataset (this is
explicitly stretch scope per the BRD) -- it never touches the main
promo/referral dataset or its frozen eval snapshot.

Run: python -m backend.cod_collusion.generate_data
"""

import json
import random
import string
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 2026828
random.seed(SEED)
np.random.seed(SEED)

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "cod" / "raw"
GT_DIR = ROOT / "data" / "cod" / "ground_truth"
RAW_DIR.mkdir(parents=True, exist_ok=True)
GT_DIR.mkdir(parents=True, exist_ok=True)

TODAY = datetime(2026, 8, 28)
START = datetime(2025, 9, 1)
SPAN_DAYS = (TODAY - START).days
TARGET_ACCOUNTS = 1500

counters = {"user": 0, "order": 0}
accounts, orders = [], []


def next_id(prefix, key, width=6):
    counters[key] += 1
    return f"{prefix}{counters[key]:0{width}d}"


def rand_phone(prefix=None):
    if prefix:
        return prefix + "".join(random.choices(string.digits, k=10 - len(prefix)))
    return "+91" + str(random.choice([6, 7, 8, 9])) + "".join(random.choices(string.digits, k=9))


def rand_address_hash():
    return "addr_" + "".join(random.choices(string.ascii_lowercase + string.digits, k=12))


def rand_pincode():
    return str(random.randint(1, 8)) + "".join(random.choices(string.digits, k=5))


def rand_signup():
    return START + timedelta(days=random.uniform(0, SPAN_DAYS))


def make_account(signup, address_hash=None, phone=None, pincode=None):
    uid = next_id("C", "user")
    accounts.append({
        "user_id": uid, "signup_date": signup.strftime("%Y-%m-%d"),
        "phone_number": phone or rand_phone(),
        "delivery_address_hash": address_hash or rand_address_hash(),
        "home_pincode": pincode or rand_pincode(),
    })
    return uid


def add_order(uid, ts, value, payment_method, delivery_status):
    orders.append({
        "order_id": next_id("OC", "order"), "user_id": uid, "order_value": round(value, 2),
        "order_date": ts.strftime("%Y-%m-%d"), "payment_method": payment_method, "delivery_status": delivery_status,
    })


def gen_collusion_ring(size):
    """Shared delivery address (the drop point) and/or a phone-number prefix (a batch of
    SIMs bought together). High-value COD orders, refused almost every time."""
    address = rand_address_hash() if random.random() < 0.75 else None
    phone_prefix = "+91" + "".join(random.choices(string.digits, k=7)) if (address is None or random.random() < 0.6) else None
    pincode = rand_pincode()
    refusal_rate = random.uniform(0.7, 1.0)

    members = []
    for _ in range(size):
        signup = rand_signup()
        phone = rand_phone(phone_prefix) if phone_prefix else rand_phone()
        uid = make_account(signup, address_hash=address, phone=phone, pincode=pincode)
        members.append(uid)

        n_orders = random.randint(2, 6)
        ts = signup
        for _ in range(n_orders):
            ts = ts + timedelta(days=random.uniform(2, 20))
            if ts > TODAY:
                break
            value = random.uniform(2000, 12000)  # high-value targeting
            refused = random.random() < refusal_rate
            add_order(uid, ts, value, "COD", "refused" if refused else "delivered")
    return members


def gen_shared_address_confounder(size):
    """A real multi-tenant address (hostel/apartment building) -- many distinct accounts,
    same address, but normal refusal behavior and a healthy mix of COD/prepaid."""
    address = rand_address_hash()
    pincode = rand_pincode()
    members = []
    for _ in range(size):
        signup = rand_signup()
        uid = make_account(signup, address_hash=address, phone=rand_phone(), pincode=pincode)
        members.append(uid)

        n_orders = random.randint(3, 12)
        ts = signup
        for _ in range(n_orders):
            ts = ts + timedelta(days=np.random.exponential(20) + 2)
            if ts > TODAY:
                break
            value = max(99, np.random.normal(900, 500))
            payment = random.choices(["COD", "prepaid"], weights=[0.4, 0.6])[0]
            refused = payment == "COD" and random.random() < 0.12  # normal organic refusal rate
            add_order(uid, ts, value, payment, "refused" if refused else "delivered")
    return members


def gen_background(n):
    uids = []
    for _ in range(n):
        signup = rand_signup()
        uid = make_account(signup)
        uids.append(uid)
        n_orders = np.random.poisson(3)
        ts = signup
        for _ in range(n_orders):
            ts = ts + timedelta(days=np.random.exponential(25) + 2)
            if ts > TODAY:
                break
            value = max(99, np.random.normal(700, 400))
            payment = random.choices(["COD", "prepaid"], weights=[0.35, 0.65])[0]
            refused = payment == "COD" and random.random() < 0.10
            add_order(uid, ts, value, payment, "refused" if refused else "delivered")
    return uids


def main():
    rings_gt, confounders_gt, labels = {}, {}, []

    n_rings = 10
    for i in range(1, n_rings + 1):
        size = random.randint(3, 10)
        members = gen_collusion_ring(size)
        rid = f"COD_RING_{i:02d}"
        rings_gt[rid] = {"members": members, "description": "Shared delivery address and/or phone-number prefix; high-value COD orders refused 70-100% of the time."}
        labels += [{"user_id": u, "cluster_type": "cod_ring", "cluster_id": rid} for u in members]

    n_conf = 6
    for i in range(1, n_conf + 1):
        size = random.randint(6, 16)
        members = gen_shared_address_confounder(size)
        cid = f"COD_CONF_{i:02d}"
        confounders_gt[cid] = {"members": members, "description": "Real multi-tenant address (hostel/apartment); normal ~12% refusal rate, mixed COD/prepaid."}
        labels += [{"user_id": u, "cluster_type": "cod_confounder", "cluster_id": cid} for u in members]

    planted = sum(len(v["members"]) for v in rings_gt.values()) + sum(len(v["members"]) for v in confounders_gt.values())
    n_background = max(TARGET_ACCOUNTS - planted, 0)
    bg_uids = gen_background(n_background)
    labels += [{"user_id": u, "cluster_type": "background", "cluster_id": ""} for u in bg_uids]

    pd.DataFrame(accounts).to_csv(RAW_DIR / "accounts.csv", index=False)
    pd.DataFrame(orders).to_csv(RAW_DIR / "orders.csv", index=False)
    with open(GT_DIR / "rings.json", "w") as f:
        json.dump(rings_gt, f, indent=2)
    with open(GT_DIR / "confounders.json", "w") as f:
        json.dump(confounders_gt, f, indent=2)
    pd.DataFrame(labels).to_csv(GT_DIR / "labels.csv", index=False)

    print("=== COD collusion dataset generated ===")
    print(f"Total accounts: {len(accounts)}")
    print(f"  Collusion rings: {n_rings}, {sum(len(v['members']) for v in rings_gt.values())} accounts")
    print(f"  Confounders (shared address, legit): {n_conf}, {sum(len(v['members']) for v in confounders_gt.values())} accounts")
    print(f"  Background: {n_background} accounts")
    print(f"Orders: {len(orders)}")
    print(f"Raw -> {RAW_DIR}")
    print(f"Ground truth -> {GT_DIR}")


if __name__ == "__main__":
    main()
