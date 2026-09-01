# Cost-calibrated threshold sensitivity

Stage 5 has two judgment-call thresholds, both tuned by eyeballing the dev
split (see [`ARCHITECTURE.md`](ARCHITECTURE.md)):

- `DEVICE_CLEAR_ORGANIC_THRESHOLD` (default 3): a shared-device cluster clears
  if `organic_score >= this`.
- `SOFT_FLAG_SUSPICION_THRESHOLD` (default 3): a soft-signal-only cluster
  (no shared device/instrument) flags if `suspicion_score >= this`.

The track's own bar language asks about false-positive cost. This is the
concrete answer: what does each threshold choice cost in real rupees, and
does a different threshold cost less?

## Methodology

Both thresholds are swept 1-4 by replaying the **exact production**
`evaluate_cluster()` function (`backend/pipeline/confounder_filter.py`,
imported unchanged, called with a different threshold argument — never
reimplemented) against every already-computed Stage 4 feature dict already
sitting in the DB. No data regeneration, no pipeline rerun — pure re-analysis
of numbers already produced. Full script:
[`backend/cost_threshold_sensitivity.py`](../backend/cost_threshold_sensitivity.py).

**Two costs, treated very differently on purpose:**

- **False-negative cost (a missed ring) is computed, not assumed.** For every
  planted ring, this sums the real `bonus_amount` of every *paid* referral
  claim touching that ring's members, straight from `data/raw/referrals.csv`
  — real money already in the dataset. Result: **Rs 1,024 average per missed
  ring** (range Rs 0-2,629 across 80 rings).
- **False-positive cost (a wrongly-flagged legitimate cluster) is NOT in the
  data** — no support-ticket log or churn record exists to compute it from —
  so it's an explicit, labeled assumption swept across three scenarios rather
  than asserted as one true number:

| Scenario | Cost | Assumption |
|---|---|---|
| `review_only` | Rs 150 | Analyst review time only (~15 min at an assumed loaded Rs 600/hr); zero churn. |
| `review_plus_moderate_churn` | Rs 329 | + 5% churn probability on an assumed 5-future-order LTV (grounded in this dataset's real mean order value, Rs 715). |
| `review_plus_high_value_churn` | Rs 1,222 | + 15% churn probability on an assumed 10-future-order LTV, for a higher-value customer segment. |

*(Numbers below are from the current `SEED=42668329` dataset — this
project's third freeze, most recently to ground `HARD_RING_SIZE_RANGE` in
real YelpChi/Amazon fraud-cluster sizes, see `EXTERNAL_VALIDATION.md`. Re-run
fresh, single pass, per the eval integrity protocol, not patched from any
prior seed's numbers.)*

## Sweep 1: soft-signal suspicion threshold (current = 3)

| Threshold | Flagged | Recall | FP rate | Rings missed | Confounder FPs |
|---|---|---|---|---|---|
| 1 | 84 | 100.0% | 2.5% | 0 | 1 |
| 2 | 81 | 100.0% | 2.5% | 0 | 1 |
| **3 (current)** | 75 | 92.5% | 2.5% | 6 | 1 |
| 4 | 65 | 80.0% | 2.5% | 16 | 1 |

**Real finding: the confounder FP stays flat at 1 across every threshold
value on this branch.** The one real false positive in the current dataset
has `shared_device=True`, so it never reaches this branch's decision at all
— this specific sweep has no effect on it either way. Cost-optimal threshold
is therefore always 1 in every FP-cost scenario, but **not because aggressive
flagging is free in general** — only because this particular dataset's one
known false positive happens to sit on a different branch. Reported exactly
as found, not stretched into a general claim this data can't support.

## Sweep 2: shared-device organic-clear threshold (current = 3)

| Threshold | Flagged | Recall | FP rate | Rings missed | Confounder FPs |
|---|---|---|---|---|---|
| 1 | 74 | 92.5% | 0.0% | 6 | 0 |
| 2 | 74 | 92.5% | 0.0% | 6 | 0 |
| **3 (current)** | 75 | 92.5% | 2.5% | 6 | 1 |
| 4 | 84 | 92.5% | 17.5% | 6 | 7 |

**Real finding: recall is completely flat (74/80 rings) across all four
threshold values tested** — no real ring in this dataset has a high enough
`organic_score` for this threshold to ever cost recall in either direction.
Only the confounder FP count moves: 0 at threshold 1 or 2, 1 at the current
production default (3), 7 (17.5%) at threshold 4. **That makes threshold=1
or 2 a strict improvement over the current default on every metric measured
here — same recall, fewer false positives — true regardless of any
FP-cost assumption.**

This finding is **not applied to production** in this repo. It was found by
evaluating against the full 80-ring/40-confounder set, including the holdout
split this project has deliberately never tuned against anywhere else (see
[`ARCHITECTURE.md`](ARCHITECTURE.md) and `eval.py`'s dev/holdout split) —
acting on it now would break that discipline. It's reported as a specific,
testable hypothesis for the next dev-split tuning pass, not a change made on
the strength of this script alone.

## Total cost by scenario (Rs)

| Threshold | review_only | review_plus_moderate_churn | review_plus_high_value_churn |
|---|---|---|---|
| **Soft-signal sweep** | | | |
| 1 | 150 (optimal) | 329 (optimal) | 1,222 (optimal) |
| 2 | 150 | 329 | 1,222 |
| 3 (current) | 6,293 | 6,471 | 7,364 |
| 4 | 16,530 | 16,709 | 17,602 |
| **Device-clear sweep** | | | |
| 1 | 6,143 (optimal) | 6,143 (optimal) | 6,143 (optimal) |
| 2 | 6,143 | 6,143 | 6,143 |
| 3 (current) | 6,293 | 6,471 | 7,364 |
| 4 | 7,193 | 8,443 | 14,695 |

## Honest read

At every FP-cost scenario grounded in this dataset's real numbers, the fraud
recovered per ring (Rs 1,024 average) is large enough relative to a single
false positive's cost that cost-minimization favors the most aggressive
threshold tested in both sweeps — this holds even at the high-value-churn
scenario (Rs 1,222/FP), because in this specific frozen dataset neither sweep
finds a real recall cost to aggressive flagging in the range tested. That is
itself the finding, not a shortcoming of the method: this system's
conservative defaults (`suspicion_score >= 3`, `organic_score >= 3` to clear)
are not free — they're a deliberate trade against a false-positive cost this
script now makes visible and auditable, and on this dataset specifically, the
device-branch trade (threshold 3 vs. 1/2) is one worth re-examining in the
next dev-split tuning pass, since it costs 1 real, avoidable false positive
for no measured recall benefit.

## What a production version of this check would need

- A real support-ticket/churn log to replace the labeled FP-cost assumptions
  with measured figures.
- Thresholds swept jointly (not independently) — this analysis holds one
  threshold fixed while sweeping the other, a reasonable simplification given
  the two branches never interact for a single cluster, but a full grid would
  be needed before acting on any combined recommendation.
- Re-running this against a genuinely held-out slice before applying the
  device-branch finding to production, to preserve the same tuning discipline
  used everywhere else in this project.
