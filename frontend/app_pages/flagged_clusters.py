import sys
from pathlib import Path

import pandas as pd
import streamlit as st

FRONTEND_DIR = Path(__file__).resolve().parents[1]
if str(FRONTEND_DIR) not in sys.path:
    sys.path.insert(0, str(FRONTEND_DIR))

from shared import ACTION_COLOR, MODE_ICON, MODE_LABEL, STAGE_COLOR, cached_all_clusters, cached_cod_clusters, ensure_version, get_cod_graph, get_graph, graph_viz  # noqa: E402

st.title(":material/flag: Flagged clusters")

loss_type = st.segmented_control("Example scenario", ["Referral Abuse", "COD Collusion"], default="Referral Abuse")
st.caption(
    ":material/info: Two synthetic scenarios, shown here to make the mechanism concrete — the underlying "
    "graph-clustering detector isn't limited to these. See **External Validation** for the same approach run "
    "against 5 real, independently-labeled fraud datasets (review fraud, Bitcoin, card transactions)."
)

if loss_type == "COD Collusion":
    st.caption(
        "Stretch scope: same Stage 2/3 clustering, reused unchanged, fed shared delivery-address and "
        "phone-number-prefix edges instead of device/instrument/IP/referral. No LLM narrative layer exists "
        "for this loss type — Stage 5's deterministic reason is the whole case. See `docs/SECOND_LOSS_TYPE.md`."
    )
    version = ensure_version()
    cod_all = cached_cod_clusters(version)
    cod_flagged = [c for c in cod_all if c["flagged"]]
    if not cod_flagged:
        st.info("No flagged COD clusters yet. Run `python -m backend.cod_collusion.run`.", icon=":material/info:")
        st.stop()

    with st.container(horizontal=True):
        st.metric("Flagged clusters", len(cod_flagged), border=True)
        st.metric("Hard-signal", sum(1 for c in cod_flagged if c["detection_stage"] == "hard"), border=True)
        st.metric("Soft-signal", sum(1 for c in cod_flagged if c["detection_stage"] == "soft"), border=True)

    st.space("medium")
    cod_search = st.text_input("Search cluster ID", placeholder="e.g. CC0001", key="cod_search")
    cod_rows = [c for c in cod_flagged if not cod_search or cod_search.lower() in c["cluster_id"].lower()]
    st.caption(f"Showing {len(cod_rows)} of {len(cod_flagged)} flagged COD clusters.")

    cod_table = pd.DataFrame([{
        "Cluster": c["cluster_id"], "Stage": c["detection_stage"], "Size": c["features"]["size"],
        "Refusal rate": c["features"]["refusal_rate"], "COD fraction": c["features"]["cod_fraction"],
        "Avg order value": c["features"]["avg_order_value"], "Shared address": c["features"]["shared_address"],
    } for c in cod_rows])
    cod_event = st.dataframe(
        cod_table, hide_index=True, width="stretch", height=min(360, 46 + 35 * len(cod_table)),
        on_select="rerun", selection_mode="single-row",
        column_config={"Refusal rate": st.column_config.ProgressColumn(min_value=0, max_value=1, format="%.0%%")},
    )
    cod_selected_idx = cod_event.selection.rows[0] if cod_event.selection.rows else 0
    cod_selected = cod_rows[cod_selected_idx] if cod_rows else None

    if cod_selected is None:
        st.info("No clusters match this filter.", icon=":material/info:")
        st.stop()

    st.space("large")
    st.subheader(f"Case: {cod_selected['cluster_id']}")
    cf = cod_selected["features"]
    st.badge(f"{cod_selected['detection_stage']}-signal", color=STAGE_COLOR.get(cod_selected["detection_stage"], "gray"))
    st.markdown(f"**Deterministic filter reason**: {cod_selected['filter_reason']}")

    cod_detail_cols = st.columns(2)
    with cod_detail_cols[0]:
        with st.expander("Stage 4 feature scores", icon=":material/query_stats:", expanded=True):
            fc1, fc2 = st.columns(2)
            fc1.metric("Size", cf["size"])
            fc1.metric("Refusal rate", f"{cf['refusal_rate']:.0%}")
            fc1.metric("COD fraction", f"{cf['cod_fraction']:.0%}")
            fc2.metric("Avg order value", f"Rs {cf['avg_order_value']:,.0f}")
            fc2.metric("Order-value CV", cf.get("order_value_cv", "n/a"))
            fc2.metric("Shared address", "Yes" if cf["shared_address"] else "No")
            st.caption(f"Signals present: {', '.join(cf['signals_present']) or 'none'}")
    with cod_detail_cols[1]:
        with st.expander("Graph", icon=":material/hub:", expanded=True):
            G_cod = get_cod_graph(version)
            html_path = graph_viz.render_cluster_graph(G_cod, cod_selected["members"], node_color="#c0392b",
                                                        cache_key=f"cod_{cod_selected['cluster_id']}", height=380)
            st.iframe(src=html_path, height=380)
    st.stop()

st.caption(
    "Every candidate cluster that survived Stage 5's confounder filter. Each one already has a "
    "deterministic reason before any LLM ever saw it — the case writeup below explains that reason "
    "in plain English and recommends one bounded action for a human to execute."
)

version = ensure_version()
all_clusters = cached_all_clusters(version)
flagged = [c for c in all_clusters if c["flagged"]]

if not flagged:
    st.info("No flagged clusters yet. Run the pipeline from the sidebar.", icon=":material/info:")
    st.stop()

