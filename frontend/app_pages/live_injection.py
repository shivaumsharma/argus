import sys
from pathlib import Path

import pandas as pd
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

source = st.radio("Scenario source", ["Generate a random ring", "Upload CSV files", "Describe in free text"],
                  horizontal=True,
                  help="Generate: a fresh synthetic ring, appended to the real live dataset. Upload/Describe: "
                       "your own scenario, run in an isolated scratch copy — data/raw/, the frozen snapshot, "
                       "and data/app.db are never touched by either of these two.")

if source == "Generate a random ring":
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

elif source == "Upload CSV files":
    st.caption(
        "Files shaped like `accounts.csv`/`sessions.csv`/`referrals.csv`/`payment_instruments.csv`/`orders.csv`. "
        "Only `accounts.csv` is required — upload just the files relevant to your scenario. Columns and types "
        "are validated before anything runs; a mismatch is rejected with a specific reason, never silently coerced."
    )
    uploaded = st.file_uploader("CSV files", type="csv", accept_multiple_files=True)
    run_llm_csv = st.checkbox("Also run Stage 8 (LLM case writeup) if flagged", value=True, key="run_llm_csv")

    if uploaded and st.button(":material/upload: Validate & run", type="primary"):
        from backend.custom_scenario import run_scenario, validate_csv_files
        files, errors = {}, []
        for f in uploaded:
            try:
                files[f.name] = pd.read_csv(f, dtype=str)
            except Exception as e:
                errors.append(f"{f.name}: not readable as CSV ({type(e).__name__}: {e}).")
        if not errors:
            valid, schema_errors = validate_csv_files(files)
            if not valid:
                errors = schema_errors

        if errors:
            st.error("Upload rejected:", icon=":material/error:")
            for e in errors:
                st.write(f"- {e}")
        else:
            with st.spinner("Running the scenario in an isolated scratch copy..."):
                outcome = run_scenario(files, run_llm=run_llm_csv, verbose=False)
            bump_version()
            st.session_state["last_injection"] = outcome
            st.rerun()

else:  # Describe in free text
    st.caption(
        "Describe the scenario in plain language (e.g. \"9 accounts sharing a device, signed up over 3 days, "
        "claimed bonuses within hours\"). One real LLM call extracts structured records — shown below for a "
        "quick confirm before anything runs, since free-text extraction can misread intent."
    )
    description = st.text_area("Scenario description", height=120,
                               placeholder="9 accounts sharing the same device, signed up over 3 days, each claimed a referral bonus within hours...")
    run_llm_text = st.checkbox("Also run Stage 8 (LLM case writeup) if flagged", value=True, key="run_llm_text")

    if description and st.button(":material/auto_awesome: Extract structured scenario"):
        from backend.custom_scenario import extract_from_text
        try:
            with st.spinner("Extracting structured records..."):
                extracted = extract_from_text(description, verbose=False)
            st.session_state["extracted_scenario"] = extracted
        except RuntimeError as e:
            st.error(str(e), icon=":material/error:")

    extracted = st.session_state.get("extracted_scenario")
    if extracted:
        st.info(f"**Interpretation** ({MODE_LABEL.get(extracted['mode'], extracted['mode'])}): "
               f"{extracted['interpretation_notes']}", icon=":material/info:")
        st.dataframe(
            [{"user_id": a["user_id"], "signup": a["signup_date"], "device": a["device_fingerprint_id"],
              "instrument": a["instrument_hash"], "referred_by": a["referred_by_user_id"] or "—",
              "bonus": a["bonus_amount"] or "—", "orders": len(a["order_values"])}
             for a in extracted["accounts"]],
            hide_index=True, width="stretch",
        )
        c1, c2 = st.columns(2)
        if c1.button(":material/check: Confirm — run this scenario", type="primary", width="stretch"):
            from backend.custom_scenario import extracted_to_csv_rows, run_scenario, validate_csv_files
            files = extracted_to_csv_rows(extracted)
            valid, errors = validate_csv_files(files)
            if not valid:
                st.error("Extraction produced an invalid scenario: " + "; ".join(errors), icon=":material/error:")
            else:
                with st.spinner("Running the scenario in an isolated scratch copy..."):
                    outcome = run_scenario(files, run_llm=run_llm_text, verbose=False)
                bump_version()
                st.session_state["last_injection"] = outcome
                del st.session_state["extracted_scenario"]
                st.rerun()
        if c2.button(":material/close: Discard", width="stretch"):
            del st.session_state["extracted_scenario"]
            st.rerun()

st.space("large")

outcome = st.session_state.get("last_injection")
if not outcome:
    st.info("Nothing injected yet this session.", icon=":material/info:")
    st.stop()

st.subheader("Result")
st.caption(f"Accounts: {outcome['members'][0]} .. {outcome['members'][-1]} ({outcome['size']} total, {outcome['kind']}-signal)")

if outcome["status"] == "not_clustered":
    st.error("The scenario did not form a candidate cluster at all — Stage 2/3 never grouped it.", icon=":material/error:")
elif outcome["status"] == "clustered_not_flagged":
    st.warning(f"Clustered as **{outcome['matched_cluster']['cluster_id']}** but Stage 5 did **not** flag it.", icon=":material/warning:")
    st.write(f"Reason: {outcome['filter_reason']}")
else:
    case = outcome.get("case")
    matched = outcome["matched_cluster"]
    st.success(f"Flagged as **{matched['cluster_id']}** — real-time, this run.", icon=":material/check_circle:")

    header_cols = st.columns([2, 2, 3])
    header_cols[0].badge(f"{matched['detection_stage']}-signal", color="red" if matched["detection_stage"] == "hard" else "violet")
    if case:
        action = case["recommended_action"]
        header_cols[1].badge(action, color=ACTION_COLOR.get(action, "gray"))
        header_cols[2].markdown(f"confidence **{case['confidence']:.2f}** · {MODE_LABEL.get(case['mode'], case['mode'])}")

        st.markdown(case["case_summary"])
        if case.get("key_evidence"):
            st.markdown("**Key evidence:**")
            for ev in case["key_evidence"]:
                st.markdown(f"- {ev}")
    else:
        st.caption("Stage 8 writeup was skipped for this run.")
        st.write(f"Filter reason: {matched['filter_reason']}")

    with st.expander("Graph", icon=":material/hub:", expanded=True):
        # A custom-scenario outcome carries its own scratch-built graph (its accounts were
        # never added to the real dataset, by design, so the shared real-data graph wouldn't
        # contain them at all); the "generate a random ring" path has no "graph" key and
        # falls back to the real, now-mutated dashboard graph exactly as before.
        G = outcome.get("graph") or get_graph(version)
        html_path = graph_viz.render_cluster_graph(G, matched["members"], node_color="#c0392b",
                                                     cache_key=f"injected_{matched['cluster_id']}")
        st.iframe(src=html_path, height=380)
