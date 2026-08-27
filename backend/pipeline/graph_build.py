"""
Stage 1 -- Entity graph construction.

Nodes = accounts. Edges = shared device_fingerprint_id, shared instrument_hash,
IP-subnet overlap, or a referral link, with weights reflecting signal strength:
shared payment instrument > shared device > IP overlap > referral link alone.
A referral edge is strengthened further when the claim happens within hours of
signup (the tight-timing pattern rings exhibit).

Every edge records which signal(s) produced it, so any downstream flag is
traceable back to a specific shared attribute (explainability requirement).
"""

from collections import defaultdict

import networkx as nx
import pandas as pd

from .data_io import DataBundle

# Signal base weights: instrument > device > ip_subnet > referral
W_INSTRUMENT = 4.0
W_DEVICE = 3.0
W_IP_SUBNET = 2.0
W_REFERRAL_TIGHT = 2.0   # claim within 6h of signup
W_REFERRAL_WARM = 1.3    # claim within 48h
W_REFERRAL_COLD = 0.8    # claim later, or no claim session found

HARD_SIGNALS = {"shared_instrument", "shared_device"}


def _valid(value) -> bool:
    """A missing device_fingerprint_id / instrument_hash / IP is a data-quality gap, not
    a shared value -- accounts with the same gap must never be treated as linked."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return False
    return str(value).strip() != ""


def _add_edge(G, u, v, signal, weight):
    if u == v:
        return
    if G.has_edge(u, v):
        G[u][v]["weight"] += weight
        G[u][v]["signals"].add(signal)
    else:
        G.add_edge(u, v, weight=weight, signals={signal})


def build_graph(data: DataBundle) -> nx.Graph:
    G = nx.Graph()
    G.add_nodes_from(data.accounts.user_id)

    # --- shared instrument_hash ---
    groups = defaultdict(list)
    for uid, ih in zip(data.instruments.user_id, data.instruments.instrument_hash):
        if _valid(ih):
            groups[ih].append(uid)
    for members in groups.values():
        if len(members) < 2:
            continue
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                _add_edge(G, members[i], members[j], "shared_instrument", W_INSTRUMENT)

    # --- shared device_fingerprint_id ---
    groups = defaultdict(list)
    for uid, dev in zip(data.accounts.user_id, data.accounts.device_fingerprint_id):
        if _valid(dev):
            groups[dev].append(uid)
    for members in groups.values():
        if len(members) < 2:
            continue
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                _add_edge(G, members[i], members[j], "shared_device", W_DEVICE)

    # --- IP-subnet overlap (first three octets of signup IP) ---
    groups = defaultdict(list)
    for uid, subnet in data.ip_subnet.items():
        if _valid(subnet):
            groups[subnet].append(uid)
    for members in groups.values():
        if len(members) < 2:
            continue
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                _add_edge(G, members[i], members[j], "ip_subnet_overlap", W_IP_SUBNET)

    # --- referral link, weighted by claim speed ---
    for referrer, referred in zip(data.referrals.referrer_user_id, data.referrals.referred_user_id):
        if referrer not in G or referred not in G:
            continue
        signup = data.signup_ts.get(referred)
        claim = data.claim_ts.get(referred)
        if signup is not None and claim is not None:
            hours = (claim - signup).total_seconds() / 3600.0
            if hours <= 6:
                w = W_REFERRAL_TIGHT
            elif hours <= 48:
                w = W_REFERRAL_WARM
            else:
                w = W_REFERRAL_COLD
        else:
            w = W_REFERRAL_COLD
        _add_edge(G, referrer, referred, "referral_link", w)

    return G


def hard_signal_subgraph(G: nx.Graph) -> nx.Graph:
    """Edges driven only by shared device or shared instrument -- the near-certain signals."""
    H = nx.Graph()
    H.add_nodes_from(G.nodes)
    for u, v, d in G.edges(data=True):
        if d["signals"] & HARD_SIGNALS:
            H.add_edge(u, v, weight=d["weight"], signals=d["signals"] & HARD_SIGNALS)
    return H
