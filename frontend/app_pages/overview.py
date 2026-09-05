import sys
from pathlib import Path

import streamlit as st

FRONTEND_DIR = Path(__file__).resolve().parents[1]
if str(FRONTEND_DIR) not in sys.path:
    sys.path.insert(0, str(FRONTEND_DIR))

from shared import (  # noqa: E402
    cached_confounder_rows,
    cached_eval_report,
    cached_ring_rows,
    ensure_version,
    get_graph,
    graph_viz,
    reporting,
)

version = ensure_version()

# --- Hero: one line, not a paragraph ---
st.title(":material/hub: Argus")
st.markdown(
    "##### A farmed account looks ordinary alone. A *ring* of them doesn't — the fraud only shows up "
    "when you look at accounts **together**. So instead of scoring one account at a time, this system "
    "builds a graph of who's connected to whom, and clusters it."
)
st.caption(
    ":material/travel_explore: This is a general coordinated-fraud/collusion-ring detector, not a "
    "single-scenario tool. The demo below runs on a synthetic promo/referral-abuse dataset for a concrete "
    "walkthrough, and the same unmodified clustering mechanism is separately validated against **5 real, "
    "independently-labeled fraud datasets** (review fraud, Bitcoin, card transactions) — see "
    "**External Validation** in the sidebar for that evidence."
)

eval_report = cached_eval_report(version)
if not eval_report:
    st.warning(
        "No pipeline output yet. Click **Re-run detection** in the sidebar, then **Re-run LLM investigation**, "
        "to generate the numbers and cases shown on this page.",
        icon=":material/warning:",
    )
    st.stop()

# --- See it, don't just read about it: a real ring next to a real lookalike ---
rings, confounders = reporting.load_ground_truth()
hard_rings = {rid: r for rid, r in rings.items() if r["type"] == "hard"}
ring_id, ring = sorted(hard_rings.items(), key=lambda kv: abs(len(kv[1]["members"]) - 10))[0]

lookalike_types = {"office", "hostel"}
lookalikes = {cid: c for cid, c in confounders.items() if c["type"] in lookalike_types}
conf_id, conf = sorted(lookalikes.items(), key=lambda kv: abs(len(kv[1]["members"]) - len(ring["members"])))[0]

G = get_graph(version)
ring_html = graph_viz.render_cluster_graph(G, ring["members"], node_color="#c0392b", cache_key=f"overview_{ring_id}_v2", height=320, show_edge_labels=False)
conf_html = graph_viz.render_cluster_graph(G, conf["members"], node_color="#27ae60", cache_key=f"overview_{conf_id}_v2", height=320, show_edge_labels=False)

st.space("small")
g1, g2 = st.columns(2)
with g1:
    st.markdown(":red[**This is a fraud ring**]")
    st.caption(f"{ring_id} · {len(ring['members'])} accounts · flagged `HOLD_BONUS`")
    st.iframe(src=ring_html, height=320)
    st.caption(
        ":violet[**purple**]/:red[**red**] edges = shared payment instrument / device — near-certain signal. "
        "Every account signed up within days, claimed a bonus within hours, and went silent."
    )
with g2:
    st.markdown(":green[**This is a real hostel — correctly left alone**]")
    st.caption(f"{conf_id} · {len(conf['members'])} accounts · same wifi, never flagged")
    st.iframe(src=conf_html, height=320)
    st.caption(
        "Every edge is :orange[**orange**] — IP overlap only, no shared device or instrument. Activity is "
        "spread over months with normal, varied spending. Same shape of graph, opposite verdict."
    )

st.space("medium")

# --- Headline KPIs ---
ring_rows = cached_ring_rows(version)
conf_rows = cached_confounder_rows(version)
n_accounts = G.number_of_nodes()
rings_caught = sum(1 for r in ring_rows if r["detected"])
confounders_spared = sum(1 for r in conf_rows if not r["wrongly_flagged"])
overall = eval_report["overall"]

with st.container(horizontal=True):
    st.metric("Accounts analyzed", f"{n_accounts:,}", border=True)
    st.metric("Rings caught", f"{rings_caught} / {len(ring_rows)}", border=True)
    st.metric("Confounders correctly spared", f"{confounders_spared} / {len(conf_rows)}", border=True)
    st.metric("Confounder false-positive rate", f"{overall['confounder_false_positive_rate']:.1%}", border=True)
st.caption(
    "These four numbers are from the primary synthetic (referral-abuse) demo dataset specifically. For "
    "results on real-world data this system never generated itself, see External Validation."
)

st.space("large")

# --- How it works, compressed ---
st.subheader("How it works")
steps = [
    (":material/hub:", "Build the graph", "shared device / instrument / IP / referral = an edge"),
    (":material/link:", "Hard-signal clusters", "connected components on the near-certain edges"),
    (":material/share:", "Soft-signal clusters", "community detection over everything else"),
    (":material/query_stats:", "Score each cluster", "burst timing, templating, dormancy"),
    (":material/verified_user:", "Filter confounders", "actively looks for evidence it's legit"),
    (":material/smart_toy:", "LLM writes the case", "only for survivors; bounded to 3 actions"),
]
with st.container(horizontal=True):
    for icon, title, desc in steps:
        with st.container(border=True, width=190):
            st.markdown(f"{icon} **{title}**")
            st.caption(desc)
st.caption("Five deterministic stages decide what's suspicious. The LLM only writes up a case *after* that decision is made — it never decides.")

st.space("large")

# --- Cost framing ---
with st.container(border=True):
    st.markdown(":material/balance: **A missed ring costs money. A false alarm costs a delay.**")
    st.write(
        "A missed ring means paid-out fraudulent bonuses. A wrongly-flagged legitimate cluster costs, at most, "
        "a delayed payout pending human review — nothing here auto-executes. Every recommendation is bounded to "
        "`HOLD_BONUS` / `MANUAL_REVIEW` / `NO_ACTION`, and **no code path anywhere bans, blocks, or moves money.**"
    )

st.space("large")

# --- Navigation ---
st.subheader("Where to look next")
nav_cols = st.columns(4)
with nav_cols[0]:
    with st.container(border=True):
        st.markdown(":material/travel_explore: **External Validation**")
        st.caption("The general-capability proof: this same detector on 5 real, independently-labeled fraud datasets.")
        st.page_link("app_pages/external_validation.py", label="Open external validation", icon=":material/arrow_forward:")
with nav_cols[1]:
    with st.container(border=True):
        st.markdown(":material/flag: **Flagged clusters**")
        st.caption("Every cluster the demo pipeline flagged, with its evidence, its graph, and the LLM's case writeup.")
        st.page_link("app_pages/flagged_clusters.py", label="Open flagged clusters", icon=":material/arrow_forward:")
with nav_cols[2]:
    with st.container(border=True):
        st.markdown(":material/verified_user: **Confounders left alone**")
        st.caption("Every household, hostel, and office network that looks similar but was correctly not flagged.")
        st.page_link("app_pages/confounders.py", label="Open confounders", icon=":material/arrow_forward:")
with nav_cols[3]:
    with st.container(border=True):
        st.markdown(":material/monitoring: **Metrics**")
        st.caption("Held-out precision/recall, hard vs. soft signal, and the confounder false-positive rate.")
        st.page_link("app_pages/metrics.py", label="Open metrics", icon=":material/arrow_forward:")
