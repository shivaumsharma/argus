import sys
from pathlib import Path

import streamlit as st

FRONTEND_DIR = Path(__file__).resolve().parents[1]
if str(FRONTEND_DIR) not in sys.path:
    sys.path.insert(0, str(FRONTEND_DIR))

from shared import ACTION_COLOR, MODE_LABEL, bump_version, ensure_version, get_graph, graph_viz  # noqa: E402
from backend import snapshot  # noqa: E402

st.title(":material/bolt: Live injection")
st.caption(
    "Drop a brand-new synthetic ring into the running system right now and watch it get flagged — "
    "the pipeline reruns for real, against the real dataset, in a few seconds."
)

version = ensure_version()

with st.container(border=True):
    st.markdown(":material/warning: **This mutates the live dataset.**")
    st.write(
        "Injecting appends real rows to `data/raw/*.csv` and reruns the full pipeline — it does not run "
        "against a throwaway copy. The eval numbers reported in the README were measured on a frozen, "
        "single-pass snapshot; injecting a ring here will change the dataset until you reset it below."
    )
    if not snapshot.has_snapshot():
        st.error("No frozen snapshot found yet. Run `python -m backend.snapshot` once before using this page.",
                  icon=":material/error:")
    if st.button(":material/restart_alt: Reset to frozen snapshot", width="stretch"):
        with st.spinner("Restoring the frozen dataset..."):
            snapshot.reset_to_snapshot(verbose=False)
        bump_version()
        st.toast("Reset to the frozen snapshot.", icon=":material/check_circle:")
        st.rerun()

st.space("medium")

col1, col2, col3 = st.columns([1, 1, 1])
with col1:
    kind = st.segmented_control("Ring type", ["hard", "soft"], default="hard",
                                 help="Hard-signal: shares a device or payment instrument. Soft-signal: only IP overlap + referral timing.")
with col2:
    size = st.slider("Accounts in the ring", min_value=3, max_value=15, value=9)
with col3:
    st.write("")
    st.write("")
    go = st.button(":material/rocket_launch: Inject now", type="primary", width="stretch")

if go:
    from backend.live_injection import inject_and_detect
    with st.spinner(f"Injecting a {size}-account {kind}-signal ring and rerunning the pipeline..."):
        outcome = inject_and_detect(kind=kind, size=size, verbose=False)
    bump_version()
    st.session_state["last_injection"] = outcome
    st.rerun()

st.space("large")

outcome = st.session_state.get("last_injection")
if not outcome:
    st.info("Nothing injected yet this session.", icon=":material/info:")
    st.stop()

st.subheader("Result")
st.caption(f"Injected accounts: {outcome['members'][0]} .. {outcome['members'][-1]} ({outcome['size']} total, {outcome['kind']}-signal)")

if outcome["status"] == "not_clustered":
    st.error("The injected ring did not form a candidate cluster at all — Stage 2/3 never grouped it.", icon=":material/error:")
elif outcome["status"] == "clustered_not_flagged":
    st.warning(f"Clustered as **{outcome['matched_cluster']['cluster_id']}** but Stage 5 did **not** flag it.", icon=":material/warning:")
    st.write(f"Reason: {outcome['filter_reason']}")
else:
    case = outcome["case"]
    matched = outcome["matched_cluster"]
    st.success(f"Flagged as **{matched['cluster_id']}** — real-time, this run.", icon=":material/check_circle:")

    header_cols = st.columns([2, 2, 3])
    header_cols[0].badge(f"{matched['detection_stage']}-signal", color="red" if matched["detection_stage"] == "hard" else "violet")
    action = case["recommended_action"]
    header_cols[1].badge(action, color=ACTION_COLOR.get(action, "gray"))
    header_cols[2].markdown(f"confidence **{case['confidence']:.2f}** · {MODE_LABEL.get(case['mode'], case['mode'])}")

    st.markdown(case["case_summary"])
    if case.get("key_evidence"):
        st.markdown("**Key evidence:**")
        for ev in case["key_evidence"]:
            st.markdown(f"- {ev}")

    with st.expander("Graph", icon=":material/hub:", expanded=True):
        G = get_graph(version)
        html_path = graph_viz.render_cluster_graph(G, matched["members"], node_color="#c0392b",
                                                     cache_key=f"injected_{matched['cluster_id']}")
        st.iframe(src=html_path, height=380)