# --- Summary ---
n_live = sum(1 for c in flagged if c.get("llm_mode") in ("anthropic", "gemini"))
with st.container(horizontal=True):
    st.metric("Flagged clusters", len(flagged), border=True)
    st.metric("Hard-signal", sum(1 for c in flagged if c["detection_stage"] == "hard"), border=True)
    st.metric("Soft-signal", sum(1 for c in flagged if c["detection_stage"] == "soft"), border=True)
    st.metric("Hold bonus", sum(1 for c in flagged if c["llm_recommended_action"] == "HOLD_BONUS"), border=True)
    st.metric("Manual review", sum(1 for c in flagged if c["llm_recommended_action"] == "MANUAL_REVIEW"), border=True)
    st.metric("Written by live LLM", f"{n_live}/{len(flagged)}", border=True,
              help="Cases written by a real, live LLM call (primary or fallback provider) vs. the deterministic template fallback.")

st.space("medium")

# --- Filters ---
filter_cols = st.columns([1, 1.4, 2])
with filter_cols[0]:
    stage_filter = st.segmented_control("Detection stage", ["All", "hard", "soft"], default="All")
with filter_cols[1]:
    actions_present = sorted({c["llm_recommended_action"] for c in flagged if c["llm_recommended_action"]})
    action_filter = st.pills("Recommended action", actions_present, selection_mode="multi", default=actions_present)
with filter_cols[2]:
    search = st.text_input("Search cluster ID", placeholder="e.g. C0002", label_visibility="visible")

rows = flagged
if stage_filter and stage_filter != "All":
    rows = [c for c in rows if c["detection_stage"] == stage_filter]
if action_filter:
    rows = [c for c in rows if c["llm_recommended_action"] in action_filter]
if search:
    rows = [c for c in rows if search.lower() in c["cluster_id"].lower()]
rows = sorted(rows, key=lambda c: (c["llm_confidence"] is None, -(c["llm_confidence"] or 0)))

st.caption(f"Showing {len(rows)} of {len(flagged)} flagged clusters.")

table_df = pd.DataFrame([{
    "Cluster": c["cluster_id"],
    "Stage": c["detection_stage"],
    "Size": c["features"]["size"],
    "Action": c["llm_recommended_action"] or "pending",
    "Confidence": c["llm_confidence"],
    "Written by": MODE_LABEL.get(c.get("llm_mode"), "-"),
    "Signup span (d)": c["features"]["signup_span_days"],
    "Order CV": c["features"]["order_value_cv"],
    "Claim-then-dormant": c["features"]["claim_then_dormant_frac"],
} for c in rows])

event = st.dataframe(
    table_df, hide_index=True, width="stretch", height=min(360, 46 + 35 * len(table_df)),
    on_select="rerun", selection_mode="single-row",
    column_config={"Confidence": st.column_config.ProgressColumn(min_value=0, max_value=1, format="%.2f")},
)

selected_idx = event.selection.rows[0] if event.selection.rows else 0
selected = rows[selected_idx] if rows else None

if selected is None:
    st.info("No clusters match these filters.", icon=":material/info:")
    st.stop()

st.space("large")
st.subheader(f"Case: {selected['cluster_id']}")

c = selected
f = c["features"]
header_cols = st.columns([2, 2, 3])
header_cols[0].badge(f"{c['detection_stage']}-signal", color=STAGE_COLOR.get(c["detection_stage"], "gray"))
action = c["llm_recommended_action"] or "PENDING"
header_cols[1].badge(action, color=ACTION_COLOR.get(action, "gray"))
conf = c["llm_confidence"]
header_cols[2].markdown(f"confidence **{conf:.2f}**" if conf is not None else "_not yet investigated_")

st.markdown(c["llm_case_summary"] or "_Run the LLM investigation stage from the sidebar to generate a case summary._")

if c["llm_key_evidence"]:
    st.markdown("**Key evidence:**")
    for ev in c["llm_key_evidence"]:
        st.markdown(f"- {ev}")

if c.get("llm_mode"):
    icon = MODE_ICON.get(c["llm_mode"], ":material/info:")
    label = MODE_LABEL.get(c["llm_mode"], c["llm_mode"])
    st.caption(f"{icon} Case written by: **{label}**")

detail_cols = st.columns(2)
with detail_cols[0]:
    with st.expander("Stage 4 feature scores", icon=":material/query_stats:"):
        fc1, fc2, fc3 = st.columns(3)
        fc1.metric("Size", f["size"])
        fc1.metric("Edge density", f["edge_density"])
        fc2.metric("Signup span (days)", f["signup_span_days"])
        fc2.metric("Order-value CV", f["order_value_cv"] if f["order_value_cv"] is not None else "n/a")
        fc3.metric("Claim velocity (h)", f["bonus_claim_velocity_hours"] if f["bonus_claim_velocity_hours"] is not None else "n/a")
        fc3.metric("Post-signup engagement", f["post_signup_engagement"])
        st.caption(f"Signals present: {', '.join(f['signals_present']) or 'none'}")
        st.caption(f"Deterministic filter reason: {c['filter_reason']}")
with detail_cols[1]:
    with st.expander("Graph", icon=":material/hub:", expanded=True):
        G = get_graph(version)
        html_path = graph_viz.render_cluster_graph(G, c["members"], node_color="#c0392b", cache_key=c["cluster_id"], height=380)
        st.iframe(src=html_path, height=380)
