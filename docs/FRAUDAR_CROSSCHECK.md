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

## The one comparable number

**FRAUDAR's recall on the 40 planted hard-signal rings, counted straight
(≥50% bidirectional member overlap, the same threshold this project's own
`eval.py` uses everywhere else — no other filtering): 15/40 (37.5%).**

That's the single number directly comparable to this project's own Stage 2,
which gets **100% (40/40)** on the identical 40 rings, from the identical
underlying device/instrument/subnet signals. Every other count in this
document (18 blocks found, 74 flagged clusters, 100%/100% precision-recall
on individual blocks) is supporting detail *about* that headline, not a
competing one — see "Overlap with our own pipeline's output" below for why
15/40 and "15 of 74" are the same 15 rings counted against two different,
non-interchangeable denominators.

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

**7,500 users, 20,914 distinct attribute values, 22,500 edges.**

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
reference this dataset's construction at all. Re-running with this
genuinely blind threshold instead of the inside-knowledge one produces an
**identical result**: the same 18 blocks, same sizes, same scores, same
15/40 headline. That's real evidence the specific number "3" wasn't doing
hidden work in this particular run — but that check is a confirmation
performed *after* fixing the actual problem, not a retroactive justification
for having had it, and it's reported as exactly that rather than as proof
the original shortcut was fine all along.

## Results (raw counts, not just percentages)

**FRAUDAR found 18 dense blocks.** 15 of them each *exactly* match one
distinct hard-signal ring — not just overlap it: 100% recall and 100%
precision *for that individual block*, meaning the block's members are
identical to the ring's members, member for member. Those are the same 15
rings behind the 15/40 headline number above:

| | Count |
|---|---|
| Hard-signal rings FRAUDAR isolates as a clean, standalone block (exact 100%/100% match) | 15 / 40 |
| Hard-signal rings FRAUDAR does not isolate cleanly (see "why" below) | 25 / 40 |

**0 of 40 soft-signal rings** were matched — out of scope by construction
(see Scope above), not a capability finding.

**0 of 40 planted confounders were ever flagged as a standalone dense
block** — this is the specific disagreement check asked for, and the honest
answer is: no disagreement in the false-positive direction, at least not as
a clean, standalone detection. FRAUDAR — despite having no explainable
legitimacy filter of any kind, unlike Stage 5 — does not mistake a genuine
household, hostel, office, or influencer network for a fraud block on its
own.

**Two large "catch-all" blocks appear, and they matter for reading the above
honestly.** Once the 15 clean matches are peeled away, the next-best
remaining cut isn't another distinct ring — it's a large, diluted mass: one
140-user block and one 7,120-user block (95% of the entire 7,500-account
dataset). Both blocks technically *touch* real ground truth — the 140-user
block includes all 9 members of `RING_HARD_10` and all 6 members of
`CONF_HOUSEHOLD_03`; the 7,120-user block includes all 15 members of
`RING_SOFT_02` and all 47 members of `CONF_INFLUENCER_07` — but at 2–22%
precision, meaning the "block" is overwhelmingly everyone else, not a
detection. Reported here exactly because the raw numbers, read carelessly,
could be misquoted as "FRAUDAR flagged a confounder" — it technically
touches one, inside a block that's 95% of the whole graph, which is not a
meaningful flag by any reasonable reading.

## Overlap with our own pipeline's output

This is a *different* count from the 15/40 headline above, with a different
denominator, on purpose — worth stating plainly rather than leaving two
"15 of X" numbers sitting next to each other unexplained. Our pipeline's 74
flagged clusters break down as 40 matched hard rings + 33 matched soft rings
+ 1 wrongly-flagged confounder. FRAUDAR was never scoped to find the 33 soft
rings or evaluate the 1 confounder (see Scope), so "15 of 74" isn't a
recall figure — it's simply how many of those 74 clusters happen to be one
of the same 15 hard rings FRAUDAR independently found, expressed against the
denominator of *everything* our pipeline flagged rather than the 40 hard
rings that are actually comparable:

| | Count |
|---|---|
| FRAUDAR blocks that substantially match one of our 74 flagged clusters | 15 / 18 |
| Our flagged clusters that FRAUDAR also substantially finds | 15 / 74 (= 15 of the same 40 hard rings, restated against the larger denominator) |

The useful reading of this table: FRAUDAR — a completely different algorithm
family, with no access to referral timing, order values, or engagement
signals, and a detection mechanism that never sees ground truth — confirms
15 of our flagged clusters *are* real dense blocks by a completely unrelated
method's own criteria. That's genuine cross-validation that those 15
hard-ring detections aren't an artifact of this project's own
graph-clustering choices (with the one qualification on how many total
blocks got reported — see "Independence, qualified" above).

## Why FRAUDAR misses the other 25 hard rings, and what that says about Stage 2

Every ring FRAUDAR *cleanly* isolated has ≥10 members; every ring it missed
is mostly 3–9 members (a few 11–12-member rings were also missed, swept into
the diluted catch-all blocks instead of isolated cleanly — size correlates
strongly with clean separability here, but isn't a hard cutoff). This is a
real, well-understood limitation of *single-pass greedy peeling for multiple
simultaneous blocks*, not a bug: the largest, densest blocks get correctly
isolated first, but as peeling continues, the "next best" remaining cut in
the residual graph isn't guaranteed to align with any one remaining planted
structure — smaller rings get swept into a larger, messier leftover mass
instead.

This is the concrete, measured reason this project's own Stage 2 (connected
components on the hard-signal subgraph, not a density metric) achieves 100%
recall on *all* 40 hard rings regardless of size, while a generic
density-peeling approach — run here completely independently, on the exact
same underlying attribute-sharing signals — only cleanly isolates 15. A
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

- **Does establish**: 15 of the 40 hard-signal rings (37.5%) are confirmed
  by an unrelated, published, camouflage-resistant method whose detection
  mechanism never sees ground truth — real cross-validation, not just an
  internal self-check, for those 15 of this project's 40/40 Stage 2
  detections. Qualified: how many total blocks got reported (18) used one
  tuning decision informed by this project's own data before being fixed —
  see "Independence, qualified" above.
- **Does establish**: no planted confounder is mistaken for a dense fraud
  block by a method with zero legitimacy-checking logic, at least not
  cleanly — a relevant data point for Stage 5's value, though the two large
  diluted blocks mean this isn't a clean, unqualified "zero false positives"
  claim either.
- **Does not establish** that FRAUDAR is worse than this project's pipeline
  in general — it was deliberately run with far less information than Stage
  1-5 get (no referral timing, no order values, no engagement, no soft
  -signal graph at all) specifically to test the *device/instrument/subnet*
  signals in isolation, which is what was asked. A fair FRAUDAR-vs-Stage3
  comparison on soft signals would need referral-timing edges added to the
  bipartite graph, which this test deliberately didn't do.
