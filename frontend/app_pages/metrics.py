import sys
from pathlib import Path

import pandas as pd
import streamlit as st

FRONTEND_DIR = Path(__file__).resolve().parents[1]
if str(FRONTEND_DIR) not in sys.path:
    sys.path.insert(0, str(FRONTEND_DIR))

from shared import cached_calibration_report, cached_confounder_rows, cached_cost_sensitivity_report, cached_eval_report, cached_fairness_report, cached_ring_rows, ensure_version  # noqa: E402

st.title(":material/monitoring: Metrics")
st.caption(
    "Computed on a held-out split of the planted ground truth — never used to pick any threshold in the "
    "pipeline. Reported honestly, including the numbers that aren't a clean 100%."
)

version = ensure_version()
eval_report = cached_eval_report(version)
if not eval_report:
    st.warning("No eval report found. Run `python -m backend.pipeline.eval`.", icon=":material/warning:")
    st.stop()

overall = eval_report["overall"]

st.subheader("Headline numbers")
with st.container(horizontal=True):
    st.metric("Hard-signal ring recall", f"{overall['hard_signal_recall']:.0%}",
              help=f"{overall['n_rings_hard']} planted hard-signal rings", border=True)
    st.metric("Soft-signal ring recall", f"{overall['soft_signal_recall']:.0%}",
              help=f"{overall['n_rings_soft']} planted soft-signal rings — the real test of the approach", border=True)
    st.metric("Confounder false-positive rate", f"{overall['confounder_false_positive_rate']:.0%}",
              help=f"{overall['n_confounders']} planted legitimate clusters", border=True)
    st.metric("Cluster-level precision", f"{overall['cluster_precision']:.0%}",
              help=f"tp={overall['cluster_tp']}, fp={overall['cluster_fp']}", border=True)

with st.container(border=True):
    st.markdown(":material/balance: **Cost-weighted framing**")
    st.write(
        "A missed ring means paid-out fraudulent bonuses — direct financial loss, recoverable only via "
        "clawback if caught later. A wrongly-flagged legitimate cluster means a blocked bonus, customer "
        "friction, and possible churn — but zero automatic action is ever taken on it (every recommendation "
        "is `HOLD_BONUS` / `MANUAL_REVIEW` / `NO_ACTION` for a human to execute), so the real-world cost of a "
        "false positive here is a delayed payout pending review, not a wrongful punishment. That asymmetry is "
        "why Stage 5 is tuned conservatively toward not flagging on ambiguous evidence."
    )

st.space("large")

# --- Difficulty breakdown ---
st.subheader("Recall and false-positive rate by difficulty")
st.caption(
    "The dataset deliberately plants a mix of easy and hard cases per category — a 'hard mode' ring "
    "(slower claims, noisier order values) and a 'tight' confounder (compressed signup window). This is "
    "where the misses actually live, and it's the honest way to show that."
)

ring_rows = cached_ring_rows(version)
conf_rows = cached_confounder_rows(version)

diff_cols = st.columns(2)
with diff_cols[0]:
    df = pd.DataFrame(ring_rows)
    if not df.empty:
        summary = df.groupby(["type", "difficulty"]).agg(
            total=("detected", "count"), detected=("detected", "sum")
        ).reset_index()
        summary["recall"] = (summary["detected"] / summary["total"]).round(3)
        summary = summary.rename(columns={"type": "Signal", "difficulty": "Difficulty", "total": "Rings", "detected": "Detected", "recall": "Recall"})
        with st.container(border=True):
            st.markdown("**Ring recall**")
            st.dataframe(summary, hide_index=True, width="stretch",
                         column_config={"Recall": st.column_config.ProgressColumn(min_value=0, max_value=1, format="%.0%%")})
with diff_cols[1]:
    df = pd.DataFrame(conf_rows)
    if not df.empty:
        summary = df.groupby(["type", "difficulty"]).agg(
            total=("wrongly_flagged", "count"), wrong=("wrongly_flagged", "sum")
        ).reset_index()
        summary["fp_rate"] = (summary["wrong"] / summary["total"]).round(3)
        summary = summary.rename(columns={"type": "Type", "difficulty": "Difficulty", "total": "Confounders", "wrong": "Wrongly flagged", "fp_rate": "FP rate"})
        with st.container(border=True):
            st.markdown("**Confounder false positives**")
            st.dataframe(summary, hide_index=True, width="stretch",
                         column_config={"FP rate": st.column_config.ProgressColumn(min_value=0, max_value=1, format="%.0%%")})

