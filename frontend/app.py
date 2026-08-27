import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import db, graph_viz, reporting  # noqa: E402
from backend.pipeline import run_pipeline  # noqa: E402
from backend.pipeline.data_io import load_data  # noqa: E402
from backend.pipeline.graph_build import build_graph  # noqa: E402

st.set_page_config(page_title="Abuse-Ring Sentinel", layout="wide", page_icon=":material/hub:")

ACTION_COLOR = {"HOLD_BONUS": "red", "MANUAL_REVIEW": "orange", "NO_ACTION": "gray"}
STAGE_COLOR = {"hard": "red", "soft": "violet"}


@st.cache_resource(show_spinner=False)
def get_graph(_version: int):
    data = load_data()
    return build_graph(data)


def bump_version():
    st.session_state["data_version"] = st.session_state.get("data_version", 0) + 1
    get_graph.clear()


if "data_version" not in st.session_state:
    st.session_state["data_version"] = 0

st.title("Promo/Referral Abuse-Ring Sentinel")
st.markdown(
    "A single farmed account looks ordinary — real-looking phone number, plausible order, "
    "no red flag. The fraud is only visible when accounts are looked at **together**: a shared "
    "device, a shared payment instrument, an overlapping IP, a suspiciously tight referral chain. "
    "This is a **graph problem, not a row-classification problem** — every flag below traces back "
    "to a specific, inspectable shared attribute, and every recommendation is bounded "
    "(`HOLD_BONUS` / `MANUAL_REVIEW` / `NO_ACTION`). Nothing here can ban, block, or move money; "
    "a human always executes the final action."
)

with st.sidebar:
    st.subheader("Pipeline controls")
    if st.button(":material/refresh: Re-run detection (Stages 1-5)", width="stretch"):
        with st.spinner("Building graph, clustering, scoring, filtering..."):
            run_pipeline.run(verbose=False)
        bump_version()
        st.success("Detection pipeline re-run.")
        st.rerun()

    if st.button(":material/smart_toy: Re-run LLM investigation (Stage 8)", width="stretch"):
        from backend.llm_investigate import investigate_all
        with st.spinner("Investigating flagged clusters..."):
            investigate_all(verbose=False)
        st.success("LLM investigation re-run.")
        st.rerun()

    st.caption(
        "LLM stage falls back to a clearly-labeled deterministic template writeup "
        "when no Anthropic API credentials are available."
    )

all_clusters = db.get_all_clusters()
flagged_clusters = sorted(
    [c for c in all_clusters if c["flagged"]],
    key=lambda c: (c["llm_confidence"] is None, -(c["llm_confidence"] or 0)),
)
eval_report = reporting.load_eval_report()

if not all_clusters:
    st.warning("No pipeline output found yet. Click **Re-run detection** in the sidebar to generate it.")
    st.stop()

tab_cases, tab_confounders, tab_graph, tab_metrics, tab_audit = st.tabs([
    ":material/flag: Flagged clusters",
    ":material/verified_user: Confounders left alone",
    ":material/hub: Graph explorer",
    ":material/monitoring: Metrics",
    ":material/history: Audit log",
])

# ---------------------------------------------------------------------------
# Tab 1 -- Case cards
# ---------------------------------------------------------------------------
with tab_cases:
    st.caption(f"{len(flagged_clusters)} clusters survived the deterministic Stage 5 confounder filter.")
    if not flagged_clusters:
        st.info("No flagged clusters. Run the pipeline from the sidebar.")

    for c in flagged_clusters:
        f = c["features"]
        with st.container(border=True):
            header_cols = st.columns([3, 2, 2, 2])
            header_cols[0].markdown(f"**{c['cluster_id']}**")
            header_cols[1].badge(f"{c['detection_stage']}-signal", color=STAGE_COLOR.get(c["detection_stage"], "gray"))
            action = c["llm_recommended_action"] or "PENDING"
            header_cols[2].badge(action, color=ACTION_COLOR.get(action, "gray"))
            conf = c["llm_confidence"]
            header_cols[3].markdown(f"confidence **{conf:.2f}**" if conf is not None else "_not yet investigated_")

            st.markdown(c["llm_case_summary"] or "_Run the LLM investigation stage from the sidebar to generate a case summary._")

            if c["llm_key_evidence"]:
                st.markdown("**Key evidence:**")
                for ev in c["llm_key_evidence"]:
                    st.markdown(f"- {ev}")

            if c.get("llm_mode") == "fallback_template":
                st.caption(":material/info: Template fallback used (no LLM credentials available for this run).")

            with st.expander("Stage 4 feature scores"):
                fc1, fc2, fc3 = st.columns(3)
                fc1.metric("Size", f["size"])
                fc1.metric("Edge density", f["edge_density"])
                fc2.metric("Signup span (days)", f["signup_span_days"])
                fc2.metric("Order-value CV", f["order_value_cv"] if f["order_value_cv"] is not None else "n/a")
                fc3.metric("Claim velocity (h)", f["bonus_claim_velocity_hours"] if f["bonus_claim_velocity_hours"] is not None else "n/a")
                fc3.metric("Post-signup engagement", f["post_signup_engagement"])
                st.caption(f"Signals present: {', '.join(f['signals_present']) or 'none'}")
                st.caption(f"Deterministic filter reason: {c['filter_reason']}")

            with st.expander("Show graph"):
                G = get_graph(st.session_state["data_version"])
                html_path = graph_viz.render_cluster_graph(G, c["members"], node_color="#c0392b", cache_key=c["cluster_id"])
                st.iframe(src=html_path, height=420)

