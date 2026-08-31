"""Load raw CSVs into a shared, pre-indexed bundle used by every pipeline stage."""

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "raw"
GT_DIR = ROOT / "data" / "ground_truth"
PROCESSED_DIR = ROOT / "data" / "processed"
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


def _drop_invalid(df: pd.DataFrame, table: str, bad_mask: pd.Series, reason: str, id_col: str, report: list, verbose: bool):
    """Shared drop-and-log path for every malformed-record check below. Never raises --
    a bad row is skipped and logged, the rest of the batch proceeds unaffected. Verified
    against backend/infra_resilience_test.py: a corrupted record anywhere in the batch
    (missing field, wrong type, out-of-range value) no longer halts the whole run, and
    every skip is accounted for in `report` rather than silently absorbed (e.g. a missing
    order_value used to pass through as NaN and quietly poison downstream averages)."""
    n_bad = int(bad_mask.sum())
    if n_bad == 0:
        return df
    examples = df.loc[bad_mask, id_col].astype(str).head(3).tolist()
    report.append({"table": table, "reason": reason, "rows_dropped": n_bad, "example_ids": examples})
    if verbose:
        print(f"  [data quality] {table}: dropped {n_bad} row(s) -- {reason} (examples: {examples})")
    return df.loc[~bad_mask].reset_index(drop=True)


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
    data_quality_report: list = field(default_factory=list)  # rows dropped as malformed, per table/reason


def load_data(raw_dir: Path = None, verbose: bool = True) -> DataBundle:
    """`verbose=True` by default logs every malformed row dropped (see _drop_invalid) --
    matching this project's convention of informative-by-default output. Every existing
    call site is unaffected: on the frozen dataset (no malformed rows) zero rows are ever
    dropped, verified byte-identical against the pre-validation behavior."""
    raw_dir = raw_dir or RAW_DIR
    report = []
    accounts = pd.read_csv(raw_dir / "accounts.csv", dtype=str)
    sessions = pd.read_csv(raw_dir / "sessions.csv", dtype=str)
    referrals = pd.read_csv(raw_dir / "referrals.csv", dtype=str)
    instruments = pd.read_csv(raw_dir / "payment_instruments.csv", dtype=str)
    orders = pd.read_csv(raw_dir / "orders.csv", dtype=str)

    # Required-id checks first (an empty/missing id would otherwise silently vanish from
    # every downstream groupby -- e.g. an order with no user_id used to disappear from
    # that user's order history with no record it ever existed).
    accounts = _drop_invalid(accounts, "accounts", accounts["user_id"].isna() | (accounts["user_id"].astype(str).str.strip() == ""),
                              "missing user_id", "user_id", report, verbose)
    sessions = _drop_invalid(sessions, "sessions", sessions["user_id"].isna() | (sessions["user_id"].astype(str).str.strip() == ""),
                              "missing user_id", "user_id", report, verbose)
    orders = _drop_invalid(orders, "orders", orders["user_id"].isna() | (orders["user_id"].astype(str).str.strip() == ""),
                            "missing user_id", "user_id", report, verbose)

    # Datetime fields: coerce (never raises) instead of a hard cast that crashes the whole
    # batch on one unparseable value, then drop+log just the rows that didn't parse.
    sessions["timestamp"] = pd.to_datetime(sessions["timestamp"], errors="coerce")
    sessions = _drop_invalid(sessions, "sessions", sessions["timestamp"].isna(), "unparseable timestamp", "user_id", report, verbose)

    accounts["signup_date"] = pd.to_datetime(accounts["signup_date"], errors="coerce")
    accounts = _drop_invalid(accounts, "accounts", accounts["signup_date"].isna(), "unparseable signup_date", "user_id", report, verbose)

    orders["order_date"] = pd.to_datetime(orders["order_date"], errors="coerce")
    orders = _drop_invalid(orders, "orders", orders["order_date"].isna(), "unparseable order_date", "user_id", report, verbose)

    referrals["claim_date"] = pd.to_datetime(referrals["claim_date"], errors="coerce")
    referrals = _drop_invalid(referrals, "referrals", referrals["claim_date"].isna(), "unparseable claim_date", "referrer_user_id", report, verbose)

    # Numeric fields: coerce, then drop rows that didn't parse OR fall outside a sane
    # range (a negative order_value/bonus_amount used to pass straight through and
    # silently corrupt downstream averages/CV -- see confidence in features.py).
    orders["order_value"] = pd.to_numeric(orders["order_value"], errors="coerce")
    orders = _drop_invalid(orders, "orders", orders["order_value"].isna() | (orders["order_value"] < 0),
                            "missing/negative order_value", "user_id", report, verbose)

    referrals["bonus_amount"] = pd.to_numeric(referrals["bonus_amount"], errors="coerce")
    referrals = _drop_invalid(referrals, "referrals", referrals["bonus_amount"].isna() | (referrals["bonus_amount"] < 0),
                               "missing/negative bonus_amount", "referrer_user_id", report, verbose)

    if verbose and report:
        print(f"  [data quality] {sum(r['rows_dropped'] for r in report)} total row(s) dropped across "
              f"{len(report)} check(s) -- see data_quality_report for detail.")

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
        data_quality_report=report,
    )
