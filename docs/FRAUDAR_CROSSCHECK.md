# FRAUDAR cross-check

An independent detection method, run against the same frozen dataset, to see
whether it agrees or disagrees with this project's own pipeline — a
different question from accuracy alone. Standalone: `backend/fraudar_analysis.py`
does not import from, call, or modify anything in `backend/pipeline/`
(Stages 1-5). It only reads the already-frozen `data/raw/` CSVs and, for
comparison, the already-computed `clusters.json` / ground truth — read-only
in both directions. **"Independent" needs one qualification, not left
implicit — see "Independence, qualified" below: the detection mechanism
never sees ground truth, but one tuning decision along the way did use
inside knowledge of this project's own data.**

## Scope — read this before the numbers below

This cross-check builds its bipartite graph from **device/instrument/subnet
attributes only**. Referral-link timing and order-value signals were left
out entirely, by design (that's exactly what was asked for). That has one
direct consequence that has to be stated up front, not discovered halfway
through a table: **this cross-check can only ever speak to hard-signal
rings.** Soft-signal rings are *defined* by having no shared device or
instrument — only IP overlap plus referral-chain timing — so a graph with no
timing edges structurally cannot find them. The 0/40 soft-ring result
reported below isn't a finding about FRAUDAR's capability; it's an artifact
of what this specific test was scoped to look at. Everything below that
matters as a real comparison is scoped to the 40 hard-signal rings only.

*(Numbers below are from the current re-frozen `SEED=42668329` dataset —
`HARD_RING_SIZE_RANGE` minimum lowered 3→2, grounded in real YelpChi/Amazon
fraud-cluster sizes, see `EXTERNAL_VALIDATION.md`. This is this project's
third freeze; the number below has moved at every step — 37.5% (`SEED=20260828`)
→ 12.5% (`SEED=51238923`) → 17.5% (current) — and each move is discussed
honestly below, not hidden.)*

## The one comparable number

**FRAUDAR's recall on the 40 planted hard-signal rings, counted straight
(≥50% bidirectional member overlap, the same threshold this project's own
`eval.py` uses everywhere else — no other filtering): 7/40 (17.5%).**

That's the single number directly comparable to this project's own Stage 2,
which gets **100% (40/40)** on the identical 40 rings, from the identical
underlying device/instrument/subnet signals. Every other count in this
document (13 blocks found, 75 flagged clusters, 100%/100% precision-recall
on individual blocks) is supporting detail *about* that headline, not a
competing one — see "Overlap with our own pipeline's output" below for why
7/40 and "7 of 75" are the same 7 rings counted against two different,
non-interchangeable denominators.

**This number has moved at every one of this project's three freezes
(37.5% → 12.5% → 17.5%) — reported plainly at each step, not smoothed over.**
The middle drop (37.5%→12.5%) was isolated directly, not left as a plausible
guess. Two things changed in that re-freeze: the seed (`20260828` → `51238923`)
and `USE_GROUNDED_DEVICE_SHARING` (False → True, grounding household/hostel
device-sharing in real Indian survey data — see `ARCHITECTURE.md`).
`backend/fraudar_seed_isolation.py` generates three disposable datasets
holding one variable fixed while changing the other, to separate the two:

| Variant | Seed | Grounding | Blocks found | Hard-ring recall |
|---|---|---|---|---|
| A — original pre-refreeze dataset | `20260828` | OFF | 18 | 15/40 (37.5%) |
| B — new seed only | `51238923` | OFF | 13 | 10/40 (25.0%) |
| C — dataset after that re-freeze | `51238923` | ON | 11 | 5/40 (12.5%) |

Variant A exactly reproduces the original 15/40 result, confirming the
isolation harness itself is trustworthy before reading its decomposition.
**That drop split exactly evenly between the two causes: −5 rings from
ordinary seed-to-seed variance (A→B), −5 rings from the grounding
recalibration itself (B→C).** Neither cause dominated. Half of what looked
like a realism-recalibration side effect was the same kind of single-seed
variance every other result in this project already carries; the other half
was real — grounding device-sharing in actual survey statistics measurably
added enough legitimate dense structure to cost FRAUDAR 5 clean ring
isolations on the identical 40 underlying rings. Full methodology and the
general governance this motivated for this whole class of parameter: see
[`REALISM_CALIBRATION.md`](REALISM_CALIBRATION.md).

**The most recent move (12.5%→17.5%) is a third, separate freeze — a
different class of parameter (`HARD_RING_SIZE_RANGE`, the fraud ring's own
size shape, not organic device-sharing) and a fresh seed together, not
isolated the same way.** No forensic decomposition was run for this specific
transition — unlike the middle drop, this one wasn't the subject the user
asked to isolate, and a third disposable-dataset study for every future
freeze would be disproportionate. Reported as what it is: a real number from
a real re-freeze, moving in a direction (up) that happens to be favorable
here, on a seed drawn for a completely different, well-documented reason
(see `EXTERNAL_VALIDATION.md`'s ring-size grounding section) — not evidence
of anything about FRAUDAR beyond ordinary run-to-run variance.

**Is the primary dataset expected to move again, which would determine
whether isolating this move is worth doing yet? No — stated explicitly, not
left implicit.** Every other item of recent work touched external data only:
the YelpChi/Amazon behavioral-scoring investigation (`EXTERNAL_VALIDATION.md`)
runs against outside data with no write path to `backend/generate_data.py`
or `data/raw/`; the Elliptic coverage check is the same; the adversarial
-recommender audit-trail investigation queried `data/app.db` read-only. None
of them are generator-logic changes, so none of them require another
Eval Integrity Protocol re-freeze. The primary dataset (`SEED=42668329`) is
locked as of this pass — deep-diagnosing this specific FRAUDAR move the same
way the first drop was diagnosed would be reasonable *future* work if it's
ever wanted, but isn't currently blocked on, or racing, further primary
-dataset churn.

Stage 2's connected-components approach is unaffected by any of this: still
100% (40/40) on identical underlying signals at every freeze, exactly
because it extracts each connected component whole regardless of what
density surrounds
it — see "Why FRAUDAR misses" below.

## What FRAUDAR is, and what "independent" means here

FRAUDAR (Hooi, Song, Beutel, Shah, Shin, Faloutsos — *"FRAUDAR: Bounding
Graph Fraud in the Face of Camouflage"*, KDD 2016, best paper award) finds
dense blocks in a bipartite graph via greedy peeling: repeatedly remove
whichever node (from either side) currently contributes the least weighted
degree, tracking a density score (total weighted edge mass ÷ remaining node
count) at every step, and returning the point in that removal sequence that
maximized the score — a 2-approximation to the weighted densest-subgraph
problem. FRAUDAR's specific contribution is a *camouflage-resistant*
weighting: each attribute-side node is weighted `1/log(degree_in_full_graph
+ 5)`, so an attribute touched by many distinct users counts for less per
edge than a rare one, discouraging dilution via popular, ordinary
attributes.

The detection mechanism itself is genuinely independent, not a variant of
this project's own method: no connected components, no Louvain, no
organic-evidence filter — just density, camouflage-weighted, and it never
sees ground truth at any point while running. (One separate tuning decision
about how many blocks to *keep*, not how they're *found*, did use inside
knowledge of this project's own data — see "Independence, qualified" below
for the full story and the fix.) The exact algorithm was verified against
the public reference implementation ([safe-graph/UGFraud](https://github.com/safe-graph/UGFraud),
Apache-2.0, `UGFraud/Detector/Fraudar.py`) before writing this — the log
-weighting formula and the greedy peeling procedure were read from that code
directly, not approximated from memory. The implementation here is a clean
reimplementation, not a copy, and includes its own correctness check: a
hand-planted dense clique in a synthetic bipartite graph is recovered
exactly, including under injected camouflage (extra edges from the clique to
a widely-shared attribute) — matching the paper's own core claim.

## Bipartite graph

Users on one side, distinct shared-attribute *values* on the other (a
specific `device_fingerprint_id`, a specific `instrument_hash`, a specific
IP subnet — first three octets, matching this project's own Stage 1
definition) — an edge wherever a user has that exact value. Deliberately
excludes referral-link edges (unlike Stage 1's own graph), exactly as asked:
device/instrument/subnet only, nothing about timing.

**7,500 users, 20,903 distinct attribute values, 22,500 edges.** (Edge count
is a structural constant — each user contributes exactly 3 attribute edges,
device + instrument + subnet, regardless of how much any value is shared —
so it's identical across every seed; the distinct-attribute-value count
shifts slightly with sharing intensity.)

## Independence, qualified — a real bug found and fixed, and a circularity problem found in the fix

The first version asked for a fixed 80 blocks (matching the 80 planted
rings) and got back 15 genuine matches plus 65 degenerate single-user
"blocks" — every one of them scoring exactly 0.2791, because once no real
dense structure is left, a single leftover user-attribute edge trivially
maximizes local density and the loop kept manufacturing them. The reference
implementation's own stopping rule (stop once two consecutive block scores
are within 0.01) does not work on *this* dataset: with many planted rings of
similar size and structure, several genuinely distinct real rings land on
the exact same score by coincidence — trying that rule stopped the whole
search after just 1 block.

**The first fix introduced a real methodological problem, not just a
different bug.** It stopped the search as soon as a found block dropped
below 3 users, justified at the time as "every planted ring or confounder in
this generator has ≥3 members by construction." That justification uses
*inside knowledge of how this project's own ground truth was built* — a
smaller version of exactly the kind of ground-truth leakage this project is
careful to avoid everywhere else (dev/holdout splits never tuned on
holdout, thresholds eyeballed only against dev, etc). The greedy peeling
*mechanism* — the log-weighted density scoring, which block gets removed at
each step — never touched ground truth and stayed fully blind throughout.
But the *decision of how many blocks to keep* was informed by a fact about
our own data, not derived blind. That's a real asterisk on "independent,"
not a technicality to wave off.

**Fixed properly, not just re-justified.** The threshold is now
`min_block_users=2` — the generic mathematical floor for *any* bipartite
"sharing" relationship to exist at all (you cannot have two-or-more-people
-share-an-attribute with fewer than 2 people), a justification that doesn't
reference this dataset's construction at all. On the original
`SEED=20260828` dataset, re-running with this genuinely blind threshold
instead of the inside-knowledge one produced an **identical result**: the
same 18 blocks, same sizes, same scores, same 15/40 headline. That's real
evidence the specific number "3" wasn't doing hidden work in that run — but
that check is a confirmation performed *after* fixing the actual problem,
not a retroactive justification for having had it, and it's reported as
exactly that rather than as proof the original shortcut was fine all along.
(This `min_block_users=2` fix is the only threshold this script has ever
used since — the 13-blocks/7-of-40 result reported throughout the rest of
this document, on the current `SEED=42668329` dataset, already reflects
it.)

## Results (raw counts, not just percentages)

**FRAUDAR found 13 dense blocks** (up from 11 on the prior seed — a
different random draw of ring sizes and attribute overlaps, not a
consequence of the ring-size-range change specifically; the smallest planted
rings this generator now draws, size 2, don't show up as clean FRAUDAR
matches either way). 7 of them each *exactly* match one distinct hard-signal
ring — not just overlap it: 100% recall and 100% precision *for that
individual block*, meaning the block's members are identical to the ring's
members, member for member: `RING_HARD_32` (12 members), `RING_HARD_28`
(12), `RING_HARD_08` (13), `RING_HARD_06` (13), `RING_HARD_40` (14),
`RING_HARD_12` (14), `RING_HARD_10` (14). Those are the same 7 rings behind
the 7/40 headline number above — every one of them sits at 12-14 members,
the upper-middle-to-top of this generator's size range (`gen_hard_ring` now
draws 2-15 members, grounded in real YelpChi/Amazon fraud-cluster sizes —
see `EXTERNAL_VALIDATION.md`).

| | Count |
|---|---|
| Hard-signal rings FRAUDAR isolates as a clean, standalone block (exact 100%/100% match) | 7 / 40 |
| Hard-signal rings FRAUDAR does not isolate cleanly (see "why" below) | 33 / 40 |

**0 of 40 soft-signal rings** were matched cleanly — out of scope by
construction (see Scope above), not a capability finding.

**0 of 40 planted confounders were ever flagged as a standalone dense
block** — this is the specific disagreement check asked for, and the honest
answer is: no disagreement in the false-positive direction, at least not as
a clean, standalone detection. One tiny 2-user block touches a small sliver
of a real hostel confounder (`CONF_HOSTEL_05`, 13.3% recall of that
confounder — two of its members happen to share one device with each other,
not the whole group), far short of a real match. FRAUDAR — despite having no
explainable legitimacy filter of any kind, unlike Stage 5 — still does not
mistake a genuine household, hostel, office, or influencer network for a
fraud block on its own.

**Diluted blocks appear, and they matter for reading the above honestly.**
Beyond the 7 clean matches, the next-best remaining cuts aren't other
distinct rings — they're diluted masses that technically *touch* real ground
truth at 100% recall but single-digit precision: a 44-user block containing
all of `RING_HARD_38` (11 members, 25.0% precision); a 62-user block
containing all of `RING_HARD_35` (15 members, 24.2% precision); a 141-user
block containing all of `RING_HARD_01` (11 members, 7.8% precision) plus a
sliver of `CONF_HOUSEHOLD_02` (5 of 5 members, but only 3.5% of that block —
the confounder is fully inside it, but so is nearly everyone else); a
second 62-user block containing all of `RING_HARD_02` (15 members, 24.2%
precision) plus a sliver of `CONF_HOSTEL_01` (2 of 14 members, 3.2%
precision). On top of those, one massive **7,097-user block (94.6% of the
entire 7,500-account dataset)** touches all of `RING_SOFT_02` and all of
`CONF_INFLUENCER_01` at 0.2% and 0.6% precision respectively — the
"block" is overwhelmingly everyone else, not a detection. Reported here
exactly because the raw numbers, read carelessly, could be misquoted as
"FRAUDAR flagged a confounder" — it technically touches several, inside
blocks that are mostly the rest of the graph, which is not a meaningful
flag by any reasonable reading.

## Overlap with our own pipeline's output

This is a *different* count from the 7/40 headline above, with a different
denominator, on purpose — worth stating plainly rather than leaving two
"7 of X" numbers sitting next to each other unexplained. Our pipeline's 75
flagged clusters break down as 40 matched hard rings + 34 matched soft rings
+ 1 false positive (a confounder). FRAUDAR was never scoped to find the soft
rings or evaluate the false positive (see Scope), so "7 of 75" isn't a recall
figure — it's simply how many of those 75 clusters happen to be one of the
same 7 hard rings FRAUDAR independently found, expressed against the
denominator of *everything* our pipeline flagged rather than the 40 hard
rings that are actually comparable:

| | Count |
|---|---|
| FRAUDAR blocks that substantially match one of our 75 flagged clusters | 7 / 13 |
| Our flagged clusters that FRAUDAR also substantially finds | 7 / 75 (= the same 7 hard rings, restated against the larger denominator) |

The useful reading of this table: FRAUDAR — a completely different algorithm
family, with no access to referral timing, order values, or engagement
signals, and a detection mechanism that never sees ground truth — confirms
7 of our flagged clusters *are* real dense blocks by a completely unrelated
method's own criteria. That's genuine cross-validation that those 7
hard-ring detections aren't an artifact of this project's own
graph-clustering choices (with the one qualification on how many total
blocks got reported — see "Independence, qualified" above).

## Why FRAUDAR misses the other 33 hard rings, and what that says about Stage 2

Every ring FRAUDAR *cleanly* isolated on this dataset has 12-14 members —
the upper-middle-to-top of this generator's size range (`gen_hard_ring` now
draws 2-15) — consistent with, not contradicting, the pattern seen on both
prior seeds (≥10-member rings, then 14-15-member rings, isolate more
cleanly). Size correlates with clean separability here, more strongly on a
denser graph, but isn't a hard cutoff on any seed tested. This is a real,
well-understood limitation of *single-pass greedy peeling for multiple
simultaneous blocks*, not a bug: the largest, densest blocks get correctly
isolated first, but as peeling continues, the "next best" remaining cut in
the residual graph isn't guaranteed to align with any one remaining planted
structure — smaller rings get swept into a larger, messier leftover mass
instead, and that effect is more pronounced the more competing dense
structure (like grounded confounder device-sharing) is in the graph.

This is the concrete, measured reason this project's own Stage 2 (connected
components on the hard-signal subgraph, not a density metric) achieves 100%
recall on *all* 40 hard rings regardless of size, while a generic
density-peeling approach — run here completely independently, on the exact
same underlying attribute-sharing signals — only cleanly isolates 7. A
connected component is extracted whole regardless of how it compares to
every other component's relative density; a greedy density-maximizing walk
inherently favors the biggest, densest structure first and dilutes weaker
ones. This isn't a criticism of FRAUDAR (it wasn't designed to enumerate
*every* dense block in one pass at equal fidelity — its own paper's real
-world result finds *one* large block in a 1.47-billion-edge graph, not many
small ones); it's a genuine, informative structural difference between
"connected components as ground truth for hard signals" and "density-ranked
peeling," measured on the same data.