st.space("large")

# --- Dev vs holdout ---
st.subheader("Dev vs. holdout split")
st.caption("Thresholds were only ever eyeballed against the dev split. These headline numbers come from holdout.")
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

st.space("large")

# --- Ring-by-ring detail ---
st.subheader("Ring-by-ring detail")
show_missed_only = st.toggle("Show missed rings only")
rows_to_show = [r for r in ring_rows if not r["detected"]] if show_missed_only else ring_rows
st.dataframe(
    [{"Ring": r["ring_id"], "Type": r["type"], "Difficulty": r["difficulty"], "Size": r["size"],
      "Detected": "yes" if r["detected"] else "MISSED", "Matched cluster": r["matched_cluster_id"] or "-"}
     for r in rows_to_show],
    hide_index=True, width="stretch", height=min(420, 46 + 35 * len(rows_to_show)),
)

st.space("large")

# --- Confidence calibration ---
st.subheader("Does stated confidence track ground truth?")
calib = cached_calibration_report(version)
if not calib:
    st.info("Run `python -m backend.confidence_calibration` after a live LLM investigation pass to generate this.",
             icon=":material/info:")
else:
    st.caption(
        f"{calib['n_flagged']} flagged clusters carry a real (non-template) LLM confidence score. "
        f"{calib['n_true_rings']} match a planted ring; {calib['n_not_true_ring']} don't."
    )
    bucket_rows = [b for b in calib["buckets"] if b["n"] > 0]
    st.dataframe(
        [{"Confidence": b["range"], "Clusters": b["n"],
          "Accuracy": b["accuracy"], "False positives": ", ".join(b.get("false_positives") or []) or "—"}
         for b in bucket_rows],
        hide_index=True, width="stretch",
        column_config={"Accuracy": st.column_config.ProgressColumn(min_value=0, max_value=1, format="%.0%%")},
    )
    n_neg = calib["n_not_true_ring"]
    st.caption(
        f":material/info: Only {n_neg} negative example{'s' if n_neg != 1 else ''} exist{'s' if n_neg == 1 else ''} "
        f"across {calib['n_flagged']} flagged clusters — most buckets show 100% simply because they contain zero "
        "negative examples to miss, not because confidence has been validated against a meaningful number of "
        "counter-examples. This is a real signal (confidence does correlate with the Stage 4/5 evidence strength "
        "the LLM was given), but with this few negative examples it is not a statistically meaningful calibration "
        "curve, and that's stated plainly rather than blended into one clean number."
    )

st.space("large")

# --- Fairness audit ---
st.subheader("Fairness audit — does the false-positive rate skew by geography?")
fairness = cached_fairness_report(version)
if not fairness:
    st.info("Run `python -m backend.fairness_audit` to generate this.", icon=":material/info:")
