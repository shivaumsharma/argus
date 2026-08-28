"""Stage 4 for the COD loss type -- refusal-specific behavioral features, same
"still fully deterministic" discipline as the referral-abuse features."""

import networkx as nx
import pandas as pd


def compute_features(G: nx.Graph, members: set, accounts: pd.DataFrame, orders: pd.DataFrame) -> dict:
    members = list(members)
    size = len(members)

    sub = G.subgraph(members)
    n_edges = sub.number_of_edges()
    max_edges = size * (size - 1) / 2
    edge_density = n_edges / max_edges if max_edges > 0 else 0.0
    signals_present = set()
    for _, _, d in sub.edges(data=True):
        signals_present |= d["signals"]

    acc_sub = accounts[accounts.user_id.isin(members)]
    top_addr_count = acc_sub.delivery_address_hash.value_counts().max() if len(acc_sub) else 0
    shared_address = top_addr_count >= 2
    shared_address_frac = top_addr_count / size if size else 0.0

    ord_sub = orders[orders.user_id.isin(members)]
    n_orders = len(ord_sub)
    cod_orders = ord_sub[ord_sub.payment_method == "COD"]
    n_cod = len(cod_orders)
    cod_fraction = n_cod / n_orders if n_orders else 0.0
    n_refused = (cod_orders.delivery_status == "refused").sum()
    refusal_rate = n_refused / n_cod if n_cod else None
    avg_order_value = ord_sub.order_value.mean() if n_orders else None
    order_value_cv = (ord_sub.order_value.std() / avg_order_value) if n_orders >= 2 and avg_order_value else None

    return {
        "size": size, "n_edges": n_edges, "edge_density": round(edge_density, 4),
        "signals_present": sorted(signals_present),
        "shared_address": bool(shared_address), "shared_address_frac": round(shared_address_frac, 3),
        "n_orders": n_orders, "n_cod_orders": n_cod, "cod_fraction": round(cod_fraction, 3),
        "refusal_rate": round(refusal_rate, 3) if refusal_rate is not None else None,
        "avg_order_value": round(avg_order_value, 2) if avg_order_value is not None else None,
        "order_value_cv": round(order_value_cv, 4) if order_value_cv is not None else None,
    }
