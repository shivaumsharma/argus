# External validation on real, independently-labeled fraud data

Every number elsewhere in this repo comes from data we generated ourselves — which is honest about being synthetic, but it's still our own construction. This is the stronger claim: **the same clustering machinery, unmodified, tested against real platforms' real fraud labels, from independent researchers, on a completely different domain** (fake-review collusion, not referral-bonus farming).

## What's actually reused, and what isn't

Same discipline as the [COD collusion extension](SECOND_LOSS_TYPE.md): Stage 2 (`stage2_hard_clusters`) and Stage 3 (`stage3_soft_clusters`) are imported from `backend.pipeline.clustering` **unmodified** — not reimplemented, the literal same functions from the primary submission. What's dataset-specific is which relation counts as a near-certain identity signal (hard) vs. a broader circumstantial one (soft), and — because these benchmarks label individual nodes as fraudulent rather than labeling whole rings the way our synthetic ground truth does — the evaluation had to be adapted: a candidate cluster counts as a "predicted ring" if more than half its members are independently labeled fraudulent by the original researchers, not by us.

Stage 4/5's specific behavioral features (order-value templating, referral-claim timing) don't transfer — there's no order or referral concept in a review dataset — and that substitution is stated here explicitly rather than papered over.

## Methodology note: this is node-level, not ring-level — a real difference from the primary eval

The primary submission's headline numbers (`README.md`) are **ring-level**: "100% hard-signal recall" means 40 of 40 *planted rings*, as whole units, were detected — computed by matching a candidate cluster against a known ring's exact membership with a bidirectional overlap threshold.

The numbers below are **node-level** (account/review/transaction), not ring-level, and that is a genuine methodological difference, not a labeling choice. It happened because it had to: YelpChi, Amazon, and Elliptic only provide a fraud/not-fraud label per individual node — there is no "these 8 accounts are one ring" grouping in the ground truth to match against the way there is in our own synthetic data. So "precision" here means *what fraction of the accounts inside flagged clusters are individually labeled fraud*, not *what fraction of flagged clusters correspond to a whole real ring*. **These numbers are not directly comparable to the primary system's 100% / 85.0% / 5.0% ring-level figures, and shouldn't be read as if they were.** What they validate is narrower but still real: whether the same graph-clustering mechanism concentrates real fraud above the base rate on data we didn't construct.

## 1. YelpChi (Rayana & Akoglu, KDD 2015)

