import sys
from pathlib import Path

import streamlit as st

FRONTEND_DIR = Path(__file__).resolve().parents[1]
if str(FRONTEND_DIR) not in sys.path:
    sys.path.insert(0, str(FRONTEND_DIR))

from shared import cached_confounder_rows, cached_eval_report, cached_ring_rows, ensure_version, get_graph  # noqa: E402

version = ensure_version()

# --- Hero ---
st.title(":material/hub: Promo/referral abuse-ring sentinel")
st.markdown(
    "##### A single farmed account looks ordinary. A *ring* of them doesn't."
)
st.write(
    "Real-looking phone number, plausible order, no red flag — that's what makes referral-bonus farming "
    "hard to catch one account at a time. The fraud only becomes visible when accounts are looked at "
    "**together**: the same device behind a dozen \"different\" signups, a bonus claimed two hours after "
    "signup, order values that are identical down to the rupee. That's not something a per-account model "
    "can see, no matter how good it is — the signal only exists *across* accounts. So this system builds "
    "a graph of who's connected to whom, and clusters it."
)

ring_rows = cached_ring_rows(version)
conf_rows = cached_confounder_rows(version)
eval_report = cached_eval_report(version)

if not eval_report:
    st.warning(
        "No pipeline output yet. Click **Re-run detection** in the sidebar, then **Re-run LLM investigation**, "
        "to generate the numbers and cases shown on this page.",
        icon=":material/warning:",
    )
    st.stop()

n_accounts = get_graph(version).number_of_nodes()
rings_caught = sum(1 for r in ring_rows if r["detected"])
confounders_spared = sum(1 for r in conf_rows if not r["wrongly_flagged"])
overall = eval_report["overall"]

st.space("medium")
with st.container(horizontal=True):
    st.metric("Accounts analyzed", f"{n_accounts:,}", border=True,
              help="Every account in this synthetic cohort, planted rings and confounders included, plus ordinary background users.")
    st.metric("Rings caught", f"{rings_caught} / {len(ring_rows)}", border=True,
              help="Planted fraud rings the pipeline recovered, hard-signal and soft-signal combined.")
    st.metric("Confounders correctly spared", f"{confounders_spared} / {len(conf_rows)}", border=True,
              help="Planted legitimate clusters — real households, hostels, office networks, organic referral trees — left unflagged.")
    st.metric("Confounder false-positive rate", f"{overall['confounder_false_positive_rate']:.1%}", border=True,
              help="The honesty check: how often a legitimate cluster gets wrongly flagged. See the Metrics page for the full breakdown.")

st.space("large")

# --- How it works ---
st.subheader("How it works")
st.caption("Five deterministic stages decide what's suspicious. An LLM only ever writes up a case *after* that decision is made.")

steps = [
    (":material/hub:", "1. Build the graph", "Accounts as nodes. Edges wherever two accounts share a device, a payment instrument, an IP subnet, or a referral link."),
    (":material/link:", "2. Hard-signal clustering", "Connected components on shared-device / shared-instrument edges only — near-certain fraud signals, no model needed."),
    (":material/share:", "3. Soft-signal clustering", "Weighted community detection over the full graph — catches rings connected only by IP overlap and referral timing."),
    (":material/query_stats:", "4. Score every cluster", "Signup-burst tightness, order-value templating, claim-then-dormant pattern, post-signup engagement — still fully deterministic."),
    (":material/verified_user:", "5. Filter out confounders", "Explicit rules actively look for evidence a cluster is *legitimate* and suppress the flag when they find it."),
    (":material/smart_toy:", "6. Bounded LLM writeup", "Only for clusters that survive Stage 5. Sees only the evidence above, never raw account data, and picks one of three bounded actions."),
]
with st.container(horizontal=True):
    for icon, title, desc in steps:
        with st.container(border=True, width=230):
            st.markdown(f"{icon} **{title}**")
            st.caption(desc)

st.space("large")

# --- Cost framing ---
with st.container(border=True):
    st.markdown(":material/balance: **Why a false positive here is cheap and a false negative is expensive**")
    st.write(
        "A **missed ring** means paid-out fraudulent bonuses — real money, recoverable only via clawback if "
        "caught later, and often not caught at all. A **wrongly-flagged legitimate cluster** costs, at most, a "
        "delayed bonus payout pending human review — because nothing in this system auto-executes anything. "
        "Every recommendation is bounded to `HOLD_BONUS` / `MANUAL_REVIEW` / `NO_ACTION`, and a human always "
        "makes the final call. **There is no code path anywhere here that bans, blocks, or moves money.**"
    )

st.space("large")

# --- Navigation ---
st.subheader("Where to look next")
nav_cols = st.columns(3)
with nav_cols[0]:
    with st.container(border=True):
        st.markdown(":material/flag: **Flagged clusters**")
        st.caption("Every cluster the pipeline flagged, with its evidence, its graph, and the LLM's case writeup.")
        st.page_link("app_pages/flagged_clusters.py", label="Open flagged clusters", icon=":material/arrow_forward:")
with nav_cols[1]:
    with st.container(border=True):
        st.markdown(":material/verified_user: **Confounders left alone**")
        st.caption("The households, hostels, and office networks that look similar but were correctly not flagged — and why.")
        st.page_link("app_pages/confounders.py", label="Open confounders", icon=":material/arrow_forward:")
with nav_cols[2]:
    with st.container(border=True):
        st.markdown(":material/monitoring: **Metrics**")
        st.caption("Held-out precision/recall, hard vs. soft signal, and the confounder false-positive rate — the honest numbers.")
        st.page_link("app_pages/metrics.py", label="Open metrics", icon=":material/arrow_forward:")
