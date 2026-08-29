# Scale stress test

Does this survive more than a demo-sized cohort? Reruns the exact same Stage
1-5 pipeline at 10x and 50x the frozen dataset's account count (75,000 and
375,000 accounts) and reports the real, measured runtime — not an assertion
that it scales.

## Safety

This never touches the frozen dataset. Generation for each scale runs in its
own subprocess (`python -m backend.generate_data --scale N --raw-dir ...
--gt-dir ...`), writing only to `data/scale_test/<N>x/`. Pipeline timing then
loads directly from that directory and calls the same Stage 1-5 functions
used everywhere else in this repo, unchanged — it never calls
`db.write_clusters()` or writes to `data/processed/clusters.json`, so
`data/app.db` (the live dashboard's backing store) is never touched. Ring and
confounder counts scale proportionally with account count (40+40+40 at 1x →
400+400+400 at 10x, etc.) rather than holding them fixed while only
background noise grows — a fixed fraud rate as volume grows is the less
realistic assumption. Full script:
[`backend/scale_stress_test.py`](../backend/scale_stress_test.py).

## Two real bottlenecks found and fixed along the way

Running this for the first time surfaced two genuine performance bugs —
reported here rather than quietly fixed and forgotten, because "we stress
tested and found real problems" is a more credible scalability story than
a clean number with no history.

**1. Stage 4 feature scoring: 270s → under 1s at 10x scale.** The original
`compute_features()` (`backend/pipeline/features.py`) re-scanned the *entire*
sessions/orders tables with pandas boolean masks on every call, once per
candidate cluster — at 10x scale (1,700 candidates against a 10x-larger
sessions table) this alone took 270 of the pipeline's 277 total seconds.
Profiling (`cProfile`) pinned the single largest cost precisely:
`pandas.Series.map()` against a plain dict, on an Arrow-backed string column,
is pathologically slow in this pandas version — 24.5 of 29.5 profiled
seconds across just 200 clusters. Fixed by pre-grouping sessions/orders by
`user_id` once in `load_data()` (`backend/pipeline/data_io.py`) into plain
per-user lists, and replacing every per-cluster pandas scan/map in
`compute_features()` with direct Python iteration over those small
pre-grouped lists. Verified byte-identical output against all 174 stored
frozen-dataset cluster features before and after, both refactor passes.

**2. Data generation: superlinear → near-linear.** `add_organic_referrals()`
in `backend/generate_data.py` called `ordered.index(uid)` — an O(n) list
scan — once per chosen background referral, making that function
O(n_chosen x n_background): quadratic in background account count. This
alone explained most of generation time growing 17x for only a 5x account
increase (10x → 50x). Fixed with a precomputed `{uid: index}` dict built
once — a pure lookup optimization with zero effect on which referrer gets
picked or the random-number-generator call sequence. Verified byte-identical
output against the entire frozen dataset (all 5 raw CSVs + all 3 ground-truth
files, byte-for-byte) before and after.

Both fixes are pure performance changes with **zero behavioral difference** —
verified against the frozen dataset's actual stored output, not just
asserted. The primary eval numbers reported everywhere else in this repo are
unaffected.

## One measurement thrown out, and why

An earlier run of this exact test reported Stage 3 (Louvain) taking 8,294
seconds (2.3 hours) at 50x — an obvious outlier against every other
measurement here. Rather than report it as-is or silently discard it, it was
investigated: re-running Louvain in isolation against the *exact same* 50x
graph, in its own clean process, took 56.7s; a subsequent full clean rerun of
the entire test (nothing else running concurrently) reproduced 33.3s,
consistent with an earlier 33.1s measurement from before the anomalous run.
Degree distribution on that graph shows no pathological hub (max degree 50,
bounded by construction) that could explain a genuine 250x algorithmic
blowup. The conclusion: the 8,294s figure was a one-off measurement artifact
(most likely OS-level resource contention from something else running on the
machine at that moment, not a property of the graph or the algorithm), and
it is not used below. This is the same discipline this project applies to
the Elliptic Stage 2 null result and the Amazon small-sample result
elsewhere: confirm an anomaly before reporting it, don't just report the
first number that comes out.

## Results (clean run, both fixes applied)

| Scale | Accounts | Graph edges | Candidate clusters | Generation | Stage 3 (Louvain) | **Total pipeline** |
|---|---|---|---|---|---|---|
| 1x | 7,500 | 9,018 | 174 | n/a (frozen) | 0.57s | **2.42s** |
| 10x | 75,000 | 89,998 | 1,700 | 29.6s | 8.41s | **26.65s** |
| 50x | 375,000 | 469,352 | 9,043 | 190.6s | 33.26s | **79.27s** |

Full per-stage breakdown:

| Stage | 1x | 10x | 50x |
|---|---|---|---|
| load_data | 1.37s | 13.34s | 32.67s |
| Stage 1 (graph build) | 0.23s | 2.29s | 6.09s |
| Stage 2 (hard clustering) | 0.01s | 0.12s | 0.35s |
| Stage 3 (Louvain) | 0.57s | 8.41s | 33.26s |
| Stage 4 (feature scoring) | 0.25s | 2.50s | 6.89s |
| Stage 5 (confounder filter) | 0.00s | 0.01s | 0.01s |
| **Total pipeline** | **2.42s** | **26.65s** | **79.27s** |

## Honest read

**The pipeline itself scales close to linearly** with account volume once the
two bugs above are fixed: ~11x pipeline time for a 10x account increase,
~3x more for the next 5x increase (10x → 50x) — sublinear-to-linear, not the
quadratic blowup either unfixed bottleneck would have produced. At 375,000
accounts (50x this project's demo scale), the full detection pipeline
completes in under 80 seconds.

**Louvain (Stage 3) is now the largest single component at scale** — 33.3s of
79.3s total at 50x (42%), up from being a minor cost at 1x. It isn't a
problem at the scale tested here, but it's the component most likely to
become the next bottleneck if pushed further (100x+), and the honest
next-step target if this were being sized for a genuinely larger deployment.

**Data generation is not the pipeline, and shouldn't be read as one.** It's a
synthetic-cohort-creation step specific to this project's evaluation
methodology, not something a real production system does (real transaction
data already exists; it isn't generated). Its 190.6s at 50x is reported for
completeness, not as evidence about production readiness.

## What a genuinely production-scale test would need

- This tests 375,000 accounts against Louvain's default resolution and this
  project's edge-weighting scheme; Razorpay's actual merchant network is
  larger, and a real deployment would need this rerun at that scale, on real
  infrastructure, not a synthetic cohort on a single machine.
- Louvain's approximately-linear-in-practice runtime is a property of this
  graph's sparsity (average degree ~2.4, unchanged across scales by
  construction); a real transaction graph's density profile could differ
  and would need its own measurement, not an extrapolation from this one.
- No memory-usage profiling was done here — only wall-clock time. At genuine
  production scale, memory footprint (the full graph plus every candidate
  cluster's subgraph) would need its own real measurement.