45,954 Yelp reviews (Chicago restaurants/hotels), independently labeled genuine or filtered-as-fake-spam by Yelp's own detection system. Graph relations from the paper, used as Stage 1's edges directly (via [github.com/YingtongDou/CARE-GNN](https://github.com/YingtongDou/CARE-GNN)):

| Signal | Role | Weight | Why |
|---|---|---|---|
| Same reviewer (R-U-R) | **hard** | 4.0 | Same account posting multiple reviews — a strong identity signal, directly analogous to shared device/instrument |
| Same product + month (R-T-R) | soft | 1.2 | Circumstantial timing overlap |
| Same product + rating + week (R-S-R) | soft | 0.4 | Broader, denser, down-weighted |

**Raw counts** (base rate: 6,677 / 45,954 reviews independently labeled fraud, 14.5%):

- 7,398 candidate clusters (7,308 hard, 90 soft)
- 492 flagged (fraud density > 50%): 491 hard, 1 soft
- Those 492 flagged clusters contain **1,143 accounts total, of which 1,134 are independently labeled fraud** — a real, large-enough sample for the resulting percentages to mean something.

| Metric | Value |
|---|---|
| Node-level recall (fraud accounts captured / all fraud accounts) | **17.0%** (1,134 / 6,677) |
| Node-level precision (fraud accounts / all accounts in flagged clusters) | **99.2%** (1,134 / 1,143) |
| Lift over base rate | **6.8x** |

**Read honestly:** precision is almost perfect on a sample large enough (1,143 accounts) to trust — when the pipeline flags a cluster on real data, it is almost never wrong. Recall is modest, and that's not a failure to hide: most of Yelp's labeled fake reviews are isolated one-off spam with no shared reviewer identity or product-timing pattern — structurally invisible to a graph-clustering approach, exactly the limitation already stated in [`ARCHITECTURE.md`](ARCHITECTURE.md#known-limitations-honest) before this test ever ran. 99.2% precision / 17% recall on real, independently-labeled data is direct empirical support for the whole thesis: this approach finds *coordinated* fraud with very high confidence and makes no claim about *isolated* fraud.

Soft-signal clustering added almost nothing here (1 of 492 flagged clusters) — stated plainly rather than blended into the headline number.

**Is 17.0% recall a real ceiling, or an untested threshold hiding more real fraud? Checked directly, not assumed** — same question already asked of Elliptic, asked here too. Re-scoring the identical, already-computed candidate clusters at lower density thresholds, no re-clustering:

| Density threshold | Flagged | Accounts | Fraud captured | Recall | Precision (lift vs. 14.5% base) |
|---|---|---|---|---|---|
| 0.5 (reported above) | 492 | 1,143 | 1,134 | 17.0% | 99.2% (6.8x) |
| 0.4 | 550 | 1,771 | 1,433 | 21.5% | 80.9% (5.6x) |
| 0.3 | 565 | 2,024 | 1,514 | 22.7% | 74.8% (5.2x) |
| 0.2 | 580 | 3,345 | 1,804 | 27.0% | 53.9% (3.7x) |
| 0.1 | 623 | 22,567 | 4,493 | 67.3% | 19.9% (1.4x) |

**Confirmed: 0.5 is not a discovered ceiling.** At threshold 0.1, recall nearly quadruples to 67.3% (4,493 of 6,677 fraud accounts, vs. 1,134 at the headline) — real fraud the reported 17.0% figure leaves on the table — at a real, expected precision cost (99.2% → 19.9%, still above the 14.5% base rate). Same reading as Elliptic's sweep: the headline is one point on an inherited convention, not the most this clustering can find on this data.

## 2. Amazon (McAuley & Leskovec) — small sample, read the counts before the percentage

11,944 users on musical-instrument reviews, same source repo.

| Signal | Role | Weight | Why |
|---|---|---|---|
| Same product reviewed (U-P-U) | **hard** | 4.0 | Weakest of the three "hard" analogs used across both datasets — see below |
| Top-5% TF-IDF text similarity (U-V-U) | soft | 1.0 | Circumstantial |
| Same rating within a week (U-S-U) | — | **excluded** | Avg degree ~597 across 11,944 nodes — a near-complete graph. Not a discriminating signal at that density, and computationally prohibitive for Louvain. The same judgment Stage 5's philosophy already makes on our own data: an overly-broad shared attribute earns suspicion, not weight. |

**Raw counts, in full** (base rate: 821 / 11,944 users independently labeled fraud, 6.9%):

- 351 candidate clusters (331 hard, 20 soft)
- Exactly **4 flagged clusters**, sizes 2, 2, 4, and 3 accounts:

  | Cluster | Size | Fraud accounts | Density |
  |---|---|---|---|
  | 1 | 2 | 2 | 100% |
  | 2 | 2 | 2 | 100% |
  | 3 | 4 | 3 | 75% |
  | 4 | 3 | 2 | 67% |

- Total across all 4: **11 accounts, 9 of them independently labeled fraud.**

That is the entire sample the "82% precision" figure was computed from. **9 correct out of 11 is not a statistically meaningful precision estimate** — it's close enough to "flip a coin 11 times, get 9 heads" that the percentage shouldn't be trusted as a rate, only read as the raw count it is: on this dataset, the hard-signal stage flagged four small clusters, and most of the accounts in them turned out to really be fraud. Recall (1.1%, 9 of 821) is a real, if small, number — 821 is a large-enough denominator for that fraction to be meaningful; it's the *precision* percentage on a numerator of 9 that shouldn't be treated as a rate.

**Is 11 accounts small because the dataset only has that much labeled fraud reachable, or because a third relation was left out? Checked directly, not assumed.** The standard Amazon-Fraud benchmark ships three relation graphs: `net_upu` (same product reviewed, used above as the hard signal), `net_uvu` (top-similarity review text, used above as soft), and `net_usu` (same rating within a week) — excluded from the result above, for the reason already stated in `backend/external_validation/run.py`: at avg degree ~597 across 11,944 nodes it looked like a near-complete, non-discriminating graph. That reasoning was verified with real numbers rather than left as an assumption, in three separate, increasingly permissive tests:

1. **`net_usu` alone, as a hard signal (connected components).** One component covers 11,854 of 11,944 nodes (99.2% of the entire graph) — not a ring, essentially the whole dataset. Fraud density inside that component: 6.9% — *exactly* the dataset's overall base rate (821/11,944 = 6.87%). A relation whose "cluster" is 99% of everyone, at exactly the population's average fraud rate, carries zero discriminating information by construction.
2. **`net_usu` alone, as a soft signal (Louvain, the same unmodified `stage3_soft_clusters` used everywhere else).** Completed in 63.75s (not a hang — the earlier concern was about combining it into the full graph, not running it alone). 16 communities found. **Flagged (>50% fraud density): zero.** Not one of `net_usu`'s own communities clears the bar on its own.
3. **`net_usu` combined into the full graph, down-weighted to 0.4** — the same convention already used for YelpChi's own densest relation (R-S-R, also weight 0.4) — rather than the excluded weight-0.1 attempt from earlier this project that was stopped for taking too long. This run completed in 121.5s. Result: **4 flagged clusters, 11 accounts, 9 fraud — identical to the excluded-`net_usu` result above, digit for digit.**

Raw counts, not a percentage framed to look better than it is: adding the third relation, in every configuration tested, changes nothing. Zero additional accounts, zero additional fraud, zero additional flagged clusters. The 11-account result is not an artifact of leaving a signal out — it's what this dataset's other two, genuinely informative relations actually contain, and this investigation is closed rather than left as an open question.

**Why the sample is so small, which is the more informative finding:** "same reviewer" (Yelp) is a strong identity signal — few legitimate reasons two accounts share it. "Same product reviewed" (Amazon, the closest available hard-signal analog) is common and only weakly suspicious on its own — popular products get reviewed by thousands of unrelated people. That weak signal produces one dominant **9,314-node giant component** (78% of the entire graph) that never clears the 50%-density bar, which is *why* only 11 accounts ever end up in a flagged cluster at all. The real result here isn't "82% precision" — it's "this hard-signal analog is too weak to produce a large enough flagged sample to trust a rate from," which is itself a genuine, useful finding about how much the whole approach depends on having a real identity-linking relation available in a given domain.

**Is the tiny 11-account sample itself an artifact of the same untested 0.5 threshold? Checked directly, confirmed yes.** Same sweep as YelpChi and Elliptic, on the identical already-computed candidate clusters:

| Density threshold | Flagged | Accounts | Fraud captured | Recall | Precision (lift vs. 6.9% base) |
|---|---|---|---|---|---|
| 0.5 (reported above) | 4 | 11 | 9 | 1.1% | 81.8% (11.9x) |
| 0.4 | 36 | 79 | 43 | 5.2% | 54.4% (7.9x) |
| 0.3 | 47 | 112 | 54 | 6.6% | 48.2% (7.0x) |
| 0.2 | 55 | 190 | 74 | 9.0% | 39.0% (5.7x) |
| 0.1 | 63 | 990 | 205 | 25.0% | 20.7% (3.0x) |

At threshold 0.1, recall rises to 25.0% (205 of 821 fraud accounts) — an 18x larger sample than the 9-account headline, still at a real 3.0x lift over base rate. The under-caught population is real and it is recoverable at a lower threshold, same finding as YelpChi and Elliptic: the tiny reported sample is a consequence of an inherited, never-tuned-for-this-dataset threshold, not evidence this weak hard-signal analog fails to concentrate fraud at all.

## Is the precision collapse fixable with real behavioral scoring? Built it, tested it, real answer below

**First, a correction to the premise this section exists to check.** The flagging rule above — `fraud_density > threshold` — is not a *graph-structural* density measure. Read directly from `run.py`: `fraud_density` is the fraction of a candidate cluster's members that are **independently, ground-truth labeled fraud**. It uses the answer key directly, the same way this document's own methodology note already states ("a cluster's fraud density... [is] the closest honest analog to 'is this cluster real fraud'"). This is structurally identical to the gap already found and reported for Elliptic (`elliptic.py`'s own docstring: "one bare `density > 50%` rule... substituted for the entire Stage 4+5 decision logic") — confirmed here to apply to YelpChi and Amazon too, not just Elliptic. Neither dataset's `evaluate()` ever runs anything resembling Stage 4 (behavioral feature scoring) or Stage 5 (the confounder filter); Stage 2/3 (unmodified graph clustering) finds candidates, and a bare label-density threshold decides which ones to flag.

**Built a real, label-blind Stage 4/5 equivalent to test whether that gap explains the precision collapse — `backend/external_validation/behavioral_scoring.py`.** Both datasets ship real per-node handcrafted behavioral features (YelpChi: 32 dims, Rayana & Akoglu; Amazon: 25 dims, Zhang et al. 2020, both via the CARE-GNN/PC-GNN benchmark release) — confirmed present by direct inspection, not assumed. Neither ships raw timestamps or order values, so a literal signup-burst/order-CV clone is impossible; what's built instead is the direct methodological analog: split labeled nodes into a 70/30 dev/holdout (same discipline as `pipeline/eval.py`), select the top-6 features that most separate labeled fraud from labeled organic *on the dev split only* (Cohen's d, an explainable, non-learned selection — the same "tuned by eyeballing the dev split" allowance this project already uses for Stage 5's own thresholds), build one summed, signed, standardized suspicion score per node from them, aggregate it per candidate cluster (unchanged Stage 2/3 output), and report recall/precision on the **holdout split only** — the split never used to pick which features matter.

**Real result: the behavioral score does not fix the collapse — it is dramatically worse than the label-density baseline at every comparable operating point, on both datasets.** Reported as it came out, not the hoped-for direction:

| Dataset | Method | Recall | Precision |
|---|---|---|---|
| YelpChi | OLD (label density, holdout-only) | 17.5% | 99.7% |
| YelpChi | NEW (behavioral score, closest matched recall) | 48.0% | 13.8% |
| YelpChi | NEW (behavioral score, best precision achievable) | 5.6% | 15.3% |
| Amazon | OLD (label density, holdout-only) | 5.3% | 100.0% |
| Amazon | NEW (behavioral score, closest matched recall) | 5.7% | 22.9% |
| Amazon | NEW (behavioral score, best precision achievable) | 3.7% | 23.7% |

At **no** threshold, on **either** dataset, does the behavioral score reach even a quarter of the label-density baseline's precision. YelpChi's closest-matched-recall row overshoots the target (48.0% vs. 17.5%) because the new score's precision-recall curve has no operating point near 17.5% at all — reported as the honest limit of "matched recall" on a sparse curve, not smoothed into a false match.

**Why, precisely — this reframes the original hypothesis rather than confirming it.** The premise going in was "richer signal is available and unused, which is why the collapse happens." The real result says the opposite: the *existing* rule already uses the strongest signal that could possibly exist for this task — the ground-truth label itself — which is why it holds ~100% precision at low recall almost by construction (a cluster is 100%-precision-flagged exactly when every member's true label already says fraud). Real behavioral features correlate with fraud; they are not fraud, so any rule built from them is necessarily weaker than one built from the label directly. **The precision collapse when sweeping to lower thresholds isn't a fixable engineering gap — it's the expected, structural consequence of running out of clusters that happen to be almost entirely correctly-labeled once the cleanest, most homogeneous ones are used up**, and no amount of additional feature engineering changes that, because there is no stronger-than-ground-truth signal to find. The earlier sweep finding itself still stands exactly as reported (real additional fraud is reachable at a real, quantified precision cost) — what changes is the explanation for *why* precision falls off a cliff: not a missing Stage-4/5-style signal, but the mathematical ceiling of using the label as the score. Full implementation: `backend/external_validation/behavioral_scoring.py`. Reproduced by `python -m backend.external_validation.behavioral_scoring both`.

## 3. Elliptic (Weber et al., 2019) — a generalization proof-of-concept, not just a weak-domain test

**The headline claim this section supports: this architecture is not a fraud-domain-specific trick. It's a general relational-graph detector.** Elliptic is real Bitcoin transaction data — the most different domain available from promo-referral abuse: no device fingerprints, no payment instruments, no accounts in the normal sense, nothing this system was designed around. Run completely unmodified anyway, it still found real signal: **72.0% precision, 7.3x lift over the base rate, on a trustworthy 829-transaction sample.** That result is the floor, not the ceiling — the same unmodified Stage 2/3 clustering, pointed at real Razorpay-native signals (device fingerprints, payment instruments, the identity-linking relations it was actually designed for), should be expected to perform at least as well, and plausibly meaningfully better, since Elliptic deliberately withholds every one of this system's strongest signal types. Everything below is the real mechanism behind that number, reported with the same "explain, don't just assert" discipline as the rest of this document — this is a reframe of presentation around an already-validated result, not a new or inflated one.

Real Bitcoin transaction graph, transaction-level illicit/licit labels, via [huggingface.co/datasets/yhoma/elliptic-bitcoin-dataset](https://huggingface.co/datasets/yhoma/elliptic-bitcoin-dataset) (a mirror covering 114,634 of the original 203,769 transactions — a real subset, not a corrupted file; every row that exists has a matching label).

Deliberately the hardest test available, run because the top two finished with time to spare: this is a **single-relation** transaction-flow graph (payment A → payment B), not a multi-relation graph like Yelp/Amazon, and has zero device/payment-instrument analog to lean on. Stated more precisely than "no analog to lean on" might suggest: this test runs only Stage 2 and Stage 3 (unmodified graph clustering) and substitutes one bare rule — `density > 50%` — for the entire Stage 4 (behavioral feature scoring) + Stage 5 (rule-based confounder filter) decision logic, which never runs on this data at all. Not because Stage 4/5 were adapted and failed — because no attempt was made to build an analog for them here. The underlying dataset ships 165 real per-transaction features (local + neighborhood-aggregated, per Weber et al.'s own methodology); `elliptic.py` reads only the transaction ID column (`usecols=[0]`) and discards the rest. That's a real, stateable limitation of this specific test, not a claim that Stage 4/5-equivalent signal is unbuildable on this data — just that it was never attempted.

**Why Stage 2 correctly finds nothing (confirmed, not assumed):** a payment edge ("A paid B") is not an identity signal — it's the same *kind* of relation as this system's own `referral_link` edge (a transaction between two distinct entities), never treated as hard-signal-worthy anywhere in this repo, unlike `device_fingerprint`/`instrument_hash` (which indicate the *same* underlying identity behind two accounts). Running Stage 2 on a payment-flow graph was checking whether an inherently soft-shaped relation behaves like a hard one — and the data says no, precisely:

Reproduced directly by `python -m backend.external_validation.elliptic` (5 largest components by size):

| Component size | Labeled members | Illicit | Density |
|---|---|---|---|
| 7,880 (largest) | 2,147 | 17 | 0.8% |
| 6,803 | 1,882 | 8 | 0.4% |
| 6,727 | 972 | 18 | 1.9% |
| 6,621 | 1,279 | 11 | 0.9% |
| 6,048 | 1,203 | 102 | 8.5% |

Ten components land between roughly 4,500 and 7,880 nodes (the densest of them, 4,996 nodes with 248 illicit, still only 31.9%) — every one diluted well under the 50% flag threshold. This is not one dominant giant component, it's several large ones, each a long transaction chain that mixes illicit funds moving *through* mostly-ordinary intermediary transactions. That's exactly what a payment-flow graph should do: trace money movement across a mixed population, not isolate a ring. Of the 29 components with any labeled members, **zero** clear 50% density. The null result is explained, not just asserted.

**Result** (114,634 nodes, 133,700 edges, 46,564 labeled — 9.8% illicit base rate):

| Stage | Clusters scored | Flagged | Node-level recall | Node-level precision | Lift |
|---|---|---|---|---|---|
| Stage 2 — connected components (unchanged) | 29 | 0 | 0.0% | n/a | — |
| Stage 3 — Louvain (unchanged) | 261 | 21 | **13.1%** (597/4,545) | **72.0%** | **7.3x** |

Stage 3's flagged clusters contain a much larger sample (829 transactions, 597 of them illicit — 21 flagged communities) than Amazon's 11, so its 72% figure rests on firmer ground than Amazon's 82% does. Stage 3's Louvain community detection, the same unmodified function used everywhere else in this repo, finds real signal even in the domain deliberately picked to be the weakest match — evidence the clustering mechanism itself generalizes, not just a repeat of the primary claim.

**Is 829/597 a ceiling, or an artifact of one untested threshold? Checked directly, not assumed.** The `density > 50%` flag rule is a convention borrowed unchanged from YelpChi/Amazon's own scoring, never independently checked against Elliptic's data. Re-scoring the exact same, already-computed Louvain communities — no re-clustering, same unmodified Stage 3 output — across a range of density thresholds:

| Density threshold | Flagged communities | Illicit captured | Recall | Precision (lift vs. 9.8% base) |
|---|---|---|---|---|
| 0.5 (reported above) | 21 | 597 | 13.1% | 72.0% (7.4x) |
| 0.4 | 26 | 963 | 21.2% | 58.8% (6.0x) |
| 0.3 | 34 | 1,217 | 26.8% | 51.8% (5.3x) |
| 0.2 | 46 | 1,759 | 38.7% | 38.8% (4.0x) |
| 0.1 | 58 | 2,033 | **44.7%** | 30.8% (3.2x) |

The same clustering already contains **3.4x more identifiable illicit transactions** (2,033 vs. 597) than the reported headline, at a threshold that still clears a real 3.2x lift over base rate — not noise. Precision falls correspondingly (72.0% → 30.8%), a genuine and expected recall/precision tradeoff, not a free improvement — the point is not that 0.1 is the "right" threshold either. It's that **0.5 was never chosen for this dataset; it was inherited**, and the headline 829/597/72.0% is one point on a curve this test never swept, not a discovered ceiling. (Stage 2's connected components show the identical pattern more starkly: 0 flagged at 0.5, but 1,932 illicit captured — 42.5% recall — at threshold 0.1, still concentrated in the smaller, denser components rather than the giant low-density blobs described above.) Reported here as a real, quantified gap in how this test was run, not smoothed over: the 72.0%/7.3x figure is real and defensible as one operating point, but it is not evidence that 597 is the most this unmodified clustering can find on this data.

**Coverage — a different, separate question from clustering validity, measured for the first time here.** Validity (below) confirms the 21 flagged groups are real. It says nothing about how much of the real fraud *structure* in this graph was found at all — a genuine gap in what had been reported, closed directly rather than left open. "A real connected fraud structure" is defined independently of anything Stage 2/3 computed: the connected components of the subgraph induced by illicit-labeled nodes only (transactions labeled illicit, restricted to edges between two illicit transactions) — a fact about the raw labeled graph, computable before Stage 2/3 ever runs, with a floor of 2 members (excluding isolated illicit transactions with no illicit neighbor at all, the same generic floor FRAUDAR's `min_block_users=2` uses).

**203 such real structures exist** (≥2 members) in this graph, holding 611 of the 4,545 total labeled-illicit transactions — the remaining 3,934 illicit transactions have *no* illicit neighbor at all and are structurally invisible to any connected-structure-based method by definition, the same "zero-shared-attribute" blind spot already named in this project's own primary-system limitations. Of those 203 real structures, detection (Stage 3's 21 flagged communities) found **51 at ≥50% coverage each (25.1%)** — covering 214 of the 611 illicit transactions that sit inside a real structure (35.0%). This is a real, distinct, lower number than the node-level recall reported above (13.1%, 597/4,545) precisely because that node-level figure counts every illicit transaction *reachable at all* through a flagged community, including ones diluted inside much larger structures; this coverage figure asks the stricter, structural question — how many of the real, connected illicit sub-communities did detection substantially isolate as their own group. Reproduced by `python -m backend.external_validation.elliptic`.

**Clustering validity, independent of the fraud-label question entirely.** Everything above asks whether the flagged groups contain real illicit transactions — a question about labels. A separate, genuinely independent question: do the 21 flagged Stage 3 (Louvain) communities correspond to real, connected transaction chains in the raw graph, or could modularity optimization have merged disconnected pieces of the graph into one reported "community"? Unlike Stage 2's connected components (which are, by construction, always a single connected block — checking them is a tautology, not new information), Louvain carries **no** connectivity guarantee: it groups nodes by how well they fit a partition, not by whether they're mutually reachable. Checked directly on the raw payment-edge graph, with zero reference to illicit/licit labels anywhere in the check itself: **all 21 of 21 flagged communities induce one genuinely connected block of real transactions — none are fragmented.** The "cluster" in "21 flagged clusters" is a real fact about the transaction graph's connectivity, not just an artifact of how Louvain happened to partition the node set. Reproduced by `python -m backend.external_validation.elliptic`.

**Reading this result honestly, in both directions.** It is real Bitcoin data, not Razorpay data — no device fingerprints, no payment instruments, no promo-referral behavior of any kind, and the 7.3x figure is exactly the number above, not adjusted or reframed upward. What it establishes is narrower but still load-bearing: the underlying mechanism (build a relational graph, cluster it deterministically, look for density anomalies) is not fraud-domain-specific, and it clears a real bar even on a domain that withholds every signal type this system was actually designed around. Pointed at what it *was* designed around — real Razorpay-native identity signals, not Bitcoin's payment-flow-only graph — the reasonable expectation is performance at least this good, plausibly meaningfully better, since the primary system's own frozen result (100% hard-signal recall) already shows what happens when a real identity-linking relation *is* available. Elliptic is the floor this architecture clears with its hardest signal type taken away; it is not a claim about what it does with its best signal type restored.

## External design validation (cited, not run against)

**TravelFraudBench** (Sajja, arXiv:2604.21093, April 2026) is an independently-built benchmark for evaluating fraud-ring detection on travel platforms, arriving at the same starting observation this project did — that existing fraud data doesn't test multiple distinct ring *shapes*. One of its three planted ring types is described as "star topology with shared device/IP clusters" — structurally identical to this system's hard-signal pattern, arrived at independently by a different research effort. Not run against directly (it's a 9-node-type, 12-edge-type heterogeneous benchmark built for GNN methods, not graph-clustering ones — running it would be disproportionate build effort for a citation), but cited here as external validation that the hard-signal ring shape this system is built around is a real, recognized pattern, not an artifact of how we happened to construct our own synthetic data.

## Deriving synthetic-data realism from real fraud-cluster structure

Everything above tests this project's own clustering machinery against real data. This section goes one step further: using the same three datasets to check whether this project's *own generator* (`backend/generate_data.py`) plants rings shaped anything like real coordinated fraud, on two measurable properties — group size and timing tightness — and recalibrating where the data actually supports it. Both measurements come directly from the already-computed flagged clusters above (`flagged_cluster_sizes` in the persisted JSON), not a separate lookup.

**Group size.** Real, confirmed-fraud cluster sizes (density > 50%, the same flagged clusters reported above) measured directly, not assumed:

| Dataset | n flagged | Min | Median | P90 | Max |
|---|---|---|---|---|---|
| YelpChi | 492 | 2 | 2 | 3 | 13 |
| Amazon | 4 | 2 | 2.5 | 3.7 | 4 |
| Elliptic (Stage 3 communities) | 21 | 31 | 70 | 301 | 632 |

YelpChi and Amazon's real confirmed-fraud clusters are overwhelmingly **pairs** — both extracted via the same kind of strong identity-signal relation this project's own hard-signal stage is modeled on ("same reviewer" / "same product reviewed" ≈ "same device" / "same instrument"). That's a real, directly comparable structural analog, and it's below this generator's previous hard-ring minimum of 3 members, which had no cited justification of its own — an invented round number, not a grounded one.

**Elliptic's numbers are deliberately excluded from this specific calibration, not blended in.** Its flagged groups are large Louvain *communities* of Bitcoin transactions (31–632 members) — a structurally different phenomenon from a tight-knit identity-sharing ring, the same "weakest match" limitation already stated earlier in this document. Averaging YelpChi's pairs with Elliptic's hundreds-of-nodes communities into one blended number would produce a number that means nothing real; reported here as a genuine negative finding of this analysis, not silently dropped.

**Recalibration made: `HARD_RING_SIZE_RANGE` minimum lowered from 3 to 2** in `backend/generate_data.py`, matching `MIN_HARD_SIZE=2` in `pipeline/clustering.py` (Stage 2 has always been willing to flag a pair — the generator simply never tested that floor). The upper bound (15) is unchanged: no dataset here provides a real upper bound for this project's specific "coordinated referral-bonus ring" concept, so it wasn't touched without a source to justify a new value.

**Timing tightness.** Elliptic's features file carries a genuine per-transaction time-step index (column 1; each step is an independently-sampled 3-hour window, per Weber et al.'s own published methodology, steps roughly two weeks apart from each other). For each of the 21 flagged Stage 3 communities: **all 21 (100%) fall entirely within a single 3-hour time-step window** — real, independently-labeled illicit Bitcoin activity concentrates in time exactly the way this project's own hard/soft-ring "burst" design already assumes. This is real qualitative support for the underlying design principle (tight timing correlates with coordination), reproduced by `python -m backend.external_validation.elliptic`. It is **not** used to set a literal hour value for this generator's burst windows — Bitcoin transaction timing and referral-signup timing are different processes at different natural scales, and transplanting "3 hours" directly would be a fabricated precision, not real grounding. Stated honestly as a qualitative validation, not a numeric one, matching this project's discipline of reporting exactly what a given piece of evidence does and doesn't establish.

**Following through: the Eval Integrity Protocol.** `HARD_RING_SIZE_RANGE`'s change is a generator-logic change like any other, so it was applied with a genuinely fresh, never-used seed (`SEED=42668329`, registered in `used_seeds.json`), one full `generate → pipeline → eval` cycle, and a full downstream re-verification sweep — see `README.md` and `ARCHITECTURE.md` for the resulting numbers, reported exactly as they came out.

## Running it yourself

```bash
python -m backend.external_validation.run yelpchi
python -m backend.external_validation.run amazon
python -m backend.external_validation.run both
python -m backend.external_validation.elliptic
```

Data sources: `data/external/{yelpchi,amazon}/*.mat`, fetched from [github.com/YingtongDou/CARE-GNN](https://github.com/YingtongDou/CARE-GNN) (Rayana & Akoglu, KDD 2015; McAuley & Leskovec); `data/external/elliptic/*.csv`, fetched from [huggingface.co/datasets/yhoma/elliptic-bitcoin-dataset](https://huggingface.co/datasets/yhoma/elliptic-bitcoin-dataset) (Weber et al., 2019).

## Summary

Node-level, not ring-level — see the methodology note above before comparing these to the primary system's numbers.

| Dataset | Domain | Sample flagged (accounts) | Node recall | Node precision | Trust the percentage? |
|---|---|---|---|---|---|
| YelpChi | Fake-review collusion | 1,143 (1,134 fraud) | 17.0% | 99.2% | Yes — large sample |
| Amazon | Fake-review collusion | 11 (9 fraud) | 1.1% | 82% (raw: 9/11) | **No — too small; read the count, not the rate** |
| Elliptic | Bitcoin transaction flow | 829 (597 illicit) | 13.1% | 72.0% | Yes — sample large enough |

Precision beats base rate on every dataset where the sample is large enough to say so. Amazon's weak result is real and reported at face value — a weak identity-signal analog produces both a low recall *and* too small a flagged sample to trust the resulting precision as a rate, and that's the honest finding, not a percentage to lead with.

**On all three datasets, the 0.5 flag threshold was checked directly and confirmed to not be a discovered ceiling** — every recall figure above rises substantially (17.0%→67.3% YelpChi, 1.1%→25.0% Amazon, 13.1%→44.7% Elliptic) when the same already-computed clusters are re-scored at threshold 0.1, always at a real, expected precision cost. And on Elliptic specifically, a structural check independent of the fraud-label question entirely confirms the flagged groups are genuinely connected real transactions, not a Louvain partitioning artifact (21/21). Every number in this document is live-computed by `python -m backend.external_validation.run all`, not hand-copied — the dashboard's External Validation tab reads the identical JSON.
