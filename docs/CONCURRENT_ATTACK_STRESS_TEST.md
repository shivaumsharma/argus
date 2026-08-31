# Concurrent multi-ring attack stress test

Every adversarial test built so far — `adversarial_stress_test.py`, the
recommendation engine's `attack_generator.py` — injects exactly **one**
evasive ring into a disposable copy of the dataset and asks whether it's
caught. That's a real test, but it structurally cannot surface an
*interference* failure mode: does adding several sophisticated, evasive
rings **at the same time** change anything, either for the rings themselves
or for the real, planted, legitimate confounders sitting alongside them?
Multiple simultaneous rings add real graph mass — new nodes and edges —
into the same connected-components pass and the same global Louvain
partition. A single-ring test can never see whether that shifts anything.

## Design

**Two evasion strategies, deliberately different, not the same ring
repeated.**

- **Masks hard signals** (4 rings): no shared device or instrument at all —
  the only edge Stage 1 can find is the referral chain, with organic
  -looking timing. This is `backend/adversarial_recommender/attack_generator.py`'s
  `generate_variant()`, reused **completely unchanged** (re-namespaced only
  so several can be injected without id collisions) — the same already
  -validated evasion logic behind the recommender's round 2+.
- **Masks soft signals** (4 rings): the opposite trade. **Does** share a
  device — the hard signal Stage 2 exists to catch — but dials signup
  spread, order-value diversity, and post-signup engagement to try to clear
  all three of Stage 5's organic checks at once on the device branch
  (`DEVICE_CLEAR_ORGANIC_THRESHOLD`). This is a new archetype, built for
  this test using the same organic-knob-targeting technique
  `attack_generator.py` already established, applied to a branch of
  `evaluate_cluster()` no existing test had exercised.

All 8 rings are injected **together, in one pass**, into a disposable
tempdir copy of `data/raw/` (never modified), run once through the
unmodified Stage 1-5 pipeline, cleaned up in a `finally` block. Fresh seed
(`86358735`, checked against and registered in
`data/adversarial_recommender/used_seeds.json`), never reused.

Run: `python -m backend.concurrent_attack_stress_test`

## Result — raw per-ring, never blended

| Ring | Strategy | Outcome |
|---|---|---|
| CHM00-03 (4 rings) | masks hard signals | **0/4 caught** — clustered by Stage 3 (soft), not flagged by Stage 5 |
| CSM00 | masks soft signals | **caught** — flagged at Stage 2 (hard) |
| CSM01-03 (3 rings) | masks soft signals | **missed** — clustered by Stage 2 (hard), not flagged by Stage 5 |

**1 of 8 rings caught.** Two honest reads, not one blended number:

- The 0/4 "masks hard signals" result is not new — it's the exact same
  evasion `adversarial_stress_test.py` already established defeats Stage 5
  by design. What *is* new information here: it evades identically when
  four of them are injected at once, alongside four other simultaneous
  attacks and the dataset's full background/confounder traffic — the
  presence of other concurrent rings doesn't accidentally trip it up.
- The "masks soft signals" archetype is genuinely new, and its 1/4 result
  is a real, useful finding on its own: dialing all three organic checks to
  clear at once is **not reliable** — it worked for 3 of 4 attempts, and
  failed for one (CSM00), because each ring's actual `order_value_cv` and
  `post_signup_engagement` depend on real random per-account draws, not a
  guaranteed outcome of targeting a threshold. An adversary using this
  strategy would need to verify their own cluster's behavior clears the
  bar before relying on it — it's not a deterministic bypass.

## Interference check — the actual point of this test

A naive check ("is any confounder flagged in this run?") would have found
1 of 40 confounders flagged (`CONF_HOUSEHOLD_03`) and risked reporting it
as evidence of interference. It isn't — verified directly with a proper
control, not assumed: `CONF_HOUSEHOLD_03` is this dataset's one
**pre-existing, already-known** false positive (the "tight" household
variant documented in `ARCHITECTURE.md`'s Known Limitations — compressed
signup window, fails the spread-out check). It is flagged in a **zero
-rings-injected baseline pass** run against the identical unmodified data,
before any of the 8 attacks are added. Any interference check that skips
this control would misattribute an unrelated, already-documented miss to
this test's own finding.

| | Confounders flagged |
|---|---|
| Baseline (0 rings injected) | `CONF_HOUSEHOLD_03` (1) |
| With 8 concurrent attacks injected | `CONF_HOUSEHOLD_03` (1) |
| **New interference** (flagged with attacks, not in baseline) | **none** |

**Result: zero new interference found in this run.** Every confounder
flagged with the 8 attacks present was also already flagged with nothing
injected at all. Adding 8 simultaneous, deliberately evasive rings — 40
distinct new accounts' worth of graph mass, split across two structurally
different evasion strategies — did not shift Stage 2's connected components
or Stage 3's Louvain partition enough to pull any of the 40 real planted
confounders into a wrongful flag.

## Honest read

This is one run at one concurrency level (8 rings), not a sweep. It rules
out an interference effect at this specific scale and this specific mix of
evasion strategies — it does not prove no interference effect could ever
exist at a different scale (dozens of simultaneous rings), a different mix,
or a different random seed. What it *does* establish, measured rather than
assumed: Stage 2 (connected components, purely local) and Stage 3 (Louvain,
a global partition) both held their existing confounder boundaries steady
under a genuinely concurrent, mixed adversarial load in this test — the
kind of overload failure mode a single-ring test structurally cannot see at
all. The two masking strategies' raw recall (0/4 and 1/4) are consistent
with — not worse than — what single-ring testing already found, which is
itself informative: this specific concurrent scenario did not make
detection meaningfully worse than the already-documented single-ring
baseline.
