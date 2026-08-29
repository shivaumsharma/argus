import sys
from pathlib import Path

import streamlit as st

FRONTEND_DIR = Path(__file__).resolve().parents[1]
if str(FRONTEND_DIR) not in sys.path:
    sys.path.insert(0, str(FRONTEND_DIR))

from shared import bump_version, ensure_version  # noqa: E402
from backend import db  # noqa: E402
from backend.adversarial_recommender import cadence, governance  # noqa: E402
from backend.adversarial_recommender.run import run_round  # noqa: E402

st.title(":material/shield_with_heart: Adversarial recommendations")
st.caption(
    "Continuously probes the frozen pipeline for evasion gaps and drafts specific, bounded fixes — but "
    "never applies them. **This system recommends. It never modifies live detection logic.** Every "
    "proposal is fully simulated (rings caught *and* confounder false positives, always together) and "
    "held behind a two-gate human approval before it's even marked validated — applying an approved "
    "change to backend/pipeline/ remains a separate, manual, human step outside this system entirely."
)

version = ensure_version()

# --- Run a new round ---
with st.container(border=True):
    allowed, reason = cadence.can_run(force=False)
    c1, c2 = st.columns([3, 1])
    with c1:
        if allowed:
            st.markdown(f":material/check_circle: Cadence gate open — {reason}")
        else:
            st.markdown(f":material/schedule: Cadence gate closed — {reason}")
        st.caption(f"Minimum {cadence.MIN_HOURS_BETWEEN_AUTO_ROUNDS}h between automatic rounds, by default. "
                  "A manual trigger always bypasses the gate — it only throttles the automatic schedule.")
    with c2:
        if st.button(":material/bolt: Run round now", width="stretch", type="primary"):
            with st.spinner("Generating an attack, characterizing any gap, drafting and simulating a fix..."):
                result = run_round(force=True, verbose=False)
            bump_version()
            st.session_state["last_round_result"] = result
            st.rerun()

last_result = st.session_state.get("last_round_result")
if last_result:
    if last_result.get("recommendation_id"):
        st.success(f"Round {last_result['round_number']}: recommendation #{last_result['recommendation_id']} "
                   f"queued for review.", icon=":material/check_circle:")
    elif last_result.get("ran"):
        st.info(f"Round {last_result['round_number']}: {last_result['characterization_reason']} — "
               f"no recommendation this round.", icon=":material/info:")

st.space("large")

recs = db.get_all_recommendations()
pending = [r for r in recs if r["status"] == "pending"]
awaiting_confirm = [r for r in recs if r["status"] == "pending_final_confirmation"]
history = [r for r in recs if r["status"] in ("validated_approved", "rejected", "rejected_after_reeval")]

# --- Gate 1: pending review ---
st.subheader(f":material/pending_actions: Pending review ({len(pending)})")
if not pending:
    st.info("Nothing pending. Run a round above to generate one.", icon=":material/info:")
for rec in pending:
    with st.container(border=True):
        st.markdown(f"**#{rec['id']} — Round {rec['round_number']}** · `{rec['gap_parameter']}`: "
                   f"{rec['current_value']} → **{rec['proposed_value']}**")
        st.caption(rec["attack_description"])
        st.write(rec["rationale"])

        sim = rec["sim_report"]
        m1, m2, m3 = st.columns(3)
        m1.metric("Rings caught (of 80)", f"{sim['rings_caught_after']}", delta=sim["rings_delta"])
        m2.metric("Confounder FPs (of 40)", f"{sim['confounder_fp_after']}", delta=sim["confounder_fp_delta"],
                  delta_color="inverse")
        m3.metric("Closes the gap?", "Yes" if sim["attack_caught_after_fix"] else "No",
                  help="Does this fix actually flag the specific attack that motivated it? A fix can remove "
                       "a cluster from the 'actively cleared' bucket without pushing it into 'flagged' — "
                       "Stage 5 has a conservative middle ground. Shown honestly either way.")
        if not sim["attack_caught_after_fix"]:
            st.warning("This fix does not actually flag the attack that motivated it — it only stops "
                      "actively clearing it. Worth knowing before approving.", icon=":material/warning:")

        confirm_key = f"confirm_reject_{rec['id']}"
        b1, b2 = st.columns(2)
        with b1:
            if st.button(":material/check: Approve → trigger fresh-seed reeval", key=f"approve_{rec['id']}",
                        width="stretch"):
                st.session_state[f"approving_{rec['id']}"] = True
                st.rerun()
        with b2:
            if st.button(":material/close: Reject", key=f"reject_{rec['id']}", width="stretch"):
                st.session_state[confirm_key] = True
                st.rerun()

        if st.session_state.get(f"approving_{rec['id']}"):
            st.info("Approving triggers Stage 5: freeze this change, generate ONE fresh dataset with a "
                   "never-used seed, and run the pipeline once, with and without the change. This may "
                   "take a few seconds.", icon=":material/info:")
            if st.button("Confirm — run the fresh-seed reeval now", key=f"do_reeval_{rec['id']}", type="primary"):
                db.review_recommendation(rec["id"], "approved_pending_reeval", reviewer="dashboard-reviewer")
                with st.spinner("Generating a fresh, never-used-seed dataset and running the pipeline twice "
                                "(baseline vs. proposed)..."):
                    report = governance.revalidate(rec["gap_parameter"], float(rec["proposed_value"]), verbose=False)
                db.record_reeval(rec["id"], report["fresh_seed"], report)
                del st.session_state[f"approving_{rec['id']}"]
                bump_version()
                st.rerun()

        if st.session_state.get(confirm_key):
            st.warning(f"Reject recommendation #{rec['id']}? This is logged either way.", icon=":material/warning:")
            rc1, rc2 = st.columns(2)
            if rc1.button("Confirm reject", key=f"do_reject_{rec['id']}", type="primary"):
                db.review_recommendation(rec["id"], "rejected", reviewer="dashboard-reviewer")
                del st.session_state[confirm_key]
                bump_version()
                st.rerun()
            if rc2.button("Cancel", key=f"cancel_reject_{rec['id']}"):
                del st.session_state[confirm_key]
                st.rerun()

