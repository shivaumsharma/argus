# Continuous Adversarial Recommendation Engine

A subsystem that continuously probes the frozen detection pipeline for
weaknesses and proposes fixes — but never applies them. One hard rule
governs everything below and is never relaxed: **this system recommends,
it never modifies live detection logic.** No code path in
`backend/adversarial_recommender/` writes to `backend/pipeline/*.py`,
`data/raw/`, `data/frozen_snapshot/`, or any previously-verified pipeline
output. Applying a validated recommendation to production remains a
separate, manual, human action outside this system entirely.

## Why this exists

Every other honesty check in this project (the adversarial stress test,
external validation, the FRAUDAR cross-check) is a single, one-shot
measurement: build one adversarial ring, see if it evades, report the
result. That's valuable but static — it answers "does detection break
here" once, not "does it keep breaking as an adversary adapts." This
subsystem automates that repeated question, following the round-over-round
methodology of **"A multi-rounded adversarial scenario for graph-based
promo fraud detection"** (Springer, *Social Network Analysis and Mining*,
published online Dec 28, 2025, DOI
[10.1007/s13278-025-01566-0](https://link.springer.com/article/10.1007/s13278-025-01566-0)
— verified directly by fetching the paper's abstract before citing it
here, not assumed to exist because it sounded plausible). That paper's
core idea — a *generator function* that governs how the adversarial graph
evolves between rounds — is what Stage 1 implements: each round targets
the specific threshold the previous round's recommendation proposed
changing, testing whether an adversary that adapts to the last fix still
gets through.

## The five stages

**Stage 1 — Attack Generator** (`attack_generator.py`). Round 1 reuses
`backend/adversarial_stress_test.py`'s existing, already-validated evasion
ring completely unchanged — it already demonstrates a real gap, so round 1
doesn't rebuild it. Round 2+ generate a variant of the same referral
-chain-only shape, with one or more of the three organic-mimicry knobs
(signup spread, order-value diversity, post-signup engagement) dialed to
sit just barely past the previous round's proposed threshold.

**Stage 2 — Gap Characterizer** (`gap_characterizer.py`). Injects the
attack into a disposable copy of the real dataset (same pattern as
`adversarial_stress_test.py`: a tempdir, cleaned up in `finally`, never
data/raw itself) and runs the *unmodified* Stage 1-5 pipeline. Reuses
`compute_features()` and `evaluate_cluster()` exactly as they are — no new
introspection tooling. If the attack evades, characterizes which single
organic check has the smallest margin above its threshold. Honest by
construction: if all three organic checks pass comfortably (organic_score
= 3/3), no single-parameter change closes the gap — tightening any one
check still leaves two passing, still enough to clear — and this is
reported as exactly that, not forced into an unsound recommendation.

**Stage 3 — Recommendation Drafter** (`recommendation_drafter.py`). Turns
one characterized gap into exactly one bounded, reviewable change: move
`<parameter>` from `<current>` to `<proposed>`, clamped to that
parameter's defined safe range (`TUNABLE_PARAMETERS` in
`confounder_filter.py`). Never a vague "improve detection."

**Stage 4 — Impact Simulation** (`impact_simulator.py`), non-negotiable.
Every recommendation is scored against the full 80-ring/40-confounder set
by replaying the real, unmodified `evaluate_cluster()` — the same reuse
pattern already proven in `cost_threshold_sensitivity.py` — with the one
parameter overridden. Both numbers are computed and stored together always:
how many more rings it would catch, and what it does to the confounder
false-positive count. A third number is checked too and shown just as
plainly: does the fix actually flag the *specific* attack that motivated
it? A fix can remove a cluster from Stage 5's "actively cleared as
organic" bucket without pushing it into "flagged," landing it in the
conservative default-no-flag middle ground instead — this happened on the
very first real recommendation this system drafted (see Results below),
and it's surfaced as a warning, not hidden.

**Stage 5 — Human Approval Gate** (`governance.py`), two gates, not one.
A pending recommendation is first approved or rejected by a reviewer, who
sees the full Stage 4 simulation. Approval triggers the re-freeze
sequence: pick a genuinely fresh seed never used before (tracked in
`data/adversarial_recommender/used_seeds.json`, seeded with every prior
seed this project has ever used: `20260828`, `2026828`, `90210`, `7`),
generate one disposable dataset with `generate_data.generate()`, and run
the full pipeline exactly once with and without the change, on that same
fresh data. Only after a human reviews *that* clean run and confirms it
does the recommendation reach `validated_approved` — the terminal state
this system's responsibility ends at. This formalizes the same discipline
already governing the primary eval (freeze parameters, one never-seen
seed, run once, report as-is) as a reusable process, not a separate,
looser standard for this subsystem.

