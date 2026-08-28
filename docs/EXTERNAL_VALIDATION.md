# External validation on real, independently-labeled fraud data

Every number elsewhere in this repo comes from data we generated ourselves — which is honest about being synthetic, but it's still our own construction. This is the stronger claim: **the same clustering machinery, unmodified, tested against real platforms' real fraud labels, from independent researchers, on a completely different domain** (fake-review collusion, not referral-bonus farming).

## What's actually reused, and what isn't

Same discipline as the [COD collusion extension](SECOND_LOSS_TYPE.md): Stage 2 (`stage2_hard_clusters`) and Stage 3 (`stage3_soft_clusters`) are imported from `backend.pipeline.clustering` **unmodified** — not reimplemented, the literal same functions from the primary submission. What's dataset-specific is which relation counts as a near-certain identity signal (hard) vs. a broader circumstantial one (soft), and — because these benchmarks label individual nodes as fraudulent rather than labeling whole rings the way our synthetic ground truth does — the evaluation had to be adapted: a candidate cluster counts as a "predicted ring" if more than half its members are independently labeled fraudulent by the original researchers, not by us.

Stage 4/5's specific behavioral features (order-value templating, referral-claim timing) don't transfer — there's no order or referral concept in a review dataset — and that substitution is stated here explicitly rather than papered over.

## 1. YelpChi (Rayana & Akoglu, KDD 2015)