st.space("large")

# --- Gate 2: awaiting final confirmation after fresh-seed reeval ---
st.subheader(f":material/fact_check: Awaiting final confirmation ({len(awaiting_confirm)})")
st.caption("Stage 5's fresh-seed reeval is done — a human reviews that clean run before this is ever "
          "marked validated. Nothing is applied to production either way.")
if not awaiting_confirm:
    st.info("Nothing awaiting final confirmation.", icon=":material/info:")
for rec in awaiting_confirm:
    with st.container(border=True):
        st.markdown(f"**#{rec['id']}** — `{rec['gap_parameter']}`: {rec['current_value']} → "
                   f"**{rec['proposed_value']}** · fresh seed `{rec['reeval_seed']}` (never used before)")
        rr = rec["reeval_report"]
        st.caption(f"Fresh dataset, generated and evaluated exactly once, {rr['elapsed_sec']}s.")
        rc1, rc2 = st.columns(2)
        with rc1:
            st.markdown("**Baseline (this fresh data, no change)**")
            b = rr["baseline"]
            st.write(f"Hard recall: {b['hard_recall']:.1%} · Soft recall: {b['soft_recall']:.1%} · "
                    f"Confounder FP: {b['confounder_fp']}/{b['n_confounders']}")
        with rc2:
            st.markdown("**Proposed (same fresh data, change applied)**")
            p = rr["proposed"]
            st.write(f"Hard recall: {p['hard_recall']:.1%} · Soft recall: {p['soft_recall']:.1%} · "
                    f"Confounder FP: {p['confounder_fp']}/{p['n_confounders']}")

        fc1, fc2 = st.columns(2)
        if fc1.button(":material/verified: Confirm — mark validated", key=f"confirm_final_{rec['id']}",
                     type="primary", width="stretch"):
            db.finalize_recommendation(rec["id"], "validated_approved", reviewer="dashboard-reviewer",
                                       note="Fresh-seed reeval reviewed and accepted.")
            bump_version()
            st.rerun()
        if fc2.button(":material/close: Reject after reeval", key=f"reject_final_{rec['id']}", width="stretch"):
            db.finalize_recommendation(rec["id"], "rejected_after_reeval", reviewer="dashboard-reviewer",
                                       note="Fresh-seed reeval did not justify the change.")
            bump_version()
            st.rerun()

st.space("large")

# --- History ---
st.subheader(f":material/history: History ({len(history)})")
status_color = {"validated_approved": "green", "rejected": "gray", "rejected_after_reeval": "orange"}
st.dataframe(
    [{"id": r["id"], "round": r["round_number"], "parameter": r["gap_parameter"],
      "change": f"{r['current_value']} → {r['proposed_value']}", "status": r["status"],
      "reviewed_by": r["final_reviewed_by"] or r["reviewed_by"], "created_at": r["created_at"]}
     for r in history],
    hide_index=True, width="stretch",
    column_config={"status": st.column_config.TextColumn()},
)
