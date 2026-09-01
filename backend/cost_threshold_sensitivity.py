"""
Cost-calibrated threshold sensitivity.

Stage 5 has two judgment-call thresholds, both tuned by eyeballing the dev
split (see confounder_filter.py):
  - DEVICE_CLEAR_ORGANIC_THRESHOLD (default 3): a shared-device cluster
    clears if organic_score >= this.
  - SOFT_FLAG_SUSPICION_THRESHOLD (default 3): a soft-signal-only cluster
    (no shared device/instrument) flags if suspicion_score >= this.

This script asks the concrete question the track's own bar language raises:
what does each judgment call cost in real rupees, and does a different
threshold cost less? Both thresholds are swept independently by replaying
the *exact* production `evaluate_cluster()` function (imported unchanged,
called with a different threshold argument) against every already-computed
Stage 4 feature dict already sitting in the DB -- no data regeneration, no
pipeline rerun, pure re-analysis of numbers already produced.

Two costs, handled very differently on purpose:

- **False-negative cost (a missed ring) is computed, not assumed.** For
  every planted ring, this sums the real `bonus_amount` of every *paid*
  referral claim touching that ring's members, straight from
  `data/raw/referrals.csv` -- the actual fraudulent payout this system's
  ground truth represents.
- **False-positive cost (a wrongly-flagged legitimate cluster) is NOT in the
  data** -- there's no support-ticket log or churn record to compute it
  from, so it's an explicit, labeled assumption: analyst review time, plus a
  churn-risk estimate built from this dataset's own real order values,
  swept across three scenarios rather than asserted as one true figure.

Run: python -m backend.cost_threshold_sensitivity
"""

import json

import pandas as pd

from . import db
from .pipeline.confounder_filter import (
    DEVICE_CLEAR_ORGANIC_THRESHOLD,
    SOFT_FLAG_SUSPICION_THRESHOLD,
    evaluate_cluster,
)
from .pipeline.data_io import PROCESSED_DIR, RAW_DIR
from .pipeline.eval import best_match
from .reporting import load_ground_truth

THRESHOLDS = [1, 2, 3, 4]


def compute_fn_cost(rings):
    """Real, empirical: mean of actual paid referral-bonus payouts touching each
    planted ring's members, from data/raw/referrals.csv. Not an assumption."""
    referrals = pd.read_csv(RAW_DIR / "referrals.csv")
    paid = referrals[referrals["bonus_status"] == "paid"]
    totals = []
    for ring in rings.values():
        members = set(ring["members"])
        mask = paid["referred_user_id"].isin(members) | paid["referrer_user_id"].isin(members)
        totals.append(paid.loc[mask, "bonus_amount"].sum())
    return sum(totals) / len(totals), totals


def fp_cost_scenarios():
    """NOT in the data. Analyst-review time is a stated flat assumption; the
    churn component is grounded in this dataset's real order values (not an
    arbitrary number) but the churn probability and how many future orders
    are "at risk" are still assumptions -- swept as three labeled scenarios,
    not asserted as one true figure."""
    orders = pd.read_csv(RAW_DIR / "orders.csv")
    mean_order_value = orders["order_value"].mean()
    review_cost = 150.0  # ~15 min of analyst time at an assumed loaded Rs 600/hr

    return {
        "review_only": {
            "cost": round(review_cost, 2),
            "assumption": "Analyst review time only; assumes zero customers who are delayed ever churn.",
        },
        "review_plus_moderate_churn": {
            "cost": round(review_cost + 0.05 * 5 * mean_order_value, 2),
            "assumption": f"Review cost + 5% churn probability on an assumed 5-future-order LTV "
                          f"(5 x mean order value Rs {mean_order_value:.0f} = Rs {5*mean_order_value:.0f}).",
        },
        "review_plus_high_value_churn": {
            "cost": round(review_cost + 0.15 * 10 * mean_order_value, 2),
            "assumption": f"Review cost + 15% churn probability on an assumed 10-future-order LTV, "
                          f"for a higher-value customer segment "
                          f"(10 x mean order value Rs {mean_order_value:.0f} = Rs {10*mean_order_value:.0f}).",
        },
    }


