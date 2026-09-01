# Realism calibration parameters

A small, deliberately isolated class of constants in `backend/generate_data.py`
(the `REALISM_CALIBRATION` registry, plus the `USE_GROUNDED_DEVICE_SHARING`
switch next to it) that ground part of the synthetic data generator in cited
external statistics rather than an invented number. This document exists
because one change to this exact class of parameter already had a real,
unpredicted downstream effect — see "Case study" below — and the fix was to
make that class of parameter harder to change blindly, not to add a warning
comment and move on.

## Why these are isolated from every other constant in the generator

Most of `generate_data.py`'s constants (ring sizes, burst windows, order-value
noise) define the synthetic *fraud* patterns this system is built to detect —
changing them changes the test, and that's expected and fine, gated by the
existing Eval Integrity Protocol (freeze, fresh seed, run once). The
`REALISM_CALIBRATION` parameters are different in kind: they don't touch any
planted ring's fraud signal at all. They change how *organic, legitimate*
accounts behave (whether real families and hostel roommates share a device) —
which means changing them can shift how much legitimate-looking dense
structure exists in the graph, with no dial anywhere that tells you in advance
how far that ripples into a downstream cross-check that was never designed to
be sensitive to it.

## Case study: the FRAUDAR recall drop

Flipping `USE_GROUNDED_DEVICE_SHARING` False → True for the `SEED=51238923`
re-freeze (grounding household device-sharing at 55% and adding hostel
device-sharing at 15%, both cited to real Indian survey data — see the
registry's `source` fields in `generate_data.py`) coincided with FRAUDAR's
hard-signal ring recall dropping from 15/40 (37.5%) to 5/40 (12.5%) — see
[`FRAUDAR_CROSSCHECK.md`](FRAUDAR_CROSSCHECK.md). At the time, that document
reported a plausible mechanism (more legitimate dense structure diluting
FRAUDAR's density-peeling) but explicitly flagged that it had **not** isolated
that cause from ordinary seed-to-seed variance — the seed changed
(`20260828` → `51238923`) in the same re-freeze.

**Isolated directly, not left as a guess.** `backend/fraudar_seed_isolation.py`
generates three disposable datasets (never touching `data/raw/` or
`data/ground_truth/`) holding one variable fixed while changing the other:

| Variant | Seed | Grounding | FRAUDAR blocks found | Hard-ring recall |
|---|---|---|---|---|
| A — original pre-refreeze dataset | `20260828` | OFF | 18 | 15/40 (37.5%) |
| B — new seed only | `51238923` | OFF | 13 | 10/40 (25.0%) |
| C — current committed dataset | `51238923` | ON | 11 | 5/40 (12.5%) |

Variant A reproduces the exact prior result (15/40), confirming the isolation
harness itself is correct before trusting its decomposition.

**Result: the drop splits exactly evenly between the two causes, not
dominated by either.**

- Seed-only effect (A → B): **−5 rings**
- Grounding-only effect (B → C): **−5 rings**
- Total observed change (A → C): **−10 rings**

Neither cause is negligible, and neither is solely responsible. Half of what
looked like a realism-recalibration side effect was, on direct measurement,
ordinary run-to-run variance in which 40 rings happen to get drawn and how
they overlap in attribute space — the kind of variance every prior single-seed
result in this project already carries and states plainly. The other half is
real: grounding device-sharing in actual survey statistics measurably added
enough legitimate dense structure to cost FRAUDAR 5 more clean ring
isolations, on the identical 40 underlying rings. Both facts are worth
knowing, and neither would have been visible from the single before/after
comparison alone.

Run it yourself: `python -m backend.fraudar_seed_isolation`. Output persisted
to `data/processed/fraudar_seed_isolation.json`.

## The registry

`backend/generate_data.py`'s `REALISM_CALIBRATION` dict — one entry per
grounded probability, each carrying its `value`, its `source` (the specific
cited survey/report), and `known_downstream_effects` (which docs/scripts have
already been shown, or are structurally likely, to move when this value
changes). `USE_GROUNDED_DEVICE_SHARING` stays a plain top-level bool next to
the registry rather than inside it — `fraudar_seed_isolation.py` toggles it
directly at runtime to run the decomposition above, and it's a switch, not a
value with its own citation.

## Required process before changing any value in this registry

Stated in the code itself (`generate_data.py`, directly above the registry),
repeated here as the canonical reference:

1. **Re-run `backend/fraudar_seed_isolation.py` with the new value.** This is
   the one downstream number already proven sensitive to this exact class of
   change — checking it isn't optional caution, it's the concrete lesson from
   the case study above.
2. **Treat it as a generator-logic change requiring a fresh, never-used
   seed** (registered in `data/adversarial_recommender/used_seeds.json`), not
   a patch applied on top of the currently-frozen seed — the same rule already
   applied when `USE_GROUNDED_DEVICE_SHARING` itself was first flipped.
3. **Re-run every doc/script listed in the changed parameter's
   `known_downstream_effects`** and update any stale numbers found — the same
   downstream re-verification sweep already performed for the `SEED=51238923`
   re-freeze (which caught and fixed stale narrative bugs in
   `fairness_audit.py` and `cost_threshold_sensitivity.py` at the time).

This is scoped deliberately narrowly: it governs the handful of
survey-grounded realism constants in `generate_data.py`, not a general
configuration system for the whole project. Stage 5's detection thresholds
already have their own, different governance (impact-simulated per change via
`cost_threshold_sensitivity.py` / the adversarial recommender's Stage 4) and
are out of scope here.
