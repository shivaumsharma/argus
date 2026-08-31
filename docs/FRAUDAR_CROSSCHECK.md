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

*(Numbers below are from the re-frozen `SEED=51238923` dataset —
`USE_GROUNDED_DEVICE_SHARING` turned on, see `ARCHITECTURE.md`. Re-run
fresh, single pass, not patched from the prior `SEED=20260828` numbers,
which found 15/40. The drop is discussed honestly below, not hidden.)*

## The one comparable number

**FRAUDAR's recall on the 40 planted hard-signal rings, counted straight
(≥50% bidirectional member overlap, the same threshold this project's own
`eval.py` uses everywhere else — no other filtering): 5/40 (12.5%).**

That's the single number directly comparable to this project's own Stage 2,
which gets **100% (40/40)** on the identical 40 rings, from the identical
underlying device/instrument/subnet signals. Every other count in this
document (11 blocks found, 77 flagged clusters, 100%/100% precision-recall
on individual blocks) is supporting detail *about* that headline, not a
competing one — see "Overlap with our own pipeline's output" below for why
5/40 and "5 of 77" are the same 5 rings counted against two different,
non-interchangeable denominators.

**This number dropped substantially from the prior seed (37.5%→12.5%) —
reported plainly, not smoothed over.** A plausible mechanism, not a
rigorously isolated one: real household/hostel device-sharing (grounded in
Indian survey data, see `ARCHITECTURE.md`) now puts more legitimate
confounders onto shared devices than before, which is exactly the kind of
added, non-fraud dense structure single-pass greedy peeling is sensitive to
diluting into. But this run also drew a different random set of ring sizes
and attribute overlaps than the prior seed, and this test has not run
multiple seeds to separate "more confounder density" from ordinary
seed-to-seed variance as the cause — stated as a real, honest limit of what
this single re-run can establish, not stretched into a confirmed causal
claim. Stage 2's connected-components approach is unaffected either way:
still 100% (40/40) on identical underlying signals, exactly because it
extracts each connected component whole regardless of what density
surrounds it — see "Why FRAUDAR misses" below.

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

**7,500 users, 20,946 distinct attribute values, 22,500 edges.** (Edge count
is a structural constant — each user contributes exactly 3 attribute edges,
device + instrument + subnet, regardless of how much any value is shared —
so it's identical across both seeds; the distinct-attribute-value count
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
used since — the 11-blocks/5-of-40 result reported throughout the rest of
this document, on the re-frozen `SEED=51238923` dataset, already reflects
it.)

## Results (raw counts, not just percentages)

**FRAUDAR found 11 dense blocks** (down from 18 on the prior seed — fewer,
not just weaker, blocks survive the same peeling process against a denser
confounder population). 5 of them each *exactly* match one distinct
hard-signal ring — not just overlap it: 100% recall and 100% precision *for
that individual block*, meaning the block's members are identical to the
ring's members, member for member: `RING_HARD_03` (15 members),
`RING_HARD_10` (15), `RING_HARD_22` (15), `RING_HARD_33` (14), `RING_HARD_34`
(15). Those are the same 5 rings behind the 5/40 headline number above —
notably, every single one of them sits at 14-15 members, the largest
size band this generator plants (`gen_hard_ring` draws 3-15 members).

| | Count |
|---|---|
| Hard-signal rings FRAUDAR isolates as a clean, standalone block (exact 100%/100% match) | 5 / 40 |
| Hard-signal rings FRAUDAR does not isolate cleanly (see "why" below) | 35 / 40 |

**0 of 40 soft-signal rings** were matched — out of scope by construction
(see Scope above), not a capability finding.

**0 of 40 planted confounders were ever flagged as a standalone dense
block** — this is the specific disagreement check asked for, and the honest
answer is: no disagreement in the false-positive direction, at least not as
a clean, standalone detection. Two tiny 2-user blocks each touch a small
sliver of a real hostel confounder (`CONF_HOSTEL_07`, `CONF_HOSTEL_08`, both
at only 13.3% recall of that confounder — two of its members happen to
share one device with each other, not the whole group), far short of a real
match. FRAUDAR — despite having no explainable legitimacy filter of any
kind, unlike Stage 5 — still does not mistake a genuine household, hostel,
office, or influencer network for a fraud block on its own.

