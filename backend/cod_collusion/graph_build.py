"""
Stage 1 for the COD loss type -- same mechanism as the referral-abuse graph
(backend/pipeline/graph_build.py), different edge vocabulary: shared delivery
address and shared phone-number prefix instead of shared device/instrument.
Stages 2 and 3 (clustering) are imported UNCHANGED from backend.pipeline --
this file's only job is to hand them a differently-sourced graph.
"""

from collections import defaultdict
from pathlib import Path

import networkx as nx
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "cod" / "raw"

W_ADDRESS = 4.0   # hard signal -- exact same delivery address across distinct accounts
W_PHONE_PREFIX = 2.0  # soft signal -- same first-7-digit phone block (a batch of SIMs)

HARD_SIGNALS = {"shared_address"}


def load_data():
    accounts = pd.read_csv(RAW_DIR / "accounts.csv", dtype=str)
    orders = pd.read_csv(RAW_DIR / "orders.csv", dtype=str)
    orders["order_value"] = orders["order_value"].astype(float)
    orders["order_date"] = pd.to_datetime(orders["order_date"])
    return accounts, orders


def _add_edge(G, u, v, signal, weight):
    if u == v:
        return
    if G.has_edge(u, v):
        G[u][v]["weight"] += weight
        G[u][v]["signals"].add(signal)
    else:
        G.add_edge(u, v, weight=weight, signals={signal})


def _valid(v):
    return v is not None and not (isinstance(v, float) and pd.isna(v)) and str(v).strip() != ""


def build_graph(accounts: pd.DataFrame) -> nx.Graph:
    G = nx.Graph()
    G.add_nodes_from(accounts.user_id)

    groups = defaultdict(list)
    for uid, addr in zip(accounts.user_id, accounts.delivery_address_hash):
        if _valid(addr):
            groups[addr].append(uid)
    for members in groups.values():
        if len(members) < 2:
            continue
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                _add_edge(G, members[i], members[j], "shared_address", W_ADDRESS)

    groups = defaultdict(list)
    for uid, phone in zip(accounts.user_id, accounts.phone_number):
        if _valid(phone) and len(phone) >= 9:
            groups[phone[:9]].append(uid)  # "+91" + first 6 digits = same SIM block
    for members in groups.values():
        if len(members) < 2:
            continue
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                _add_edge(G, members[i], members[j], "phone_prefix", W_PHONE_PREFIX)

    return G


def hard_signal_subgraph(G: nx.Graph) -> nx.Graph:
    H = nx.Graph()
    H.add_nodes_from(G.nodes)
    for u, v, d in G.edges(data=True):
        if d["signals"] & HARD_SIGNALS:
            H.add_edge(u, v, weight=d["weight"], signals=d["signals"] & HARD_SIGNALS)
    return H
