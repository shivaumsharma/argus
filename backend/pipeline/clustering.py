"""
Stage 2 -- hard-signal clustering: connected components over shared-device /
shared-instrument edges only. Near-certain ring signal.

Stage 3 -- soft-signal clustering: weighted community detection (Louvain) over
the full graph (all edge types), to surface rings that share no device or
instrument -- only IP overlap and referral-chain timing.
"""

import networkx as nx
import community as community_louvain  # python-louvain

MIN_HARD_SIZE = 2
MIN_SOFT_SIZE = 3
LOUVAIN_RESOLUTION = 1.3


def stage2_hard_clusters(H: nx.Graph) -> list[set]:
    clusters = []
    for comp in nx.connected_components(H):
        if len(comp) >= MIN_HARD_SIZE:
            clusters.append(set(comp))
    return clusters


def stage3_soft_clusters(G: nx.Graph, resolution: float = LOUVAIN_RESOLUTION) -> list[set]:
    # Louvain needs a graph with at least one edge; isolated nodes form singleton communities we discard anyway.
    if G.number_of_edges() == 0:
        return []
    partition = community_louvain.best_partition(G, weight="weight", resolution=resolution, random_state=42)
    by_community = {}
    for uid, comm_id in partition.items():
        by_community.setdefault(comm_id, set()).add(uid)
    return [members for members in by_community.values() if len(members) >= MIN_SOFT_SIZE]


def dedupe_candidates(hard_clusters: list[set], soft_clusters: list[set], overlap_thresh: float = 0.7):
    """Union candidates from both stages. A soft-signal community that mostly
    reproduces an already-found hard cluster is dropped in favor of the hard
    version (stronger, simpler evidence). Returns list of (members, stage)."""
    candidates = [(members, "hard") for members in hard_clusters]
    for soft in soft_clusters:
        is_dup = False
        for hard in hard_clusters:
            overlap = len(soft & hard) / len(hard)
            if overlap >= overlap_thresh:
                is_dup = True
                break
        if not is_dup:
            candidates.append((soft, "soft"))
    return candidates