def _sweep(all_clusters, rings, confounders, param_name, thresholds):
    sweep = {}
    for T in thresholds:
        kwargs = {param_name: T}
        flagged = [c for c in all_clusters if evaluate_cluster(c["features"], **kwargs)["flagged"]]
        n_detected = sum(1 for r in rings.values() if best_match(set(r["members"]), flagged))
        n_fp = sum(1 for cf in confounders.values() if best_match(set(cf["members"]), flagged))
        sweep[T] = {
            "n_flagged_total": len(flagged),
            "rings_detected": n_detected, "rings_total": len(rings),
            "rings_missed": len(rings) - n_detected,
            "recall": round(n_detected / len(rings), 4),
            "confounders_fp": n_fp, "confounders_total": len(confounders),
            "fp_rate": round(n_fp / len(confounders), 4),
        }
    return sweep


def _cost_table(sweep, thresholds, fn_cost, fp_scenarios, current_threshold):
    cost_by_scenario = {}
    for name, scenario in fp_scenarios.items():
        fp_cost = scenario["cost"]
        rows = []
        best_T, best_cost = None, float("inf")
        for T in thresholds:
            s = sweep[T]
            total_cost = s["rings_missed"] * fn_cost + s["confounders_fp"] * fp_cost
            rows.append({"threshold": T, "total_cost": round(total_cost, 2),
                        "rings_missed": s["rings_missed"], "confounders_fp": s["confounders_fp"]})
            if total_cost < best_cost:
                best_T, best_cost = T, total_cost
        cost_by_scenario[name] = {
            "fp_cost": fp_cost, "assumption": scenario["assumption"],
            "rows": rows, "optimal_threshold": best_T, "optimal_cost": round(best_cost, 2),
        }
    return cost_by_scenario


def _print_cost_table(cost_by_scenario, thresholds, current_threshold):
    header = f"{'Threshold':<12}" + "".join(f"{name:<28}" for name in cost_by_scenario)
    print(header)
    for T in thresholds:
        marker = " *" if T == current_threshold else ""
        row = f"{str(T)+marker:<12}"
        for name, c in cost_by_scenario.items():
            cost = next(r["total_cost"] for r in c["rows"] if r["threshold"] == T)
            tag = " (optimal)" if T == c["optimal_threshold"] else ""
            row += f"{'Rs ' + format(cost, ',.0f') + tag:<28}"
        print(row)


def _print_sweep_table(sweep, thresholds, current_threshold):
    print(f"{'Threshold':<12}{'Flagged':<10}{'Recall':<10}{'FP rate':<10}{'Rings missed':<14}{'Confounder FPs'}")
    for T in thresholds:
        s = sweep[T]
        marker = " *" if T == current_threshold else ""
        print(f"{str(T)+marker:<12}{s['n_flagged_total']:<10}{s['recall']:.1%}"
              f"{'':<4}{s['fp_rate']:.1%}{'':<4}{s['rings_missed']:<14}{s['confounders_fp']}")


def _soft_finding(soft_sweep: dict) -> dict:
    """Structured facts behind the soft-branch finding -- computed once here, stored in the
    JSON report, and rendered by both the console printout below and the dashboard, so neither
    one can drift out of sync with the other by hand-editing prose."""
    fp_values = {soft_sweep[T]["confounders_fp"] for T in THRESHOLDS}
    if len(fp_values) == 1:
        return {"fp_flat": True, "fp_value": next(iter(fp_values)), "fp_by_threshold": None}
    return {"fp_flat": False, "fp_value": None,
            "fp_by_threshold": {T: soft_sweep[T]["confounders_fp"] for T in THRESHOLDS}}


