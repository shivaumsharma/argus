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
  — real money already in the dataset. Result: **Rs 1,016 average per missed
  ring** (range Rs 0-2,258 across 80 rings).
- **False-positive cost (a wrongly-flagged legitimate cluster) is NOT in the
  data** — no support-ticket log or churn record exists to compute it from —
  so it's an explicit, labeled assumption swept across three scenarios rather
  than asserted as one true number:

| Scenario | Cost | Assumption |
|---|---|---|
| `review_only` | Rs 150 | Analyst review time only (~15 min at an assumed loaded Rs 600/hr); zero churn. |
| `review_plus_moderate_churn` | Rs 331 | + 5% churn probability on an assumed 5-future-order LTV (grounded in this dataset's real mean order value, Rs 723). |
| `review_plus_high_value_churn` | Rs 1,235 | + 15% churn probability on an assumed 10-future-order LTV, for a higher-value customer segment. |

*(Numbers below are from the re-frozen `SEED=51238923` dataset —
`USE_GROUNDED_DEVICE_SHARING` turned on, see `ARCHITECTURE.md`. Re-run fresh,
single pass, per the eval integrity protocol, not patched from the prior
`SEED=20260828` numbers.)*

## Sweep 1: soft-signal suspicion threshold (current = 3)

| Threshold | Flagged | Recall | FP rate | Rings missed | Confounder FPs |
|---|---|---|---|---|---|
| 1 | 87 | 100.0% | 5.0% | 0 | 2 |
| 2 | 83 | 100.0% | 5.0% | 0 | 2 |
| **3 (current)** | 77 | 92.5% | 5.0% | 6 | 2 |
| 4 | 67 | 80.0% | 5.0% | 16 | 2 |

**Real finding: confounder FPs stay flat at 2 across every threshold value on
this branch.** Both real false positives in the re-frozen dataset have
`shared_device=True`, so they never reach this branch's decision at all —
this specific sweep has no effect on them either way (up from 1 false
positive on the prior seed, still both on the device branch). Cost-optimal
threshold is therefore always 1 in every FP-cost scenario, but **not because
aggressive flagging is free in general** — only because this particular
dataset's known false positives happen to sit on a different branch.
Reported exactly as found, not stretched into a general claim this data
can't support.

## Sweep 2: shared-device organic-clear threshold (current = 3)

| Threshold | Flagged | Recall | FP rate | Rings missed | Confounder FPs |
|---|---|---|---|---|---|
| 1 | 74 | 92.5% | 0.0% | 6 | 0 |
| 2 | 74 | 92.5% | 0.0% | 6 | 0 |
| **3 (current)** | 77 | 92.5% | 5.0% | 6 | 2 |
| 4 | 93 | 92.5% | 25.0% | 6 | 10 |

**Real finding: recall is completely flat (74/80 rings) across all four
threshold values tested** — no real ring in this dataset has a high enough
`organic_score` for this threshold to ever cost recall in either direction.
Only the confounder FP count moves: 0 at threshold 1 or 2, 2 at the current
production default (3), 10 (25%) at threshold 4 — steeper than the prior
seed's 0/0/1/6 progression, since more real household/hostel confounders now
share a device at all (grounded probabilities), giving this threshold more
material to act on. **That makes threshold=2 a strict improvement over the
current default on every metric measured here — same recall, fewer false
positives — true regardless of any FP-cost assumption.**

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
| 1 | 300 (optimal) | 662 (optimal) | 2,470 (optimal) |
| 2 | 300 | 662 | 2,470 |
| 3 (current) | 6,396 | 6,758 | 8,566 |
| 4 | 16,557 | 16,918 | 18,727 |
| **Device-clear sweep** | | | |
| 1 | 6,096 (optimal) | 6,096 (optimal) | 6,096 (optimal) |
| 2 | 6,096 | 6,096 | 6,096 |
| 3 (current) | 6,396 | 6,758 | 8,566 |
| 4 | 7,596 | 9,405 | 18,446 |

## Honest read

At every FP-cost scenario grounded in this dataset's real numbers, the fraud
recovered per ring (Rs 1,016 average) is large enough relative to a single
false positive's cost that cost-minimization favors the most aggressive
threshold tested in both sweeps — this holds even at the high-value-churn
scenario (Rs 1,235/FP), because in this specific frozen dataset neither sweep
finds a real recall cost to aggressive flagging in the range tested. That is
itself the finding, not a shortcoming of the method: this system's
conservative defaults (`suspicion_score >= 3`, `organic_score >= 3` to clear)
are not free — they're a deliberate trade against a false-positive cost this
script now makes visible and auditable, and on this dataset specifically, the
device-branch trade (threshold 3 vs. 2) is one worth re-examining in the next
dev-split tuning pass, since it costs 2 real, avoidable false positives for no
measured recall benefit (up from 1 on the prior seed).

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