# ---------------------------------------------------------------------------
# Tab 2 -- Confounder callout
# ---------------------------------------------------------------------------
with tab_confounders:
    st.caption(
        "These are planted, legitimate dense clusters (real households, hostels, office networks, "
        "organic referral trees) that share device/IP/referral attributes but show organic behavior. "
        "The whole job of Stage 5 is to leave these alone."
    )
    conf_rows = reporting.confounder_callout_rows()
    n_wrong = sum(1 for r in conf_rows if r["wrongly_flagged"])
    st.metric("Confounder false-positive rate", f"{n_wrong}/{len(conf_rows)} ({n_wrong / len(conf_rows):.1%})" if conf_rows else "n/a")

    for r in conf_rows:
        with st.container(border=True):
            cols = st.columns([3, 2, 2, 3])
            cols[0].markdown(f"**{r['confounder_id']}**  ({r['type']})")
            cols[1].badge(r["difficulty"], color="orange" if r["difficulty"] != "easy" else "gray")
            if r["wrongly_flagged"]:
                cols[2].badge("WRONGLY FLAGGED", color="red")
            else:
                cols[2].badge("correctly left alone", color="green")
            cols[3].markdown(f"{r['size']} accounts")

            st.markdown(r["description"])
            if r["surfaced_as_candidate"]:
                st.caption(f"Matched candidate cluster {r['matched_cluster_id']} -- filter reasoning: \"{r['filter_reason']}\"")
            else:
                st.caption(
                    "Never even surfaced as a clustering candidate -- too structurally diffuse to reach "
                    "Stage 4 scoring at all. The strongest form of 'left alone'."
                )

            if r["features"]:
                with st.expander("Feature scores"):
                    st.json(r["features"])

# ---------------------------------------------------------------------------
# Tab 3 -- Graph explorer
# ---------------------------------------------------------------------------
with tab_graph:
    st.caption("Pick any candidate cluster or any planted ground-truth cluster to inspect its subgraph directly.")
    rings, confounders = reporting.load_ground_truth()

    source = st.selectbox("Source", ["Flagged clusters (detector output)", "All candidate clusters (detector output)",
                                      "Ground-truth rings", "Ground-truth confounders"])
    G = get_graph(st.session_state["data_version"])

    if source == "Flagged clusters (detector output)":
        options = {c["cluster_id"]: c for c in flagged_clusters}
        color = "#c0392b"
    elif source == "All candidate clusters (detector output)":
        options = {c["cluster_id"]: c for c in all_clusters}
        color = "#c0392b"
    elif source == "Ground-truth rings":
        options = {rid: {"members": r["members"], "cluster_id": rid} for rid, r in rings.items()}
        color = "#c0392b"
    else:
        options = {cid: {"members": c["members"], "cluster_id": cid} for cid, c in confounders.items()}
        color = "#27ae60"

    if options:
        pick = st.selectbox("Cluster", list(options.keys()))
        chosen = options[pick]
        st.caption(f"{len(chosen['members'])} accounts")
        html_path = graph_viz.render_cluster_graph(G, chosen["members"], node_color=color, cache_key=f"explorer_{pick}")
        st.iframe(src=html_path, height=520)
        legend_cols = st.columns(4)
        legend_cols[0].markdown(":violet[**Purple edge**] shared instrument")
        legend_cols[1].markdown(":red[**Red edge**] shared device")
        legend_cols[2].markdown(":orange[**Orange edge**] IP subnet overlap")
        legend_cols[3].markdown(":blue[**Blue edge**] referral link")
    else:
        st.info("Nothing to show for this source yet.")

