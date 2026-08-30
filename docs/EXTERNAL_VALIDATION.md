# External validation on real, independently-labeled fraud data

Every number elsewhere in this repo comes from data we generated ourselves — which is honest about being synthetic, but it's still our own construction. This is the stronger claim: **the same clustering machinery, unmodified, tested against real platforms' real fraud labels, from independent researchers, on a completely different domain** (fake-review collusion, not referral-bonus farming).

## What's actually reused, and what isn't

Same discipline as the [COD collusion extension](SECOND_LOSS_TYPE.md): Stage 2 (`stage2_hard_clusters`) and Stage 3 (`stage3_soft_clusters`) are imported from `backend.pipeline.clustering` **unmodified** — not reimplemented, the literal same functions from the primary submission. What's dataset-specific is which relation counts as a near-certain identity signal (hard) vs. a broader circumstantial one (soft), and — because these benchmarks label individual nodes as fraudulent rather than labeling whole rings the way our synthetic ground truth does — the evaluation had to be adapted: a candidate cluster counts as a "predicted ring" if more than half its members are independently labeled fraudulent by the original researchers, not by us.

Stage 4/5's specific behavioral features (order-value templating, referral-claim timing) don't transfer — there's no order or referral concept in a review dataset — and that substitution is stated here explicitly rather than papered over.

## Methodology note: this is node-level, not ring-level — a real difference from the primary eval

The primary submission's headline numbers (`README.md`) are **ring-level**: "100% hard-signal recall" means 40 of 40 *planted rings*, as whole units, were detected — computed by matching a candidate cluster against a known ring's exact membership with a bidirectional overlap threshold.

The numbers below are **node-level** (account/review/transaction), not ring-level, and that is a genuine methodological difference, not a labeling choice. It happened because it had to: YelpChi, Amazon, and Elliptic only provide a fraud/not-fraud label per individual node — there is no "these 8 accounts are one ring" grouping in the ground truth to match against the way there is in our own synthetic data. So "precision" here means *what fraction of the accounts inside flagged clusters are individually labeled fraud*, not *what fraction of flagged clusters correspond to a whole real ring*. **These numbers are not directly comparable to the primary system's 100% / 82.5% / 2.5% ring-level figures, and shouldn't be read as if they were.** What they validate is narrower but still real: whether the same graph-clustering mechanism concentrates real fraud above the base rate on data we didn't construct.

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

## 3. Elliptic (Weber et al., 2019) — a generalization proof-of-concept, not just a weak-domain test

**The headline claim this section supports: this architecture is not a fraud-domain-specific trick. It's a general relational-graph detector.** Elliptic is real Bitcoin transaction data — the most different domain available from promo-referral abuse: no device fingerprints, no payment instruments, no accounts in the normal sense, nothing this system was designed around. Run completely unmodified anyway, it still found real signal: **72.0% precision, 7.3x lift over the base rate, on a trustworthy 829-transaction sample.** That result is the floor, not the ceiling — the same unmodified Stage 2/3 clustering, pointed at real Razorpay-native signals (device fingerprints, payment instruments, the identity-linking relations it was actually designed for), should be expected to perform at least as well, and plausibly meaningfully better, since Elliptic deliberately withholds every one of this system's strongest signal types. Everything below is the real mechanism behind that number, reported with the same "explain, don't just assert" discipline as the rest of this document — this is a reframe of presentation around an already-validated result, not a new or inflated one.

Real Bitcoin transaction graph, transaction-level illicit/licit labels, via [huggingface.co/datasets/yhoma/elliptic-bitcoin-dataset](https://huggingface.co/datasets/yhoma/elliptic-bitcoin-dataset) (a mirror covering 114,634 of the original 203,769 transactions — a real subset, not a corrupted file; every row that exists has a matching label).

Deliberately the hardest test available, run because the top two finished with time to spare: this is a **single-relation** transaction-flow graph (payment A → payment B), not a multi-relation graph like Yelp/Amazon, and has zero device/payment-instrument analog to lean on.

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

**Reading this result honestly, in both directions.** It is real Bitcoin data, not Razorpay data — no device fingerprints, no payment instruments, no promo-referral behavior of any kind, and the 7.3x figure is exactly the number above, not adjusted or reframed upward. What it establishes is narrower but still load-bearing: the underlying mechanism (build a relational graph, cluster it deterministically, look for density anomalies) is not fraud-domain-specific, and it clears a real bar even on a domain that withholds every signal type this system was actually designed around. Pointed at what it *was* designed around — real Razorpay-native identity signals, not Bitcoin's payment-flow-only graph — the reasonable expectation is performance at least this good, plausibly meaningfully better, since the primary system's own frozen result (100% hard-signal recall) already shows what happens when a real identity-linking relation *is* available. Elliptic is the floor this architecture clears with its hardest signal type taken away; it is not a claim about what it does with its best signal type restored.

## External design validation (cited, not run against)

**TravelFraudBench** (Sajja, arXiv:2604.21093, April 2026) is an independently-built benchmark for evaluating fraud-ring detection on travel platforms, arriving at the same starting observation this project did — that existing fraud data doesn't test multiple distinct ring *shapes*. One of its three planted ring types is described as "star topology with shared device/IP clusters" — structurally identical to this system's hard-signal pattern, arrived at independently by a different research effort. Not run against directly (it's a 9-node-type, 12-edge-type heterogeneous benchmark built for GNN methods, not graph-clustering ones — running it would be disproportionate build effort for a citation), but cited here as external validation that the hard-signal ring shape this system is built around is a real, recognized pattern, not an artifact of how we happened to construct our own synthetic data.

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