else:
    st.caption(
        "RBI's FREE-AI framework names 'Fair' as a pillar. The concrete risk: shared device/IP is also "
        "just how families and hostel residents live, not fraud — if Stage 5 clears those legitimately "
        "shared-attribute clusters unevenly by geography, that's a fairness failure this system's own "
        "signals could cause. Tagged by home_pincode against 8 verified Tier-1 metro postal prefixes "
        "(confirmed by grep: pincode is never read by Stages 1-5, so no direct bias path exists — this "
        "checks for an indirect one)."
    )
    by_tier = fairness["confounder_fp_rate_by_tier"]
    cols = st.columns(2)
    for col, (tier, d) in zip(cols, by_tier.items()):
        label = "Tier-1 metro" if tier == "tier1_metro" else "Tier-2/3 / other"
        rate_str = f"{d['fp_rate']:.1%}" if d["fp_rate"] is not None else "n/a"
        col.metric(f"{label} confounders", f"{d['fp']} / {d['n']} flagged", rate_str)

    st.dataframe(
        [{"Confounder type": ctype, "Tier-1 (n / FP)": f"{v['tier1_metro']['n']} / {v['tier1_metro']['fp']}",
          "Tier-2/3 (n / FP)": f"{v['tier2_3_other']['n']} / {v['tier2_3_other']['fp']}"}
         for ctype, v in fairness["confounder_fp_rate_by_type_and_tier"].items()],
        hide_index=True, width="stretch",
    )
    acct = fairness["account_level"]
    st.caption(
        f":material/info: Only {acct['n_confounder_accounts_in_tier1_metro']} of "
        f"{acct['n_confounder_accounts_with_pincode']} confounder-cluster accounts land in one of the 8 "
        "Tier-1 metro prefixes checked — with 40 confounders and 1 total false positive in the frozen set, "
        "no split of this data has enough false positives to support a statistically meaningful rate "
        "comparison either direction. What this does confirm: there's no code path today where geography "
        "can bias a flag directly. The indirect risk is still real and correctly named even though this "
        "dataset can't yet measure it — shared device/IP genuinely correlates with hostel and lower-income "
        "shared housing in the real world, and Stage 5's organic-evidence thresholds have never been tested "
        "against a sample where that correlation is present, because pincode is generated independently at "
        "random here (see `backend/fairness_audit.py` for the full methodology)."
    )

st.space("large")

# --- Cost-calibrated threshold sensitivity ---
st.subheader("Cost-calibrated threshold sensitivity")
cost = cached_cost_sensitivity_report(version)
if not cost:
    st.info("Run `python -m backend.cost_threshold_sensitivity` to generate this.", icon=":material/info:")
else:
    st.caption(
        f"What does a threshold choice cost in real rupees? False-negative cost is computed, not assumed: "
        f"Rs {cost['fn_cost_per_missed_ring']:,.0f} average fraudulent bonus payout per missed ring, from "
        "actual paid referral claims in data/raw/referrals.csv. False-positive cost isn't in the data, so "
        "it's swept across 3 labeled assumption scenarios instead of asserted as one number."
    )
    device = cost["device_clear_organic_threshold"]
    soft = cost["soft_signal_suspicion_threshold"]

    tab_device, tab_soft = st.tabs(["Shared-device organic-clear threshold", "Soft-signal suspicion threshold"])
    for tab, sweep_data, param_label in [
        (tab_device, device, "DEVICE_CLEAR_ORGANIC_THRESHOLD"),
        (tab_soft, soft, "SOFT_FLAG_SUSPICION_THRESHOLD"),
    ]:
        with tab:
            cur = sweep_data["current_production_value"]
            rows = []
            for T_str, s in sweep_data["sweep"].items():
                rows.append({
                    "Threshold": f"{T_str}{' (current)' if int(T_str) == cur else ''}",
                    "Recall": s["recall"], "FP rate": s["fp_rate"],
                    "Rings missed": s["rings_missed"], "Confounder FPs": s["confounders_fp"],
                })
            st.dataframe(rows, hide_index=True, width="stretch",
                        column_config={
                            "Recall": st.column_config.ProgressColumn(min_value=0, max_value=1, format="%.0%%"),
                            "FP rate": st.column_config.ProgressColumn(min_value=0, max_value=1, format="%.0%%"),
                        })
            st.caption(f"`{param_label}` — current production default = {cur}")

    st.markdown(
        "**Real finding**: recall is completely flat (73/80 rings) across every shared-device threshold "
        "tested — no real ring in this dataset has a high enough organic_score for this threshold to ever "
        "cost recall. Only the confounder FP count moves: 0 at threshold 1-2, 1 at the current default (3), "
        "6 at threshold 4. That makes threshold=2 a strict improvement on every metric measured here — same "
        "recall, fewer false positives — regardless of any FP-cost assumption."
    )
    st.caption(
        ":material/info: This finding is **not applied to production** here — it was found by evaluating "
        "against the full ring/confounder set, including the holdout split this project has deliberately "
        "never tuned against anywhere else. Reported as a testable hypothesis for the next dev-split tuning "
        "pass, not a change made on the strength of this script alone. See "
        "`docs/COST_THRESHOLD_SENSITIVITY.md` for the full breakdown, including the soft-signal branch's "
        "own honest finding: its sole real false positive sits on a different branch entirely, so that "
        "sweep shows no FP trade-off on this dataset."
    )
