"""Load raw CSVs into a shared, pre-indexed bundle used by every pipeline stage."""

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "raw"
GT_DIR = ROOT / "data" / "ground_truth"
PROCESSED_DIR = ROOT / "data" / "processed"
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class DataBundle:
    accounts: pd.DataFrame
    sessions: pd.DataFrame
    referrals: pd.DataFrame
    instruments: pd.DataFrame
    orders: pd.DataFrame

    # convenience lookups, built once
    signup_ts: dict       # user_id -> pandas.Timestamp (precise, from sessions)
    claim_ts: dict        # user_id -> pandas.Timestamp of referral_claim session (first one), or None
    ip_subnet: dict       # user_id -> "a.b.c" (first three octets of signup IP)
    session_timestamps_by_user: dict  # user_id -> list of pandas.Timestamp (that user's session times)
    order_values_by_user: dict        # user_id -> list of float (that user's order values)


def load_data(raw_dir: Path = None) -> DataBundle:
    raw_dir = raw_dir or RAW_DIR
    accounts = pd.read_csv(raw_dir / "accounts.csv", dtype=str)
    sessions = pd.read_csv(raw_dir / "sessions.csv", dtype=str)
    referrals = pd.read_csv(raw_dir / "referrals.csv", dtype=str)
    instruments = pd.read_csv(raw_dir / "payment_instruments.csv", dtype=str)
    orders = pd.read_csv(raw_dir / "orders.csv", dtype=str)

    sessions["timestamp"] = pd.to_datetime(sessions["timestamp"])
    accounts["signup_date"] = pd.to_datetime(accounts["signup_date"])
    orders["order_value"] = orders["order_value"].astype(float)
    orders["order_date"] = pd.to_datetime(orders["order_date"])
    referrals["bonus_amount"] = referrals["bonus_amount"].astype(float)
    referrals["claim_date"] = pd.to_datetime(referrals["claim_date"])

    signup_sessions = sessions[sessions.action_type == "signup"].sort_values("timestamp")
    signup_ts = signup_sessions.groupby("user_id")["timestamp"].first().to_dict()
    # fallback for any account missing a signup session row
    for uid, d in zip(accounts.user_id, accounts.signup_date):
        signup_ts.setdefault(uid, d)

    claim_sessions = sessions[sessions.action_type == "referral_claim"].sort_values("timestamp")
    claim_ts = claim_sessions.groupby("user_id")["timestamp"].first().to_dict()

    def _subnet(ip):
        if not isinstance(ip, str) or ip.count(".") != 3:
            return None
        return ".".join(ip.split(".")[:3])

    ip_subnet = {uid: _subnet(ip) for uid, ip in zip(accounts.user_id, accounts.ip_address_at_signup)}

    # Grouped once here rather than re-scanning the full sessions/orders table on every
    # per-cluster or per-member lookup in features.py -- at scale (see scale_stress_test.py)
    # the un-indexed version dominates Stage 4's runtime by two orders of magnitude.
    # Plain lists of the one column each caller actually needs, not per-user
    # DataFrames -- constructing ~account-count-many small DataFrame objects has
    # enough per-object overhead of its own to become the next bottleneck.
    session_timestamps_by_user = sessions.groupby("user_id")["timestamp"].apply(list).to_dict()
    order_values_by_user = orders.groupby("user_id")["order_value"].apply(list).to_dict()

    return DataBundle(
        accounts=accounts,
        sessions=sessions,
        referrals=referrals,
        instruments=instruments,
        orders=orders,
        signup_ts=signup_ts,
        claim_ts=claim_ts,
        ip_subnet=ip_subnet,
        session_timestamps_by_user=session_timestamps_by_user,
        order_values_by_user=order_values_by_user,
    )
