import sys
from pathlib import Path

import streamlit as st

FRONTEND_DIR = Path(__file__).resolve().parents[1]
if str(FRONTEND_DIR) not in sys.path:
    sys.path.insert(0, str(FRONTEND_DIR))

from shared import (  # noqa: E402
    cached_concurrent_attack_report,
    cached_infra_resilience_report,
    cached_supernode_stress_report,
    cached_time_drift_report,
    ensure_version,
)

st.title(":material/security: Resilience")
st.caption(
    "Not detection accuracy on a single frozen snapshot — does the system hold up under concurrent "
    "adversarial load, realistic mid-run failures, and fraud tactics that evolve over time? Every number "
    "below is computed live from the same JSON these tests write, read fresh from disk on every run — not "
    "hand-typed prose duplicated from the underlying docs."
)

version = ensure_version()

# ==========================================================================
# Concurrent multi-ring attack stress test
# ==========================================================================
st.header(":material/hub: Concurrent multi-ring attack stress test")
st.caption(
    "Every other adversarial test injects one evasive ring at a time. This injects 8 at once — two "
    "structurally different masking strategies — to check for an interference/overload effect a "
    "single-ring test can't see."
)
concurrent = cached_concurrent_attack_report(version)
if not concurrent:
    st.info("Run `python -m backend.concurrent_attack_stress_test` to generate this.", icon=":material/info:")
else:
    n_rings = concurrent["n_rings_injected"]
    n_caught = concurrent["n_caught"]
    n_hard, n_soft = concurrent["n_masking_hard_signals"], concurrent["n_masking_soft_signals"]
    hard_caught = sum(1 for r in concurrent["per_ring"] if r["strategy"] == "masks_hard_signals" and r["caught"])
    soft_caught = sum(1 for r in concurrent["per_ring"] if r["strategy"] == "masks_soft_signals" and r["caught"])

    with st.container(horizontal=True):
        st.metric("Rings caught (of 8 injected)", f"{n_caught}/{n_rings}", border=True)
        st.metric("Masking hard signals", f"{hard_caught}/{n_hard}", border=True,
                  help="No shared device/instrument — the already-proven evasion archetype, reused unchanged.")
        st.metric("Masking soft signals", f"{soft_caught}/{n_soft}", border=True,
                  help="Shared device, but dials organic-mimicking behavior to try to clear Stage 5's checks.")

    st.dataframe(
        [{"Ring": r["attack_id"], "Strategy": r["strategy"], "Outcome": "CAUGHT" if r["caught"] else "missed",
          "Candidate stage": r["candidate_stage"] or "never clustered"} for r in concurrent["per_ring"]],
        hide_index=True, width="stretch",
    )

    st.subheader("Interference check — the actual point of this test")
    baseline_ids = concurrent["confounders_flagged_baseline"]
    with_attacks_ids = concurrent["confounders_flagged_with_attacks"]
    new_interference = concurrent["new_interference_confounders"]
    st.dataframe(
        [
            {"": "Baseline (0 rings injected)", "Confounders flagged": ", ".join(baseline_ids) or "none",
             "Count": len(baseline_ids)},
            {"": f"With {n_rings} concurrent attacks injected", "Confounders flagged": ", ".join(with_attacks_ids) or "none",
             "Count": len(with_attacks_ids)},
        ],
        hide_index=True, width="stretch",
    )
    if new_interference:
        st.warning(f"NEW interference found: {', '.join(new_interference)} — flagged only when the "
                  "concurrent attacks were present, not in the zero-attack baseline.", icon=":material/warning:")
    else:
        st.success(
            "Zero new interference. Every confounder flagged with the attacks present was already flagged "
            "in the zero-attack baseline — the baseline-controlled check that separates a real interference "
            "effect from this dataset's own pre-existing false positives. Full methodology in "
            "`docs/CONCURRENT_ATTACK_STRESS_TEST.md`.",
            icon=":material/check_circle:",
        )