## What this does and doesn't establish

- **Does establish**: 7 of the 40 hard-signal rings (17.5%) are confirmed
  by an unrelated, published, camouflage-resistant method whose detection
  mechanism never sees ground truth — real cross-validation, not just an
  internal self-check, for those 7 of this project's 40/40 Stage 2
  detections. Qualified: how many total blocks got reported (13 on this
  seed, 11 and 18 on the two prior ones) used one tuning decision informed
  by this project's own data before being fixed — see "Independence,
  qualified" above. This number has moved at every one of this project's
  three freezes (37.5%→12.5%→17.5%); the middle move is isolated, not just
  plausibly explained — exactly half (−5 rings) was ordinary seed-to-seed
  variance and half (−5 rings) was the realism recalibration itself,
  confirmed by `fraudar_seed_isolation.py` — see "The one comparable number"
  above and `REALISM_CALIBRATION.md`. The most recent move was not isolated
  the same way; reported as a real number from a real re-freeze for an
  unrelated, already-documented reason, not a claim about cause.
- **Does establish**: no planted confounder is mistaken for a dense fraud
  block by a method with zero legitimacy-checking logic, at least not
  cleanly — a relevant data point for Stage 5's value, though the several
  diluted blocks (plus one 7,097-user near-graph-spanning block) mean this
  isn't a clean, unqualified "zero false positives" claim either.
- **Does not establish** that FRAUDAR is worse than this project's pipeline
  in general — it was deliberately run with far less information than Stage
  1-5 get (no referral timing, no order values, no engagement, no soft
  -signal graph at all) specifically to test the *device/instrument/subnet*
  signals in isolation, which is what was asked. A fair FRAUDAR-vs-Stage3
  comparison on soft signals would need referral-timing edges added to the
  bipartite graph, which this test deliberately didn't do.