**Three diluted blocks appear, and they matter for reading the above
honestly.** Beyond the 5 clean matches, the next-best remaining cuts aren't
other distinct rings — they're diluted masses that technically *touch* real
ground truth at 100% recall but single-digit-to-low-double-digit precision:
a 104-user block containing all of `RING_HARD_24` (13 members, 12.5%
precision); a 99-user block containing all of both `RING_HARD_02` (6
members) and `CONF_HOUSEHOLD_01` (6 members, 6.1% precision each); and a
119-user block containing all of `RING_HARD_18` (12 members, 10.1%
precision) plus over a third of `CONF_HOSTEL_06` (7 of 19 members, 5.9%
precision). On top of those, one massive **7,100-user block (94.7% of the
entire 7,500-account dataset)** touches all of `RING_SOFT_02` and all of
`CONF_INFLUENCER_05` at 0.2% and 0.6% precision respectively — the
"block" is overwhelmingly everyone else, not a detection. Reported here
exactly because the raw numbers, read carelessly, could be misquoted as
"FRAUDAR flagged a confounder" — it technically touches several, inside
blocks that are mostly the rest of the graph, which is not a meaningful
flag by any reasonable reading.

## Overlap with our own pipeline's output

This is a *different* count from the 5/40 headline above, with a different
denominator, on purpose — worth stating plainly rather than leaving two
"5 of X" numbers sitting next to each other unexplained. Our pipeline's 77
flagged clusters break down as 40 matched hard rings + 34 matched soft rings
+ 3 false positives (2 confounders, plus one other flagged cluster). FRAUDAR
was never scoped to find the soft rings or evaluate the false positives (see
Scope), so "5 of 77" isn't a recall figure — it's simply how many of those
77 clusters happen to be one of the same 5 hard rings FRAUDAR independently
found, expressed against the denominator of *everything* our pipeline
flagged rather than the 40 hard rings that are actually comparable:

| | Count |
|---|---|
| FRAUDAR blocks that substantially match one of our 77 flagged clusters | 5 / 11 |
| Our flagged clusters that FRAUDAR also substantially finds | 5 / 77 (= the same 5 hard rings, restated against the larger denominator) |

The useful reading of this table: FRAUDAR — a completely different algorithm
family, with no access to referral timing, order values, or engagement
signals, and a detection mechanism that never sees ground truth — confirms
5 of our flagged clusters *are* real dense blocks by a completely unrelated
method's own criteria. That's genuine cross-validation that those 5
hard-ring detections aren't an artifact of this project's own
graph-clustering choices (with the one qualification on how many total
blocks got reported — see "Independence, qualified" above).

## Why FRAUDAR misses the other 35 hard rings, and what that says about Stage 2

Every ring FRAUDAR *cleanly* isolated on this re-frozen dataset has 14-15
members — the top of this generator's own size range (`gen_hard_ring` draws
3-15) — an even tighter concentration than the prior seed's ≥10-member
pattern (a few of this run's 12-13-member rings were swept into the diluted
catch-all blocks instead of isolated cleanly; see the 104-user and 119-user
blocks above). Consistent with, not contradicting, the prior finding: size
correlates strongly with clean separability here, more strongly on a denser
graph, but isn't a hard cutoff either time. This is a real, well-understood
limitation of *single-pass greedy peeling for multiple simultaneous
blocks*, not a bug: the largest, densest blocks get correctly isolated
first, but as peeling continues, the "next best" remaining cut in the
residual graph isn't guaranteed to align with any one remaining planted
structure — smaller rings get swept into a larger, messier leftover mass
instead, and that effect is more pronounced the more competing dense
structure (like grounded confounder device-sharing) is in the graph.

This is the concrete, measured reason this project's own Stage 2 (connected
components on the hard-signal subgraph, not a density metric) achieves 100%
recall on *all* 40 hard rings regardless of size, while a generic
density-peeling approach — run here completely independently, on the exact
same underlying attribute-sharing signals — only cleanly isolates 5. A
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

- **Does establish**: 5 of the 40 hard-signal rings (12.5%) are confirmed
  by an unrelated, published, camouflage-resistant method whose detection
  mechanism never sees ground truth — real cross-validation, not just an
  internal self-check, for those 5 of this project's 40/40 Stage 2
  detections. Qualified: how many total blocks got reported (11 on this
  seed, 18 on the prior one) used one tuning decision informed by this
  project's own data before being fixed — see "Independence, qualified"
  above. The recall drop from 37.5%→12.5% on the re-frozen dataset is
  reported honestly, with a plausible but not rigorously isolated mechanism
  (more real confounder density diluting the same peeling process) — see
  "The one comparable number" above.
- **Does establish**: no planted confounder is mistaken for a dense fraud
  block by a method with zero legitimacy-checking logic, at least not
  cleanly — a relevant data point for Stage 5's value, though the three
  diluted blocks (plus one 7,100-user near-graph-spanning block) mean this
  isn't a clean, unqualified "zero false positives" claim either.
- **Does not establish** that FRAUDAR is worse than this project's pipeline
  in general — it was deliberately run with far less information than Stage
  1-5 get (no referral timing, no order values, no engagement, no soft
  -signal graph at all) specifically to test the *device/instrument/subnet*
  signals in isolation, which is what was asked. A fair FRAUDAR-vs-Stage3
  comparison on soft signals would need referral-timing edges added to the
  bipartite graph, which this test deliberately didn't do.
