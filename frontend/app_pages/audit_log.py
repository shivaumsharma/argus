import sys
from pathlib import Path

import streamlit as st

FRONTEND_DIR = Path(__file__).resolve().parents[1]
if str(FRONTEND_DIR) not in sys.path:
    sys.path.insert(0, str(FRONTEND_DIR))

from shared import db, humanize_event_type  # noqa: E402

st.title(":material/history: Audit log")
st.caption(
    "Every clustering decision and every LLM call, with its full input evidence and output — the "
    "auditability trail the RBI FREE-AI framework expects from AI used in fraud detection. Nothing here "
    "is a black-box judgment call; every row traces back to specific graph edges and feature values."
)

filter_cols = st.columns([2, 1])
with filter_cols[0]:
    cluster_id = st.text_input("Filter by cluster ID (optional)", placeholder="e.g. C0002")
with filter_cols[1]:
    limit = st.number_input("Max rows", min_value=20, max_value=2000, value=200, step=20)

log_rows = db.get_audit_log(cluster_id=cluster_id or None, limit=limit)
st.caption(f"{len(log_rows)} log entries.")

st.dataframe(
    [{"id": r["id"], "event": humanize_event_type(r["event_type"]), "cluster": r["cluster_id"], "timestamp": r["timestamp"]}
     for r in log_rows],
    hide_index=True, width="stretch", height=min(400, 46 + 35 * len(log_rows)),
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
