import sys
from pathlib import Path

import pandas as pd
import streamlit as st

FRONTEND_DIR = Path(__file__).resolve().parents[1]
if str(FRONTEND_DIR) not in sys.path:
    sys.path.insert(0, str(FRONTEND_DIR))

from shared import cached_confounder_rows, ensure_version  # noqa: E402

st.title(":material/verified_user: Confounders left alone")
st.caption(
    "These are planted, *legitimate* dense clusters — real households, hostels, office networks, and "
    "organic referral trees. They share device/IP/referral attributes just like a fraud ring, but their "
    "behavior is organic. The entire job of Stage 5 is to notice that and leave them alone — this page is "
    "the honesty check on how well it does that."
)

version = ensure_version()
rows = cached_confounder_rows(version)

if not rows:
    st.info("No confounder ground truth found.", icon=":material/info:")
    st.stop()

n_wrong = sum(1 for r in rows if r["wrongly_flagged"])
with st.container(horizontal=True):
    st.metric("Confounder clusters", len(rows), border=True)
    st.metric("Correctly left alone", len(rows) - n_wrong, border=True)
    st.metric("Wrongly flagged", n_wrong, border=True)
    st.metric("False-positive rate", f"{n_wrong / len(rows):.1%}", border=True)

st.space("medium")

filter_cols = st.columns([1.5, 1.5, 1.5])
with filter_cols[0]:
    types_present = sorted({r["type"] for r in rows})
    type_filter = st.pills("Type", types_present, selection_mode="multi", default=types_present)
with filter_cols[1]:
    status_filter = st.segmented_control("Status", ["All", "Correctly left alone", "Wrongly flagged"], default="All")
with filter_cols[2]:
    difficulties_present = sorted({r["difficulty"] for r in rows})
    diff_filter = st.pills("Difficulty", difficulties_present, selection_mode="multi", default=difficulties_present)

filtered = [r for r in rows if r["type"] in type_filter and r["difficulty"] in diff_filter]
if status_filter == "Correctly left alone":
    filtered = [r for r in filtered if not r["wrongly_flagged"]]
elif status_filter == "Wrongly flagged":
    filtered = [r for r in filtered if r["wrongly_flagged"]]

st.caption(f"Showing {len(filtered)} of {len(rows)} confounders.")

table_df = pd.DataFrame([{
    "Confounder": r["confounder_id"],
    "Type": r["type"],
    "Difficulty": r["difficulty"],
    "Size": r["size"],
    "Status": "wrongly flagged" if r["wrongly_flagged"] else "correctly left alone",
} for r in filtered])

event = st.dataframe(
    table_df, hide_index=True, width="stretch", height=min(360, 46 + 35 * len(table_df)),
    on_select="rerun", selection_mode="single-row",
)

selected_idx = event.selection.rows[0] if event.selection.rows else 0
selected = filtered[selected_idx] if filtered else None

if selected is None:
    st.info("No confounders match these filters.", icon=":material/info:")
    st.stop()

st.space("large")
st.subheader(f"{selected['confounder_id']} ({selected['type']})")

status_cols = st.columns([1, 1, 3])
status_cols[0].badge(selected["difficulty"], color="orange" if selected["difficulty"] != "easy" else "gray")
if selected["wrongly_flagged"]:
    status_cols[1].badge("WRONGLY FLAGGED", color="red")
else:
    status_cols[1].badge("correctly left alone", color="green")
status_cols[2].markdown(f"{selected['size']} accounts")

st.markdown(selected["description"])

if selected["surfaced_as_candidate"]:
    st.markdown(f"**Matched candidate cluster `{selected['matched_cluster_id']}`.** Stage 5's reasoning:")
    st.markdown(f"> {selected['filter_reason']}")
else:
    st.markdown(
        "**Never even surfaced as a clustering candidate** — too structurally diffuse to reach Stage 4 "
        "scoring at all. That's the strongest possible form of \"left alone\": there wasn't even a dense-enough "
        "subgraph here for Stage 2 or Stage 3 to notice, let alone flag."
    )

if selected["features"]:
    with st.expander("Feature scores", icon=":material/query_stats:"):
        f = selected["features"]
        fc1, fc2, fc3 = st.columns(3)
        fc1.metric("Size", f["size"])
        fc1.metric("Edge density", f["edge_density"])
        fc2.metric("Signup span (days)", f["signup_span_days"])
        fc2.metric("Order-value CV", f["order_value_cv"] if f["order_value_cv"] is not None else "n/a")
        fc3.metric("Post-signup engagement", f["post_signup_engagement"])
        fc3.metric("Signals present", ", ".join(f["signals_present"]) or "none")
