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


def load_data() -> DataBundle:
    accounts = pd.read_csv(RAW_DIR / "accounts.csv", dtype=str)
    sessions = pd.read_csv(RAW_DIR / "sessions.csv", dtype=str)
    referrals = pd.read_csv(RAW_DIR / "referrals.csv", dtype=str)
    instruments = pd.read_csv(RAW_DIR / "payment_instruments.csv", dtype=str)
    orders = pd.read_csv(RAW_DIR / "orders.csv", dtype=str)

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

    ip_subnet = {
        uid: ".".join(str(ip).split(".")[:3])
        for uid, ip in zip(accounts.user_id, accounts.ip_address_at_signup)
    }

    return DataBundle(
        accounts=accounts,
        sessions=sessions,
        referrals=referrals,
        instruments=instruments,
        orders=orders,
        signup_ts=signup_ts,
        claim_ts=claim_ts,
        ip_subnet=ip_subnet,
    )
