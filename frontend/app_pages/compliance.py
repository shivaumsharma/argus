import sys
from pathlib import Path

import streamlit as st

FRONTEND_DIR = Path(__file__).resolve().parents[1]
if str(FRONTEND_DIR) not in sys.path:
    sys.path.insert(0, str(FRONTEND_DIR))

from shared import cached_compliance_data, ensure_version  # noqa: E402

st.title(":material/verified: Compliance")
st.caption(
    "The RBI's FREE-AI framework (Aug 2025) expects AI used in fraud detection to be Fair, Reliable, "
    "Explainable, and Ethical. Every number on this page is computed live from the same audit_log and "
    "clusters store as docs/COMPLIANCE_SUMMARY.md — not hand-written prose duplicated in two places."
)

version = ensure_version()
d = cached_compliance_data(version)

st.caption(f"Computed {d['generated_at']} — {d['n_flagged']} flagged clusters, "
          f"{d['n_rings']} planted rings, {d['n_confounders']} planted confounders.")

st.space("large")

# --- Explainable ---
st.subheader(":material/manage_search: Explainable")
st.write(f"Every one of the **{d['n_flagged']}** currently-flagged clusters has a decision chain that traces "
        "back to specific graph edges and feature values — no black-box score. A worked example from this "
        "exact run:")

chain = d["chain_example"]
if chain:
    c, filter_row, llm_row = chain["cluster"], chain["filter_row"], chain["llm_row"]
    with st.container(border=True):
        st.markdown(f"**Cluster `{c['cluster_id']}`** ({c['detection_stage']}-signal, {c['features']['size']} accounts)")
        st.markdown(f"**1. Stage 5 decision** (deterministic, no model): _{c['filter_reason']}_")
        if filter_row:
            st.caption(f"Logged as audit_log row `{filter_row['id']}`, event `{filter_row['event_type']}`, "
                      "with the full Stage 4 feature vector as input evidence.")
        st.markdown(f"**2. Stage 8 writeup** ({c.get('llm_mode', 'n/a')}): "
                   f"_\"{(c.get('llm_case_summary') or '')[:220]}...\"_")
        if llm_row:
            st.caption(f"Logged as audit_log row `{llm_row['id']}`, event `{llm_row['event_type']}`, with the "
                      "exact prompt (Stage 4/5 evidence only, no raw account data) as input and the full "
                      "structured response as output.")
        st.markdown(f"**3. Recommended action**: `{c.get('llm_recommended_action', 'n/a')}` — bounded to "
                   "HOLD_BONUS / MANUAL_REVIEW / NO_ACTION; a human executes.")
else:
    st.info("No flagged clusters with a completed investigation exist in the current store to sample.",
           icon=":material/info:")

st.space("large")

# --- Auditable ---
st.subheader(":material/history: Auditable")
st.write(f"The audit_log table currently holds **{d['audit_rows_total']} entries**, every one with its full "
        "input evidence and output stored as JSON, queryable by cluster ID.")
st.dataframe(
    [{"event_type": event, "count": n} for event, n in sorted(d["event_counts"].items())],
    hide_index=True, width="stretch",
)
st.caption(
    "Any flag can be reconstructed end to end after the fact — which graph edges fired, which Stage 4 "
    "features were computed, why Stage 5 did or didn't suppress the flag, and exactly what evidence the LLM "
    "saw. This extends to the adversarial recommendation engine's own lifecycle "
    "(`recommendation_proposed`/`_reviewed`/`_reevaluated`/`_finalized`) via this same table, not a parallel log."
)

st.space("large")

# --- Fair ---
st.subheader(":material/balance: Fair")
overall = d["overall_eval"]
if overall:
    st.metric("Confounder false-positive rate", f"{overall['confounder_false_positive_rate']:.1%}",
              help=f"{overall.get('cluster_fp', '?')} of {d['n_confounders']} planted legitimate clusters "
                   "wrongly flagged.")
    st.caption(
        "Stage 5 exists specifically to prevent dense, legitimate clusters (households, hostels, office "
        "networks, organic referral trees) from being punished for looking structurally similar to a fraud "
        "ring. Fairness is also architectural: every recommendation is bounded to HOLD_BONUS/MANUAL_REVIEW/"
        "NO_ACTION, so a false positive costs a delayed payout pending human review, never an executed penalty."
    )
else:
    st.info("No eval report found — run the eval harness to populate this metric.", icon=":material/info:")

