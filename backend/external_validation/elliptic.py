"""
Elliptic (Weber et al., 2019) -- real Bitcoin transaction graph, real
illicit/licit labels. Included for completeness at lowest priority: it's a
transaction-flow graph with a SINGLE edge type (payment flow), not a
multi-relation graph the way YelpChi/Amazon are -- so there's no natural
hard-vs-soft split to test, which is exactly why this is a weaker match to
what this system claims than the other two datasets. What CAN be tested
honestly: does Stage 2 (connected components) and Stage 3 (Louvain),
imported unchanged from backend.pipeline.clustering exactly as everywhere
else in this repo, find anything meaningful on a real, single-relation
financial graph at all.

Data: huggingface.co/datasets/yhoma/elliptic-bitcoin-dataset (mirror of the
original Elliptic Data Set). This mirror's features file covers 114,634 of
the 203,769 total transactions -- a real subset, not corrupted (every row
has a matching class label; stated here rather than silently worked around).

Run: python -m backend.external_validation.elliptic
"""

from pathlib import Path

import networkx as nx
import pandas as pd

from ..pipeline.clustering import stage2_hard_clusters, stage3_soft_clusters

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data" / "external" / "elliptic"
FLAG_THRESHOLD = 0.5


def run(verbose=True):
    features = pd.read_csv(DATA_DIR / "elliptic_txs_features.csv", header=None, usecols=[0])
    classes = pd.read_csv(DATA_DIR / "elliptic_txs_classes.csv")
    edges = pd.read_csv(DATA_DIR / "elliptic_txs_edgelist.csv")

    node_ids = set(features[0])
    labeled = classes[classes["class"] != "unknown"].copy()
    labeled["class"] = labeled["class"].astype(int)  # 1 = illicit, 2 = licit
    label_map = dict(zip(labeled.txId, (labeled["class"] == 1).astype(int)))  # 1 = illicit, 0 = licit

    both_in = edges.txId1.isin(node_ids) & edges.txId2.isin(node_ids)
    edges_sub = edges[both_in]

    G = nx.from_pandas_edgelist(edges_sub, "txId1", "txId2")
    G.add_nodes_from(node_ids)

    n_labeled = len(label_map)
    n_illicit = sum(label_map.values())
    base_rate = n_illicit / n_labeled if n_labeled else float("nan")

    if verbose:
        print(f"\n=== Elliptic (Weber et al., 2019, via huggingface.co/datasets/yhoma/elliptic-bitcoin-dataset) ===")
        print(f"Nodes with features: {len(node_ids):,} | Edges (both endpoints in subset): {len(edges_sub):,}")
        print(f"Labeled nodes: {n_labeled:,} (illicit: {n_illicit:,}, {base_rate:.1%} base rate)")

    # Stage 2 -- connected components on the raw single-relation graph. A payment edge ("A paid B")
    # is the same KIND of relation as this system's own referral_link -- a transaction between two
    # distinct entities, never treated as hard-signal-worthy anywhere in this repo, unlike
    # device_fingerprint/instrument_hash (which indicate the SAME identity). Reported honestly
    # whichever way it comes out, with the per-component density breakdown that actually explains it
    # (not just asserted): a payment-flow graph produces several large, low-density transaction
    # chains that mix illicit funds moving through mostly-ordinary intermediaries, not one clean
    # signal to exploit.
    hard_clusters = stage2_hard_clusters(G)  # unmodified import
    hard_diag = []
    for members in hard_clusters:
        labeled_members = [m for m in members if m in label_map]
        if not labeled_members:
            continue
        illicit = sum(label_map[m] for m in labeled_members)
        hard_diag.append((len(members), len(labeled_members), illicit, illicit / len(labeled_members)))
    hard_diag.sort(key=lambda r: -r[0])
    largest_cc = hard_diag[0][0] if hard_diag else 0
    if verbose:
        print(f"\nStage 2 (connected components, unchanged): {len(hard_clusters)} components, "
              f"{len(hard_diag)} with >=1 labeled member, largest = {largest_cc:,} nodes "
              f"({largest_cc/len(node_ids):.1%} of the graph)")
        print("  size, labeled, illicit, density -- 5 largest components:")
        for size, n_lab, illicit, density in hard_diag[:5]:
            print(f"    {size:>6,}  {n_lab:>6,}  {illicit:>6,}  {density:>6.1%}")

    # Stage 3 -- Louvain on the same graph (no separate "full weighted graph" exists here since
    # there's only one relation; this IS the full graph).
    soft_clusters = stage3_soft_clusters(G)  # unmodified import
    if verbose:
        print(f"Stage 3 (Louvain, unchanged): {len(soft_clusters)} communities")

    def score(clusters, label):
        rows = []
        for members in clusters:
            labeled_members = [m for m in members if m in label_map]
            if not labeled_members:
                continue
            illicit = sum(label_map[m] for m in labeled_members)
            rows.append({"size": len(members), "n_labeled": len(labeled_members), "illicit": illicit,
                         "density": illicit / len(labeled_members)})
        flagged = [r for r in rows if r["density"] > FLAG_THRESHOLD and r["n_labeled"] >= 3]
        captured_illicit = sum(r["illicit"] for r in flagged)
        captured_total = sum(r["n_labeled"] for r in flagged)
        recall = captured_illicit / n_illicit if n_illicit else float("nan")
        precision = captured_illicit / captured_total if captured_total else float("nan")
        if verbose:
            print(f"\n{label}: {len(rows)} clusters with >=1 labeled member; "
                  f"{len(flagged)} flagged (density > {FLAG_THRESHOLD:.0%}, >=3 labeled members)")
            print(f"  Recall: {recall:.1%} ({captured_illicit}/{n_illicit}) | "
                  f"Precision: {precision:.1%} (vs {base_rate:.1%} base rate)")
        return {"n_clusters": len(rows), "n_flagged": len(flagged), "recall": recall, "precision": precision}

    hard_report = score(hard_clusters, "Stage 2 (connected components)")
    soft_report = score(soft_clusters, "Stage 3 (Louvain)")

    return {
        "n_nodes": len(node_ids), "n_edges": len(edges_sub), "n_labeled": n_labeled,
        "n_illicit": n_illicit, "base_rate": round(base_rate, 4),
        "largest_component": largest_cc, "largest_component_frac": round(largest_cc / len(node_ids), 4),
        "n_components": len(hard_clusters), "n_communities": len(soft_clusters),
        "hard": hard_report, "soft": soft_report,
    }


if __name__ == "__main__":
    run()