## Audit trail

Every recommendation's full lifecycle — proposed, reviewed, re-evaluated,
finalized — is logged to the existing `audit_log` table (`db.py`) under
new `event_type` values (`recommendation_proposed`,
`recommendation_reviewed`, `recommendation_reevaluated`,
`recommendation_finalized`), extending the same mechanism the rest of this
project already uses rather than a parallel log. The structured
recommendation data itself (the parameter, the simulation numbers, the
fresh-seed reeval report) lives in a new `recommendations` table in the
same `data/app.db`.

## Real results from testing this

Round 1 (the reused base ring): organic_score 3/3 — no single-parameter
gap exists. Honest null result, not a failure of the round.

Round 2 (all three organic knobs dialed to just past their thresholds
simultaneously): found a real gap — `spread_out_days`, attack value
22.96 vs. threshold 21, the loosest of two passing checks. Drafted
recommendation: raise `spread_out_days` to 24. Simulated impact on the
full 80/40 set: **rings caught 73→73 (+0), confounder FPs 1→1 (+0)** — a
free change (zero downside) with zero measured upside against the
*existing* planted set, because none of it happens to sit in that narrow
21-24 day window. And critically: **the fix does not actually flag the
attack that motivated it** (see Stage 4 above) — approved and re-validated
on a fresh seed anyway (identical zero-delta result, confirming the first
finding wasn't a fluke of the frozen set), and reported honestly as a
real, bounded, fully-simulated recommendation that still doesn't close
the gap it was drafted for.

Rounds 3-7 (retrying the same "probe all three organic knobs" strategy
with fresh seeds after round 2's fix didn't fully close the gap): 2 of 5
rounds evaded with no single-parameter gap (organic_score 3/3 again by
chance), 3 of 5 produced no clean gap characterization at all. This
variance is real and expected — a stochastic attack generator won't find
an exploitable gap every round, and that's reported plainly rather than
tuned to look more productive than it is.

## Cadence

Default: **`MIN_HOURS_BETWEEN_AUTO_ROUNDS = 24`** (`cadence.py`),
deliberately conservative. This is a demonstration system with a synthetic
attack generator, not a live-traffic monitor — there's no cost to checking
less often, but every increase in automatic frequency is a step closer to
a reviewer clicking "approve" without really reading the Stage 4 numbers,
which defeats the entire point of the human gate. A manual trigger
(`--force`, or the dashboard's "Run round now" button) always bypasses the
gate — it only throttles the *automatic* schedule, never a human
explicitly asking for a round right now.

## Required limitations, stated plainly

- **This system can only generate evasions the attack generator is
  designed to imagine.** Every round is a variant of the same
  referral-chain-only, organic-mimicry archetype `adversarial_stress_test.py`
  already established. It cannot discover a genuinely novel real-world
  fraud technique nobody anticipated — it narrows within a known family of
  evasion, it doesn't invent a new one. A production version would need
  many independently-designed attack families, not one parametrized shape.
- **An unmanaged review cadence risks becoming a rubber-stamp process
  rather than genuine oversight.** This is exactly why the 24-hour default
  above exists and why a manual trigger, not a shortened automatic
  interval, is the intended way to run this more often during active
  development — throttling the *schedule* protects the *reviewer's
  attention*, which is the actual scarce resource the two-gate design is
  built to protect.

## Hard safety boundary (restated)

No code path in this package may write to `backend/pipeline/*.py`,
`data/raw/`, `data/frozen_snapshot/`, `data/processed/clusters.json`, or
`data/processed/eval_report.json`. Verified directly, not just claimed:
every stage of this system was tested end to end (CLI and the
Recommendations dashboard page) with `git status`/row-count/cluster-count
checks on the primary frozen data before and after — untouched every time.
The one thing this system is allowed to write to besides its own
`recommendations` table is a disposable directory
(`data/adversarial_recommender/fresh_runs/<seed>/`), deleted in a `finally`
block immediately after each Stage 5 re-eval, win or lose.