st.markdown("**Socioeconomic false-positive audit**")
fairness = d["fairness"]
if not fairness:
    st.info("Run `python -m backend.fairness_audit` to generate this.", icon=":material/info:")
else:
    st.caption(
        "Does the confounder false-positive rate — and, separately, ring recall — skew by a real "
        "geographic/economic tier proxy? No protected attribute used anywhere; `home_pincode` confirmed "
        "unused in Stages 1-5 by direct grep, so no direct bias path exists today."
    )
    tier_display = {"tier1_metro": "Tier-1 metro", "tier2_city": "Tier-2 city", "tier3_other": "Tier-3 / other"}
    conf_by_tier = fairness["confounder_fp_rate_by_tier"]
    ring_by_tier = fairness["ring_recall_by_tier"]
    rows = []
    for tier in ("tier1_metro", "tier2_city", "tier3_other"):
        c, r = conf_by_tier[tier], ring_by_tier[tier]
        rows.append({
            "Tier": tier_display[tier],
            "Confounders (n/FP)": f"{c['n']}/{c['hits']}",
            "FP rate": f"{c['rate']:.1%}" if c["rate"] is not None else "n/a",
            "Rings (n/detected)": f"{r['n']}/{r['hits']}",
            "Recall": f"{r['rate']:.1%}" if r["rate"] is not None else "n/a",
        })
    st.dataframe(rows, hide_index=True, width="stretch")
    st.caption(f":material/info: {fairness['honest_read']}")
    with st.expander("Tier classification used"):
        st.write("**Tier-1 metro** (population >4M, 2001 census — the informal industry classification, "
                "*not* RBI's own separate 100K+ banking Tier-1):")
        st.write(", ".join(f"{city} ({prefix})" for prefix, city in fairness["tier1_prefixes"].items()))
        st.write("**Tier-2 city**:")
        st.write(", ".join(f"{city} ({prefix})" for prefix, city in fairness["tier2_prefixes"].items()))

st.space("large")

# --- Reliable ---
st.subheader(":material/verified_user: Reliable")
if overall:
    m1, m2, m3 = st.columns(3)
    m1.metric("Hard-signal recall", f"{overall['hard_signal_recall']:.1%}")
    m2.metric("Soft-signal recall", f"{overall['soft_signal_recall']:.1%}",
             help="Reported separately, not blended — the genuinely harder case, and the honest number is lower.")
    m3.metric("Cluster precision", f"{overall['cluster_precision']:.1%}")
    st.caption("All three measured on a held-out split of ground truth never used to pick a threshold.")

calib = d["calibration"]
if calib and calib.get("status") == "ok":
    n_neg = calib["n_not_true_ring"]
    src = calib.get("sources", {})
    st.caption(
        f":material/info: Stage 8's self-reported confidence checked against ground truth across "
        f"{calib['n_flagged']} scored clusters ({src.get('primary_dataset', '?')} primary + "
        f"{src.get('supplementary_batch', '?')} supplementary batch) — **{n_neg} negative examples**, "
        "enough spread to see a genuine trend. See the Metrics page for the full decile breakdown."
    )
elif calib:
    st.info(f"Combined dataset still only has {calib.get('n_not_true_ring', 0)} negative example(s) — "
           "too few for a meaningful calibration curve, reported as that rather than a thin number.",
           icon=":material/info:")
else:
    st.info("No confidence-calibration data in the current store.", icon=":material/info:")

st.space("large")

# --- Ethical ---
st.subheader(":material/diversity_3: Ethical / human-in-the-loop")
mode_counts, action_counts = d["mode_counts"], d["action_counts"]
n_real_llm = mode_counts.get("gemini", 0) + mode_counts.get("anthropic", 0)
st.write(f"Of the {d['n_flagged']} flagged clusters, **{n_real_llm}** carry a real LLM-authored case "
        f"(vs. **{mode_counts.get('fallback_template', 0)}** on the deterministic template fallback), and "
        "every one recommends exactly one of three bounded actions: "
        + ", ".join(f"`{k}` ({v})" for k, v in sorted(action_counts.items())) + ".")
st.caption(
    "The LLM never sees raw account data (no names, phones, emails) — only the aggregate evidence the "
    "deterministic pipeline already computed — and it never decides whether a cluster is suspicious; that "
    "decision is made by Stages 1-5 before the LLM is invoked at all."
)

st.space("large")
st.caption(f"Full markdown version: `docs/COMPLIANCE_SUMMARY.md` (regenerate with "
          "`python -m backend.compliance_report`).")
