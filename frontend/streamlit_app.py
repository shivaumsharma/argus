import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared import bump_version  # noqa: E402

st.set_page_config(page_title="Fraud-Ring Sentinel", layout="wide", page_icon=":material/hub:")

# Grouped so the sidebar itself tells the right story: this is a general fraud/collusion-ring
# detector (proven on real-world data) that also ships two illustrative example scenarios --
# not a tool built narrowly around either named example.
pages = {
    "": [
        st.Page("app_pages/overview.py", title="Overview", icon=":material/home:", default=True),
    ],
    "Fraud detection — real-world validation": [
        st.Page("app_pages/external_validation.py", title="External Validation", icon=":material/travel_explore:"),
        st.Page("app_pages/resilience.py", title="Resilience", icon=":material/security:"),
    ],
    "Demo: example scenarios": [
        st.Page("app_pages/flagged_clusters.py", title="Flagged clusters", icon=":material/flag:"),
        st.Page("app_pages/confounders.py", title="Confounders left alone", icon=":material/verified_user:"),
        st.Page("app_pages/graph_explorer.py", title="Graph explorer", icon=":material/share:"),
        st.Page("app_pages/live_injection.py", title="Live injection", icon=":material/bolt:"),
        st.Page("app_pages/metrics.py", title="Metrics", icon=":material/monitoring:"),
    ],
    "Governance & trust": [
        st.Page("app_pages/compliance.py", title="Compliance", icon=":material/verified:"),
        st.Page("app_pages/recommendations.py", title="Recommendations", icon=":material/shield_with_heart:"),
        st.Page("app_pages/audit_log.py", title="Audit log", icon=":material/history:"),
    ],
}
page = st.navigation(pages, position="sidebar")

with st.sidebar:
    st.markdown("**Pipeline controls**")
    if st.button(":material/refresh: Re-run detection", width="stretch",
                 help="Re-runs Stages 1-5: graph construction, hard/soft clustering, feature scoring, confounder filter."):
        from backend.pipeline import run_pipeline
        with st.spinner("Building graph, clustering, scoring, filtering..."):
            run_pipeline.run(verbose=False)
        bump_version()
        st.toast("Detection pipeline re-run.", icon=":material/check_circle:")
        st.rerun()

    if st.button(":material/smart_toy: Re-run LLM investigation", width="stretch",
                 help="Re-runs the Stage 8 case-writeup layer over currently-flagged clusters. On a free-tier "
                      "fallback provider this can take a few minutes for a full flagged set -- avoid clicking "
                      "this mid-demo."):
        from backend.llm_investigate import investigate_all
        with st.spinner("Investigating flagged clusters (can take a few minutes on a free-tier rate limit)..."):
            investigate_all(verbose=False)
        bump_version()
        st.toast("LLM investigation re-run.", icon=":material/check_circle:")
        st.rerun()

    st.caption(
        "Provider chain: a primary LLM provider (if configured) -> a free-tier fallback LLM provider (if "
        "configured) -> a clearly-labeled deterministic template writeup, so the app always has "
        "something to show."
    )

page.run()