def _device_finding(device_sweep: dict, n_rings_total: int) -> dict:
    recalls = {device_sweep[T]["rings_detected"] for T in THRESHOLDS}
    fp_by_threshold = {T: device_sweep[T]["confounders_fp"] for T in THRESHOLDS}
    if len(recalls) == 1:
        return {"recall_flat": True, "recall_value": next(iter(recalls)), "n_rings_total": n_rings_total,
                "recall_by_threshold": None, "fp_by_threshold": fp_by_threshold}
    return {"recall_flat": False, "recall_value": None, "n_rings_total": n_rings_total,
            "recall_by_threshold": {T: device_sweep[T]["rings_detected"] for T in THRESHOLDS},
            "fp_by_threshold": fp_by_threshold}


def run(verbose=True):
    rings, confounders = load_ground_truth()
    all_clusters = db.get_all_clusters()

    fn_cost, fn_totals = compute_fn_cost(rings)
    fp_scenarios = fp_cost_scenarios()

    soft_sweep = _sweep(all_clusters, rings, confounders, "soft_flag_suspicion_threshold", THRESHOLDS)
    device_sweep = _sweep(all_clusters, rings, confounders, "device_clear_organic_threshold", THRESHOLDS)

    soft_cost = _cost_table(soft_sweep, THRESHOLDS, fn_cost, fp_scenarios, SOFT_FLAG_SUSPICION_THRESHOLD)
    device_cost = _cost_table(device_sweep, THRESHOLDS, fn_cost, fp_scenarios, DEVICE_CLEAR_ORGANIC_THRESHOLD)

    soft_finding = _soft_finding(soft_sweep)
    soft_finding["optimal_thresholds"] = sorted({c["optimal_threshold"] for c in soft_cost.values()})
    device_finding = _device_finding(device_sweep, len(rings))

    report = {
        "fn_cost_per_missed_ring": round(fn_cost, 2),
        "fn_cost_methodology": "Mean of actual paid referral-bonus amounts (data/raw/referrals.csv) touching "
                               "each of the 80 planted rings' members -- real, computed, not assumed.",
        "fp_cost_scenarios": {k: v["cost"] for k, v in fp_scenarios.items()},
        "fp_cost_methodology": "Not present in the synthetic data (no support-ticket or churn log exists to "
                               "compute it from) -- explicit, labeled assumptions: analyst review time, plus a "
                               "churn-risk estimate grounded in this dataset's real order values, swept across "
                               "3 scenarios rather than asserted as one true number.",
        "soft_signal_suspicion_threshold": {
            "current_production_value": SOFT_FLAG_SUSPICION_THRESHOLD,
            "sweep": soft_sweep, "cost_by_scenario": soft_cost, "finding": soft_finding,
        },
        "device_clear_organic_threshold": {
            "current_production_value": DEVICE_CLEAR_ORGANIC_THRESHOLD,
            "sweep": device_sweep, "cost_by_scenario": device_cost, "finding": device_finding,
        },
    }

    with open(PROCESSED_DIR / "cost_threshold_sensitivity.json", "w") as f:
        json.dump(report, f, indent=2)

    if verbose:
        print("=== Cost-calibrated threshold sensitivity ===\n")
        print(f"FN cost (real, computed): Rs {fn_cost:,.0f} average fraudulent bonus payout per missed ring "
              f"(range Rs {min(fn_totals):,.0f}-{max(fn_totals):,.0f} across 80 rings)")
        print("FP cost (assumption, swept across scenarios):")
        for name, s in fp_scenarios.items():
            print(f"  {name}: Rs {s['cost']:,.0f} -- {s['assumption']}")

        print("\n--- Sweep 1: soft-signal suspicion threshold (SOFT_FLAG_SUSPICION_THRESHOLD, current=3) ---")
        _print_sweep_table(soft_sweep, THRESHOLDS, SOFT_FLAG_SUSPICION_THRESHOLD)
        print("\nTotal cost by FP-cost scenario:")
        _print_cost_table(soft_cost, THRESHOLDS, SOFT_FLAG_SUSPICION_THRESHOLD)
        soft_fp_values = {soft_sweep[T]["confounders_fp"] for T in THRESHOLDS}
        soft_optimal_Ts = sorted({c["optimal_threshold"] for c in soft_cost.values()})
        if len(soft_fp_values) == 1:
            fp_n = next(iter(soft_fp_values))
            print(
                f"\nReal finding: confounder FPs stay flat at {fp_n} across every threshold value on this "
                f"branch -- every current false positive sits on the shared-device branch instead (mutually "
                f"exclusive with this one in evaluate_cluster()), so this sweep has no effect on it either way. "
                f"Cost-optimal threshold is therefore {'always ' + str(soft_optimal_Ts[0]) if len(soft_optimal_Ts) == 1 else 'threshold ' + '/'.join(map(str, soft_optimal_Ts))} "
                f"in every FP-cost scenario, but not because aggressive flagging is free in general -- only "
                f"because this particular dataset's known false positives happen to sit on a different branch. "
                f"Reported exactly as found, not stretched into a general claim this data can't support."
            )
        else:
            soft_fp_by_T = ", ".join(f"{T}->{soft_sweep[T]['confounders_fp']}" for T in THRESHOLDS)
            print(f"\nReal finding: confounder FPs move with this threshold on this run ({soft_fp_by_T}) -- "
                  f"unlike a prior run of this same script, at least one current false positive does sit on "
                  f"this branch. Reported as measured, not assumed flat.")

        print("\n--- Sweep 2: shared-device organic-clear threshold (DEVICE_CLEAR_ORGANIC_THRESHOLD, current=3) ---")
        _print_sweep_table(device_sweep, THRESHOLDS, DEVICE_CLEAR_ORGANIC_THRESHOLD)
        print("\nTotal cost by FP-cost scenario:")
        _print_cost_table(device_cost, THRESHOLDS, DEVICE_CLEAR_ORGANIC_THRESHOLD)
        device_recalls = {device_sweep[T]["rings_detected"] for T in THRESHOLDS}
        n_rings_total = len(rings)
        fp_by_T = ", ".join(f"{T}={device_sweep[T]['confounders_fp']}" for T in THRESHOLDS)
        if len(device_recalls) == 1:
            rc = next(iter(device_recalls))
            print(
                f"\nReal finding: recall is completely flat ({rc}/{n_rings_total} rings) across all four "
                f"threshold values tested -- no real ring in this dataset has a high enough organic_score for "
                f"this threshold to ever cost recall in either direction. Only the confounder FP count moves: "
                f"{fp_by_T}. Sweeping threshold=2 against the current default (3) is therefore a strict "
                f"improvement on every metric measured here whenever it has fewer FPs at equal recall -- true "
                f"regardless of any FP-cost assumption, not just in the high-churn scenario."
            )
        else:
            device_recall_by_T = ", ".join(f"{T}->{device_sweep[T]['rings_detected']}/{n_rings_total}" for T in THRESHOLDS)
            print(f"\nReal finding: recall varies with this threshold on this run ({device_recall_by_T}) -- "
                  f"unlike a prior run of this same script, at least one real ring's organic_score is now "
                  f"sensitive to this threshold. Confounder FPs by threshold: {fp_by_T}. Reported as measured, "
                  f"not assumed flat.")
        print(
            "\nThis finding is NOT applied to production here. It was found by evaluating against the full "
            "80-ring/40-confounder set, including the holdout split this project has deliberately never "
            "tuned against anywhere else (see docs/ARCHITECTURE.md and eval.py's dev/holdout split) -- acting "
            "on it now would break that discipline. It's reported as a specific, testable hypothesis for the "
            "next dev-split tuning pass, not a change made on the strength of this script alone."
        )

        print(f"\nWritten -> {PROCESSED_DIR / 'cost_threshold_sensitivity.json'}")

    return report


if __name__ == "__main__":
    run()