# ---------------------------------------------------------------------------
# Tab 4 -- Metrics
# ---------------------------------------------------------------------------
with tab_metrics:
    if not eval_report:
        st.warning("No eval report found. Run `python -m backend.pipeline.eval` to generate one.")
    else:
        overall = eval_report["overall"]
        st.markdown("#### Held-out evaluation (never used to pick thresholds)")
        with st.container(horizontal=True):
            st.metric("Hard-signal ring recall", f"{overall['hard_signal_recall']:.0%}",
                      help=f"{overall['n_rings_hard']} planted hard-signal rings", border=True)
            st.metric("Soft-signal ring recall", f"{overall['soft_signal_recall']:.0%}",
                      help=f"{overall['n_rings_soft']} planted soft-signal rings -- the real test of the approach", border=True)
            st.metric("Confounder false-positive rate", f"{overall['confounder_false_positive_rate']:.0%}",
                      help=f"{overall['n_confounders']} planted legitimate clusters", border=True)
            st.metric("Cluster-level precision", f"{overall['cluster_precision']:.0%}",
                      help=f"tp={overall['cluster_tp']}, fp={overall['cluster_fp']}", border=True)

        st.markdown(
            "**Cost-weighted framing:** a missed ring means paid-out fraudulent bonuses (direct financial "
            "loss, recoverable only via clawback if caught later). A wrongly-flagged legitimate cluster means "
            "a blocked bonus, customer friction, and possible churn -- but zero automatic action is ever taken "
            "on it (every recommendation is `HOLD_BONUS` / `MANUAL_REVIEW` / `NO_ACTION` for a human to execute), "
            "so the real-world cost of a false positive here is a delayed payout pending review, not a wrongful "
            "punishment. That asymmetry is why Stage 5 is tuned conservatively toward not flagging confounders."
        )

        st.markdown("#### Dev vs. holdout split")
        split_cols = st.columns(2)
        for col, label in zip(split_cols, ["dev", "holdout"]):
            r = eval_report[label]
            with col:
                with st.container(border=True):
                    st.markdown(f"**{label.title()}**")
                    st.markdown(f"Hard recall: **{r['hard_signal_recall']:.0%}** ({r['n_rings_hard']} rings)")
                    st.markdown(f"Soft recall: **{r['soft_signal_recall']:.0%}** ({r['n_rings_soft']} rings)")
                    st.markdown(f"Confounder FP rate: **{r['confounder_false_positive_rate']:.0%}** ({r['n_confounders']} confounders)")
                    st.markdown(f"Cluster precision: **{r['cluster_precision']:.0%}**")

        st.markdown("#### Ring-by-ring detail")
        ring_rows = reporting.ring_recall_rows()
        st.dataframe(
            [{"Ring": r["ring_id"], "Type": r["type"], "Difficulty": r["difficulty"], "Size": r["size"],
              "Detected": "yes" if r["detected"] else "MISSED", "Matched cluster": r["matched_cluster_id"] or "-"}
             for r in ring_rows],
            hide_index=True, width="stretch",
        )

# ---------------------------------------------------------------------------
# Tab 5 -- Audit log
# ---------------------------------------------------------------------------
with tab_audit:
    st.caption(
        "Every clustering decision and every LLM call, with its full input evidence and output -- "
        "the auditability trail the RBI FREE-AI framework expects from AI used in fraud detection."
    )
    log_rows = db.get_audit_log(limit=200)
    st.dataframe(
        [{"id": r["id"], "event": r["event_type"], "cluster": r["cluster_id"], "timestamp": r["timestamp"]}
         for r in log_rows],
        hide_index=True, width="stretch", height=300,
    )
    if log_rows:
        pick_id = st.selectbox("Inspect a log entry", [r["id"] for r in log_rows])
        entry = next(r for r in log_rows if r["id"] == pick_id)
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Input evidence**")
            st.json(entry["input_evidence_json"])
        with c2:
            st.markdown("**Output**")
            st.json(entry["output_json"])
