import sys
from pathlib import Path

import streamlit as st

FRONTEND_DIR = Path(__file__).resolve().parents[1]
if str(FRONTEND_DIR) not in sys.path:
    sys.path.insert(0, str(FRONTEND_DIR))

from shared import (  # noqa: E402
    cached_all_clusters,
    cached_cod_clusters,
    cached_cod_ground_truth,
    ensure_version,
    get_cod_graph,
    get_graph,
    graph_viz,
    reporting,
)

st.title(":material/share: Graph explorer")

loss_type = st.segmented_control("Example scenario", ["Referral Abuse", "COD Collusion"], default="Referral Abuse")
is_cod = loss_type == "COD Collusion"

st.caption(
    "Pick any candidate cluster the detector found, or any planted ground-truth cluster, and inspect its "
    "subgraph directly. Edge color shows which shared attribute connects two accounts. These two scenarios "
    "are illustrative, not exhaustive — the same graph-clustering mechanism is validated on real fraud data "
    "in External Validation."
)

version = ensure_version()
if is_cod:
    all_clusters = cached_cod_clusters(version)
    rings, confounders = cached_cod_ground_truth(version)
else:
    all_clusters = cached_all_clusters(version)
    rings, confounders = reporting.load_ground_truth()
flagged = [c for c in all_clusters if c["flagged"]]

if is_cod:
    legend_cols = st.columns(2)
    legend_cols[0].markdown(":violet[**■** Purple]  shared delivery address")
    legend_cols[1].markdown(":orange[**■** Orange]  shared phone-number prefix")
else:
    legend_cols = st.columns(4)
    legend_cols[0].markdown(":violet[**■** Purple]  shared instrument")
    legend_cols[1].markdown(":red[**■** Red]  shared device")
    legend_cols[2].markdown(":orange[**■** Orange]  IP subnet overlap")
    legend_cols[3].markdown(":blue[**■** Blue]  referral link")

pick_cols = st.columns([1.5, 2])
with pick_cols[0]:
    source = st.selectbox("Source", [
        "Flagged clusters (detector output)",
        "All candidate clusters (detector output)",
        "Ground-truth rings",
        "Ground-truth confounders",
    ])

if source == "Flagged clusters (detector output)":
    options = {c["cluster_id"]: c["members"] for c in flagged}
    color = "#c0392b"
elif source == "All candidate clusters (detector output)":
    options = {c["cluster_id"]: c["members"] for c in all_clusters}
    color = "#c0392b"
elif source == "Ground-truth rings":
    options = {rid: r["members"] for rid, r in rings.items()}
    color = "#c0392b"
else:
    options = {cid: c["members"] for cid, c in confounders.items()}
    color = "#27ae60"

with pick_cols[1]:
    pick = st.selectbox("Cluster", list(options.keys()) or ["(none)"])

if not options:
    st.info("Nothing to show for this source yet.", icon=":material/info:")
    st.stop()

members = options[pick]
st.caption(f"{len(members)} accounts in {pick}")
G = get_cod_graph(version) if is_cod else get_graph(version)
html_path = graph_viz.render_cluster_graph(G, members, node_color=color, cache_key=f"explorer_{'cod_' if is_cod else ''}{pick}")
st.iframe(src=html_path, height=560)
