# Time-drift simulation

Every eval in this project so far is a single point in time: one frozen
dataset, one pipeline run, one set of numbers. This asks a different
question — does detection hold up as fraud tactics evolve across successive
periods, or does it decay? Follows the same round-over-round escalation
methodology already cited for the adversarial recommender ("A multi-rounded
adversarial scenario for graph-based promo fraud detection," Springer SNAM,
Dec 2025), applied across sequential time periods instead of approve/reject
rounds.

## Design

**Reuses existing generator logic rather than parallel code** — with one
real correction along the way (see "A real construction bug, found and
fixed" below). Two ring populations, both injected every period alongside
the real, unmodified frozen background/confounder traffic:

- **Shared-device population**: `concurrent_attack_stress_test.py`'s
  `build_soft_masking_ring()`, reused unchanged, fed this period's evolving
  signup-spread / order-CV / engagement targets.
- **No-shared-device population**: a new generator (see below), driven by a
  single `sophistication` scalar from 0.0 (naive) to 1.0 (fully evasive).

**Non-negotiable, held throughout**: Stage 1-5 (`backend/pipeline/*.py`) is
called completely unmodified, zero threshold overrides, every single
period. No retraining, no adversarial-recommender-style fix applied
mid-simulation — the point is isolating "does static detection decay
against an adapting adversary" from "did detection improve," and mixing the
two would erase the result.

**Adaptive, not pre-baked**: each population's knobs only move to the next
period's harder setting if that population was *still being caught* in the
period just measured (`recall > 0`). A population that already reached 0%
recall has no further reason to change — this conditions the schedule on
the actual measured outcome each period, not a fixed ramp decided in
advance.

**Isolation**: 4 periods × 8 rings/population injected into a fresh
disposable tempdir copy of the real `data/raw/` every period; the original
is never touched. Confounder false positives use the same baseline-control
method established in `CONCURRENT_ATTACK_STRESS_TEST.md` (computed once,
since the background is identical every period). Fresh seed (`55019284`,
registered in `used_seeds.json`).

Run: `python -m backend.time_drift_simulation`

## A real construction bug, found and fixed

The first attempt reused `attack_generator.generate_variant()` for the
no-shared-device population, fed deliberately "naive" (obviously fraudulent)
knob targets for period 1. Result: **0% recall in period 1** — the supposedly
easy, naive baseline was never caught at all, giving the simulation nowhere
to decay from. Diagnosed rather than assumed: `generate_variant()` was
purpose-built for an *already-evasive* attack, and hardcodes organic-range
claim timing (`random.uniform(0.5, 14)` days, always) and continuous
post-claim engagement regardless of any target passed to it — confirmed
directly, this means a `generate_variant()` ring can score at most 2 of 4 on
`suspicion_score` (burst + templated only; fast-claim and dormancy can never
trigger by construction), never reaching `SOFT_FLAG_SUSPICION_THRESHOLD=3`
no matter how "suspicious" its other knobs are set. This was the wrong tool
for a naive baseline — reusing it here would have made the whole test
meaningless (decay from zero is not decay). Fixed by writing
`build_naive_to_evasive_ring()`, a new generator whose *every*
suspicion-relevant parameter (signup spread, order-value CV, claim timing,
and whether the ring goes dormant after claiming) is driven continuously by
one `sophistication` scalar, converging at `sophistication=1.0` on the same
organic-mimicking shape `generate_variant()` already proves defeats Stage 5.
Re-run after the fix: period 1 caught 8/8 (100%), giving the simulation a
real baseline to decay from.

## Result — per period, never blended

| Period | No-shared-device recall | Shared-device recall | Confounder FP rate |
|---|---|---|---|
| 1 | **100%** (8/8) | **100%** (8/8) | 2.5% (1/40) |
| 2 | **0%** (0/8) | 100% (8/8) | 2.5% (1/40) |
| 3 | 0% (0/8) | 100% (8/8) | 2.5% (1/40) |
| 4 | 0% (0/8) | **25%** (2/8) | 2.5% (1/40) |

**No-shared-device: a cliff, not a gradual slope.** Recall drops from 100%
to 0% between period 1 (`sophistication=0.0`) and period 2
(`sophistication=0.33`), then the adaptive rule correctly stops evolving
further (0% recall means no measured pressure to keep changing). This is
not an artifact glossed over: at `sophistication=0.33`, signup spread is
already ~10.1 days — past `BURST_DAYS=7`, so `is_burst` flips from true to
false — while the claim-timing window has widened enough that `is_fast_claim`
also becomes unreliable. Losing two of the four suspicion checks at once
drops `suspicion_score` below the flag threshold (3) for essentially every
ring in the sampled period. `is_burst` is a hard binary threshold in the
real production code (`confounder_filter.py`), not a fuzzy one — some step
behavior here is expected by construction. What this 4-period design cannot
resolve is exactly where between `sophistication=0.0` and `0.33` the true
crossing point sits; reported as a real limit of this test's resolution,
not smoothed into a slope the data doesn't show.

**Shared-device: a later, gentler decay.** Recall holds at 100% through
period 3, then drops to 25% at period 4, once the knobs reach the exact
real production thresholds (`spread_out_days=21`, `diverse_order_cv=0.28`,
`engaged_sessions=1.5`) — the same organic-clear boundary already
characterized elsewhere this session (a probabilistic per-ring outcome, not
a guaranteed bypass; see `CONCURRENT_ATTACK_STRESS_TEST.md`'s 1/4 result on
the identical archetype). Consistent with, not contradicting, that earlier
finding.

**Confounder false-positive rate: flat at 2.5% (1/40) in every period.**
The one flagged confounder is the same pre-existing "tight household" false
positive present with zero rings injected at all (see
`CONCURRENT_ATTACK_STRESS_TEST.md`'s baseline-control methodology) — no new
interference from either evolving population, in any period.

## Honest read

**Trend, no-shared-device: decaying** (100% → 0%), but as a step, not a
slope — this test's 4-period resolution cannot distinguish a genuinely
instantaneous threshold effect from a fast-but-continuous one in the
`[0.0, 0.33]` sophistication gap. **Trend, shared-device: decaying** (100%
→ 25%), later and less completely than the no-device population within the
same 4 periods, because the device-branch's organic-clear condition
requires all three checks to clear *simultaneously*, a harder bar for an
adversary to reach than any single suspicion check flipping. **Trend,
confounder false positives: flat** — evolving fraud tactics did not, in
this run, create new collateral damage against real legitimate clusters.

This is a single run at one seed, one period count, and one pair of
archetypes — not a claim that every possible adaptation path decays at this
exact rate. What it does establish, measured rather than assumed: static
Stage 1-5 logic is not immune to an adversary that learns over time, decay
is real and substantial for both archetypes tested within just 4 periods,
and the *shape* of that decay differs meaningfully by archetype (a sharp
cliff vs. a later, partial slide) — a distinction a single blended number
would have erased.
