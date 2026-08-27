"""
Stage 4 -- cluster feature scoring. Still fully deterministic, no LLM.

For every candidate cluster (from Stage 2 or Stage 3) compute the behavioral
features that separate a farming ring from a legitimate dense cluster: size,
edge density, signup burst tightness, bonus-claim velocity, order-value
templating, the claim-then-dormant pattern, and post-signup engagement.
"""

import math
from collections import Counter
from datetime import timedelta

import networkx as nx

from .data_io import DataBundle


def build_lookups(data: DataBundle):
    device_by_user = dict(zip(data.accounts.user_id, data.accounts.device_fingerprint_id))
    instrument_by_user = dict(zip(data.instruments.user_id, data.instruments.instrument_hash))
    return device_by_user, instrument_by_user


def compute_features(G: nx.Graph, members: set, data: DataBundle, device_by_user: dict, instrument_by_user: dict) -> dict:
    members = list(members)
    size = len(members)

    # --- edge density + which signal types fired within this cluster ---
    sub = G.subgraph(members)
    n_edges = sub.number_of_edges()
    max_edges = size * (size - 1) / 2
    edge_density = n_edges / max_edges if max_edges > 0 else 0.0
    signals_present = set()
    for _, _, d in sub.edges(data=True):
        signals_present |= d["signals"]

    # --- shared device / instrument ---
    devices = [device_by_user.get(u) for u in members]
    dev_counts = Counter(d for d in devices if d is not None)
    top_device, top_device_count = (dev_counts.most_common(1) or [(None, 0)])[0]
    shared_device = top_device_count >= 2
    shared_device_frac = top_device_count / size

    instruments = [instrument_by_user.get(u) for u in members]
    instr_counts = Counter(i for i in instruments if i is not None)
    top_instr, top_instr_count = (instr_counts.most_common(1) or [(None, 0)])[0]
    shared_instrument = top_instr_count >= 2
    shared_instrument_frac = top_instr_count / size

    # --- signup timing ---
    signup_times = sorted(data.signup_ts[u] for u in members if u in data.signup_ts)
    if len(signup_times) >= 2:
        signup_span_days = (signup_times[-1] - signup_times[0]).total_seconds() / 86400.0
        gaps_hours = [
            (signup_times[i + 1] - signup_times[i]).total_seconds() / 3600.0
            for i in range(len(signup_times) - 1)
        ]
        avg_gap_hours = sum(gaps_hours) / len(gaps_hours)
    else:
        signup_span_days = 0.0
        avg_gap_hours = 0.0

    # --- bonus claim velocity + claim-then-dormant ---
    claim_hours = []
    dormant_flags = []
    for u in members:
        claim = data.claim_ts.get(u)
        signup = data.signup_ts.get(u)
        if claim is None or signup is None:
            continue
        claim_hours.append((claim - signup).total_seconds() / 3600.0)
        cutoff = claim + timedelta(days=3)
        further = data.sessions[(data.sessions.user_id == u) & (data.sessions.timestamp > cutoff)]
        dormant_flags.append(len(further) == 0)

    bonus_claim_velocity_hours = sum(claim_hours) / len(claim_hours) if claim_hours else None
    claim_frac = len(claim_hours) / size
    claim_then_dormant_frac = sum(dormant_flags) / len(dormant_flags) if dormant_flags else None

    # --- order-value templating ---
    orders_sub = data.orders[data.orders.user_id.isin(members)]
    n_orders = len(orders_sub)
    if n_orders >= 2:
        mean_val = orders_sub.order_value.mean()
        std_val = orders_sub.order_value.std()
        order_value_cv = (std_val / mean_val) if mean_val > 0 else None
    else:
        order_value_cv = None

    # --- post-signup engagement (activity beyond the first week) ---
    sessions_sub = data.sessions[data.sessions.user_id.isin(members)].copy()
    sessions_sub["signup_ref"] = sessions_sub.user_id.map(data.signup_ts)
    late = sessions_sub[sessions_sub.timestamp > (sessions_sub["signup_ref"] + timedelta(days=7))]
    post_signup_engagement = len(late) / size

    return {
        "size": size,
        "n_edges": n_edges,
        "edge_density": round(edge_density, 4),
        "signals_present": sorted(signals_present),
        "shared_device": shared_device,
        "shared_device_frac": round(shared_device_frac, 3),
        "shared_instrument": shared_instrument,
        "shared_instrument_frac": round(shared_instrument_frac, 3),
        "signup_span_days": round(signup_span_days, 2),
        "avg_gap_hours": round(avg_gap_hours, 2),
        "bonus_claim_velocity_hours": round(bonus_claim_velocity_hours, 2) if bonus_claim_velocity_hours is not None else None,
        "claim_frac": round(claim_frac, 3),
        "claim_then_dormant_frac": round(claim_then_dormant_frac, 3) if claim_then_dormant_frac is not None else None,
        "n_orders": n_orders,
        "order_value_cv": round(order_value_cv, 4) if order_value_cv is not None and not math.isnan(order_value_cv) else None,
        "post_signup_engagement": round(post_signup_engagement, 3),
    }