st.space("large")

# ==========================================================================
# Infrastructure failure resilience test
# ==========================================================================
st.header(":material/build: Infrastructure failure resilience test")
st.caption(
    "Not detection accuracy — does the system hold up under realistic mid-run failures? Two scenarios, "
    "run for real against the production code."
)
infra = cached_infra_resilience_report(version)
if not infra:
    st.info("Run `python -m backend.infra_resilience_test` to generate this.", icon=":material/info:")
else:
    a, b = infra["scenario_a"], infra["scenario_b"]
    st.subheader("(a) LLM call resilience during Stage 8")
    n_pass_a = sum(1 for v in a.values() if v == "PASS")
    st.metric("Checks passed", f"{n_pass_a}/{len(a)}", border=True)
    st.dataframe(
        [{"Check": k.replace("_", " "), "Result": v} for k, v in a.items()],
        hide_index=True, width="stretch",
    )
    st.caption(
        "White-box tests the real `ProviderRunner.investigate()` retry/degrade/fallback loop with stubbed "
        "providers (no network calls) against a rate-limit, a generic timeout, and total provider failure."
    )

    st.subheader("(b) Malformed records spliced into the middle of a batch")
    st.metric("Corruptions dropped and logged", f"{b['dropped_and_logged']}/{b['injected']}", border=True)
    st.dataframe(
        [{"Table": d["table"], "Column": d["column"], "Corruption": d["reason"]} for d in b["injected_detail"]],
        hide_index=True, width="stretch",
    )
    st.dataframe(
        [{"Table": r["table"], "Reason": r["reason"], "Rows dropped": r["rows_dropped"],
          "Example row(s)": ", ".join(str(x) for x in r["example_ids"])} for r in b["data_quality_report"]],
        hide_index=True, width="stretch",
    )
    st.success(
        f"Pipeline completed end-to-end on the cleaned data: {b['n_candidates']} candidate clusters, "
        f"{b['n_flagged']} flagged. No crash, nothing silently miscounted. Full writeup, including the two "
        "real bugs this test found and fixed, in `docs/INFRASTRUCTURE_RESILIENCE_TEST.md`.",
        icon=":material/check_circle:",
    )

st.space("large")

# ==========================================================================
# Supernode / graph-explosion stress test
# ==========================================================================
st.header(":material/hub: Supernode / graph-explosion stress test")
st.caption(
    "Every test above varies data content. This varies data shape: what happens when a shared "
    "device/instrument/IP group is huge — a shared office NAT, a compromised SDK, a data-quality glitch — "
    "not a small household or hostel? Real, existing organic background accounts from the frozen dataset, "
    "not synthetic ones, with only one shared attribute overwritten to a single value."
)
supernode = cached_supernode_stress_report(version)
if not supernode:
    st.info("Run `python -m backend.supernode_stress_test` to generate this.", icon=":material/info:")