45,954 Yelp reviews (Chicago restaurants/hotels), independently labeled genuine or filtered-as-fake-spam by Yelp's own detection system. Graph relations from the paper, used as Stage 1's edges directly (via [github.com/YingtongDou/CARE-GNN](https://github.com/YingtongDou/CARE-GNN)):

| Signal | Role | Weight | Why |
|---|---|---|---|
| Same reviewer (R-U-R) | **hard** | 4.0 | Same account posting multiple reviews — a strong identity signal, directly analogous to shared device/instrument |
| Same product + month (R-T-R) | soft | 1.2 | Circumstantial timing overlap |
| Same product + rating + week (R-S-R) | soft | 0.4 | Broader, denser, down-weighted |

**Result** (base rate: 14.5% of all reviews are labeled fraud):

| Metric | Value |
|---|---|
| Candidate clusters | 7,398 (7,308 hard, 90 soft) |
| Flagged (fraud density > 50%) | 492 (491 hard, 1 soft) |
| Fraud recall | **17.0%** (1,134 / 6,677 fraud reviews captured) |
| Flagged-cluster precision | **99.2%** |
| Lift over base rate | **6.8x** |

**Read honestly:** precision is almost perfect — when the pipeline flags a cluster on real data, it is almost never wrong. Recall is modest, and that's not a failure to hide: most of Yelp's labeled fake reviews are isolated one-off spam with no shared reviewer identity or product-timing pattern — structurally invisible to a graph-clustering approach, exactly the limitation already stated in [`ARCHITECTURE.md`](ARCHITECTURE.md#known-limitations-honest) before this test ever ran. 99.2% precision / 17% recall on real, independently-labeled data is direct empirical support for the whole thesis: this approach finds *coordinated* fraud with very high confidence and makes no claim about *isolated* fraud.

Soft-signal clustering added almost nothing here (1 of 492 flagged clusters) — stated plainly rather than blended into the headline number.

## 2. Amazon (McAuley & Leskovec)

11,944 users on musical-instrument reviews, same source repo.

| Signal | Role | Weight | Why |
|---|---|---|---|
| Same product reviewed (U-P-U) | **hard** | 4.0 | Weakest of the three "hard" analogs used across both datasets — see below |
| Top-5% TF-IDF text similarity (U-V-U) | soft | 1.0 | Circumstantial |
| Same rating within a week (U-S-U) | — | **excluded** | Avg degree ~597 across 11,944 nodes — a near-complete graph. Not a discriminating signal at that density, and computationally prohibitive for Louvain. The same judgment Stage 5's philosophy already makes on our own data: an overly-broad shared attribute earns suspicion, not weight. |

**Result** (base rate: 6.9%):

| Metric | Value |
|---|---|
| Candidate clusters | 351 (331 hard, 20 soft) |
| Flagged (fraud density > 50%) | 4 (all hard) |
| Fraud recall | **1.1%** (9 / 821) |
| Flagged-cluster precision | **81.8%** |
| Lift over base rate | **11.9x** |

**Read honestly, not cherry-picked:** this is a materially weaker result than YelpChi, and it's reported as such rather than averaged away. The reason is visible in the data, not mysterious: "same reviewer" (Yelp) is a strong identity signal — few legitimate reasons two accounts share it. "Same product reviewed" (Amazon, the closest available hard-signal analog) is common and only weakly suspicious on its own — popular products get reviewed by thousands of unrelated people. That weak signal produces one dominant **9,314-node giant component** (78% of the entire graph), diluting fraud density everywhere inside it and leaving almost all fraud nodes uncaptured by the >50%-density flag. Precision on the few small, genuinely concentrated clusters that do get flagged is still well above the base rate (11.9x lift), but the sample is tiny (4 clusters, 9 fraud nodes) and shouldn't be read as a strong claim either way.

**The finding that matters:** hard-signal precision is only as strong as the identity signal actually available in the domain. Yelp had one; Amazon's closest analog was much weaker; the results tracked that difference exactly, which is what an honest validation is supposed to do.

## 3. Elliptic (Weber et al., 2019)

Real Bitcoin transaction graph, transaction-level illicit/licit labels, via [huggingface.co/datasets/yhoma/elliptic-bitcoin-dataset](https://huggingface.co/datasets/yhoma/elliptic-bitcoin-dataset) (a mirror covering 114,634 of the original 203,769 transactions — a real subset, not a corrupted file; every row that exists has a matching label).

Lowest priority, run because the top two finished with time to spare — and structurally the weakest match on purpose: this is a **single-relation** transaction-flow graph (payment A → payment B), not a multi-relation graph like Yelp/Amazon. There's no natural hard-vs-soft split to build — this dataset is exactly the shape of "transaction-level, not ring/community-labeled" that makes it a weaker fit to what this system claims. What can be tested honestly: whether Stage 2 and Stage 3, imported unchanged, find anything at all on a real, single-relation financial graph.

**Result** (114,634 nodes, 133,700 edges, 46,564 labeled — 9.8% illicit base rate):

| Stage | Clusters scored | Flagged | Recall | Precision | Lift |
|---|---|---|---|---|---|
| Stage 2 — connected components (unchanged) | 29 | 0 | 0.0% | n/a | — |
| Stage 3 — Louvain (unchanged) | 261 | 21 | **13.1%** (597/4,545) | **72.0%** | **7.3x** |

**Read honestly:** Stage 2 finds nothing here, and that's the correct, expected outcome, not a failure — a Bitcoin transaction-flow graph has no "same device" / "same reviewer" style identity relation for connected components to exploit; the graph structure itself already breaks into 40 components (largest is only 6.9% of all nodes), so there's no giant-component problem, just no hard signal to find. Stage 3's Louvain community detection, the same unmodified function used everywhere else in this repo, does find real signal even here: 72% precision and 7.3x lift over base rate on a real financial crime graph, in a domain with no ring-shaped ground truth this system was designed around. That's a genuine, if modest, positive result in the weakest-fit domain tested — evidence the underlying clustering mechanism generalizes beyond "domains that look like our synthetic data," not just a repeat of the primary claim.

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

| Dataset | Domain | Fit to our claim | Base rate | Best recall | Best precision | Lift |
|---|---|---|---|---|---|---|
| YelpChi | Fake-review collusion | Strong (clean identity relation) | 14.5% | 17.0% | 99.2% | 6.8x |
| Amazon | Fake-review collusion | Moderate (weak identity relation) | 6.9% | 1.1% | 81.8% | 11.9x |
| Elliptic | Bitcoin transaction flow | Weak (single relation, no ring labels) | 9.8% | 13.1% | 72.0% | 7.3x |

Precision beats base rate by a wide margin on all three, every time — including the domain deliberately chosen to be the worst fit. Recall varies a lot, and tracks exactly what the domain's available signals predict, not chance: strong when a real identity-linking relation exists (Yelp), weak when it doesn't (Amazon), and moderate-from-clustering-alone when there's no identity relation at all (Elliptic). That's what an honest external validation is supposed to show.
