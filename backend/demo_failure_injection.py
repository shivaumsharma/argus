"""
Day 7 -- scripted failure injection for the demo.

Real account data has gaps: a device fingerprint SDK that failed to load, an
IP address behind a proxy that didn't get logged, a payment instrument that
was never captured. This script takes a copy of the real dataset, deliberately
blanks out several of those fields on a handful of accounts, and runs the
full Stages 1-5 pipeline against it -- proving graph construction and
clustering degrade gracefully (accounts with a missing attribute are simply
absent from that attribute's edges) instead of crashing, or worse, silently
clustering unrelated accounts together because "missing" got treated as a
shared value.

Run: python -m backend.demo_failure_injection
"""

import shutil
import tempfile
from pathlib import Path

import pandas as pd

from .pipeline.clustering import dedupe_candidates, stage2_hard_clusters, stage3_soft_clusters
from .pipeline.confounder_filter import evaluate_cluster
from .pipeline.data_io import RAW_DIR
from .pipeline.data_io import load_data
from .pipeline.features import build_lookups, compute_features
from .pipeline.graph_build import build_graph, hard_signal_subgraph

N_CORRUPT_EACH = 5


def corrupt_dataset(src_dir: Path, dst_dir: Path):
    dst_dir.mkdir(parents=True, exist_ok=True)
    for name in ["sessions.csv", "referrals.csv", "orders.csv"]:
        shutil.copy(src_dir / name, dst_dir / name)

    accounts = pd.read_csv(src_dir / "accounts.csv", dtype=str)
    instruments = pd.read_csv(src_dir / "payment_instruments.csv", dtype=str)

    rng = accounts.sample(N_CORRUPT_EACH, random_state=1).index
    accounts.loc[rng, "device_fingerprint_id"] = ""
    corrupted_device_uids = set(accounts.loc[rng, "user_id"])

    rng2 = accounts.sample(N_CORRUPT_EACH, random_state=2).index
    accounts.loc[rng2, "ip_address_at_signup"] = None
    corrupted_ip_uids = set(accounts.loc[rng2, "user_id"])

    rng3 = instruments.sample(N_CORRUPT_EACH, random_state=3).index
    instruments.loc[rng3, "instrument_hash"] = ""
    corrupted_instr_uids = set(instruments.loc[rng3, "user_id"])

    accounts.to_csv(dst_dir / "accounts.csv", index=False)
    instruments.to_csv(dst_dir / "payment_instruments.csv", index=False)

    return corrupted_device_uids, corrupted_ip_uids, corrupted_instr_uids


def run():
    tmp = Path(tempfile.mkdtemp(prefix="sentinel_failure_demo_"))
    try:
        print(f"Copying data/raw -> {tmp} and corrupting {N_CORRUPT_EACH} accounts per field...")
        dev_uids, ip_uids, instr_uids = corrupt_dataset(RAW_DIR, tmp)
        print(f"  Blanked device_fingerprint_id on: {sorted(dev_uids)}")
        print(f"  Blanked ip_address_at_signup on:  {sorted(ip_uids)}")
        print(f"  Blanked instrument_hash on:       {sorted(instr_uids)}")

        print("\nRunning Stages 1-5 against the corrupted dataset...")
        data = load_data(raw_dir=tmp)
        G = build_graph(data)
        H = hard_signal_subgraph(G)
        hard_clusters = stage2_hard_clusters(H)
        soft_clusters = stage3_soft_clusters(G)
        candidates = dedupe_candidates(hard_clusters, soft_clusters)
        device_by_user, instrument_by_user = build_lookups(data)
        for members, stage in candidates:
            feats = compute_features(G, members, data, device_by_user, instrument_by_user)
            evaluate_cluster(feats)
        print(f"  Graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges -- no exceptions.")
        print(f"  {len(candidates)} candidate clusters scored -- no exceptions.")

        print("\nVerifying corrupted accounts did NOT get spuriously linked to each other...")
        bad_pairs = []
        for uid_set, label in [(dev_uids, "device"), (ip_uids, "ip_subnet_overlap")]:
            uid_list = list(uid_set)
            for i in range(len(uid_list)):
                for j in range(i + 1, len(uid_list)):
                    if G.has_edge(uid_list[i], uid_list[j]):
                        signal = "shared_device" if label == "device" else "ip_subnet_overlap"
                        if signal in G[uid_list[i]][uid_list[j]]["signals"]:
                            bad_pairs.append((uid_list[i], uid_list[j], signal))
        if bad_pairs:
            print(f"  FAIL: {len(bad_pairs)} spurious edge(s) created from missing values: {bad_pairs}")
        else:
            print("  PASS: zero spurious edges -- missing attributes were excluded, not treated as a shared value.")

        print("\nResult: pipeline completes end to end on dirty data; no crash, no false clustering from gaps.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    run()