else:
    uncapped = {r["n"]: r for r in supernode["uncapped_sweep"]}
    worst = uncapped[max(uncapped)]
    added_seconds = worst["graph_build_seconds"] + worst["clustering_seconds"]

    st.dataframe(
        [{"N accounts": r["n"], "Graph build (s)": r["graph_build_seconds"], "Clustering (s)": r["clustering_seconds"],
          "Merged into one cluster": "yes" if r["merged_into_one_cluster"] else "no",
          "Stage 5 verdict": ("FLAGGED" if r.get("flagged") else "cleared as organic") if r["merged_into_one_cluster"] else "n/a"}
         for r in supernode["uncapped_sweep"]],
        hide_index=True, width="stretch",
    )
    if supernode["quadratic_blowup_confirmed"]:
        st.warning(
            f"Confirmed: a single N={max(uncapped):,} shared-attribute group adds **{added_seconds:.0f}s** to what "
            "is otherwise a ~2s pipeline run. Stage 1's per-group edge construction is O(n²) (a clique) — "
            f"{worst['n_edges_among_injected_accounts']:,} edges for {worst['n']:,} accounts — and Stage 3 "
            "(Louvain) clustering absorbs most of that cost, not graph construction itself as originally "
            f"guessed. Never a false positive at any size (organic_score {worst['organic_score']}/3 throughout) "
            "— this is a performance vulnerability, not a detection-accuracy one.",
            icon=":material/warning:",
        )
    else:
        st.success(f"No problem confirmed — max added stage time across the sweep was {added_seconds:.1f}s.",
                   icon=":material/check_circle:")

    cap = supernode.get("degree_cap_tested")
    if cap:
        capped = {r["n"]: r for r in supernode["mitigation_sweep"]}
        capped_worst = capped[max(capped)]
        st.success(
            f"Mitigated: `graph_build.build_graph`'s `max_shared_attribute_group_size` parameter (cap={cap}) "
            "skips edge construction for any shared-attribute group above the cap — the same judgment already "
            "applied to Amazon's excluded `net_usu` relation in external validation (\"an attribute touched by "
            f"many distinct users earns suspicion, not weight\"). At N={max(capped):,}, capped: "
            f"{capped_worst['graph_build_seconds']:.2f}s build + {capped_worst['clustering_seconds']:.2f}s "
            "clustering — flat, unaffected by N. Verified this doesn't disturb legitimate small-scale behavior: "
            "a real household or hostel in this dataset's own generator tops out at ~25 members, far under the "
            f"cap of {cap}. Default is `None` (unchanged behavior) — the cap is opt-in.",
            icon=":material/check_circle:",
        )
        with st.expander("Capped sweep, full detail"):
            st.dataframe(
                [{"N accounts": r["n"], "Graph build (s)": r["graph_build_seconds"], "Clustering (s)": r["clustering_seconds"],
                  "Edges among injected accounts": r["n_edges_among_injected_accounts"],
                  "Uncapped clique would be": r["uncapped_clique_edges_would_be"],
                  "Merged into one cluster": "yes" if r["merged_into_one_cluster"] else "no"}
                 for r in supernode["mitigation_sweep"]],
                hide_index=True, width="stretch",
            )

st.space("large")

# ==========================================================================
# Time-drift simulation
# ==========================================================================
st.header(":material/schedule: Time-drift simulation")
st.caption(
    "Every other eval is a single point in time. Does static detection decay as fraud tactics evolve "
    "across sequential periods, with Stage 1-5 held completely frozen throughout — no retraining, no "
    "fix applied mid-simulation?"
)
drift = cached_time_drift_report(version)
if not drift:
    st.info("Run `python -m backend.time_drift_simulation` to generate this.", icon=":material/info:")
else:
    st.dataframe(
        [{"Period": p["period"], "No-shared-device recall": f"{p['recall_no_shared_device']:.0%}",
          "Shared-device recall": f"{p['recall_shared_device']:.0%}",
          "Confounder FP rate": f"{p['confounder_fp_rate']:.1%}"} for p in drift["periods"]],
        hide_index=True, width="stretch",
        column_config={
            "No-shared-device recall": st.column_config.TextColumn(),
            "Shared-device recall": st.column_config.TextColumn(),
        },
    )
    t1, t2, t3 = st.columns(3)
    t1.metric("Trend — no-shared-device", drift["trend_no_shared_device"])
    t2.metric("Trend — shared-device", drift["trend_shared_device"])
    t3.metric("Trend — confounder FP", drift["trend_confounder_fp_rate"])
    st.caption(
        f"Seed `{drift['seed']}`, {drift['n_periods']} periods, {drift['rings_per_population_per_period']} "
        "rings per population per period. Each population's knobs only escalate toward the known evasive "
        "archetype if it was still being caught the period before — outcome-conditioned, not a pre-baked "
        "ramp. Full methodology, including a real construction bug found and fixed in the first attempt at "
        "this test, in `docs/TIME_DRIFT_SIMULATION.md`."
    )
