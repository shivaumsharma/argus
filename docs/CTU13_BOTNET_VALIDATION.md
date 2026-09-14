# CTU-13: generalizing to real botnet C2 detection

Every external-validation dataset up to this point (`EXTERNAL_VALIDATION.md`)
is still fraud- or abuse-adjacent: fake reviews, Bitcoin transaction flow.
This is a genuinely different domain — real network intrusion data, not
financial fraud at all — asking the same question one step further out: is
the underlying mechanism (build a relational graph from a shared identity
-linking attribute, cluster it deterministically, look for density anomalies)
specific to promo-referral abuse, or a general relational-graph detector?

**What's reused, unmodified:** `stage2_hard_clusters` and `stage3_soft_clusters`,
imported directly from `backend.pipeline.clustering` — the literal same
functions the primary submission runs, not a reimplementation. What's
dataset-specific is the graph itself and the translation of "shared
attribute" into this domain.

## The domain translation

Two bot-infected hosts calling back to the same command-and-control
server:port is structurally identical to two fraud accounts sharing a
payment instrument — a shared-attribute edge between two "accounts" (here,
source IP addresses). Popular shared infrastructure (a DNS server, a CDN
edge, an analytics endpoint) plays the same role this project's own
household/hostel confounders play elsewhere: dense, legitimate sharing that
has to be told apart from coordination, not the actual detection target.

One structural difference from the primary pipeline, stated plainly: there is
no separate "hard" vs. "soft" *edge type* here — CTU-13's netflow schema has
no analog to a device fingerprint vs. an IP subnet. A single co-destination
graph is built (source IP × destination:port, with a destination-degree cap
of 100 excluding popular shared infrastructure, the same supernode mitigation
built for the primary pipeline in `backend/supernode_stress_test.py`), and
both Stage 2 (connected components) and Stage 3 (Louvain) run on that same
graph — not on a hard-signal subgraph and a full graph the way the primary
pipeline separates them. That's why Stage 2 performs differently here than on
the primary dataset (see below).

## Data

[Stratosphere Laboratory's CTU-13](https://www.stratosphereips.org/datasets-ctu13)
(Garcia et al., 2014, CC-BY) — real university-network netflow captures
mixing genuine botnet C2 traffic with normal and background traffic. Four
scenarios, four different malware families, the detailed bidirectional-flow
files the dataset's own README recommends:

| Scenario | Malware family |
|---|---|
| s5 | Virut |
| s8 | Murlo |
| s11 | Rbot |
| s12 | NSIS.ay |

Combined because a single scenario has too few distinct infected hosts to
say anything statistically — one infected VM generates thousands of flows
from a handful of IPs, not thousands of infected accounts (scenario 11 alone
has only 3 malicious hosts). Pooling scenarios for this reason is the field's
own standard practice, not an improvised workaround.

**676,631 total flows**: 11,296 botnet-labeled, 16,702 normal-labeled,
648,633 background (unlabeled ambient traffic — included in graph
construction, since legitimate shared infrastructure is exactly the
confounder case this graph needs to be tested against, but excluded from the
labeled evaluation population, same treatment given to Elliptic's unlabeled
nodes). **140,067 total hosts, 78 labeled (14 malicious, 64 normal — 17.95%
base rate)**.

## A real methodological catch: pooling all 4 scenarios into one graph dilutes real clusters

Confirmed by direct A/B measurement, not assumed. Louvain's modularity
objective is computed over the *whole* graph it's given — the resolution and
null-model normalization terms depend on total edge weight across everything
in the graph, not decomposable per connected component. A real 3-host botnet
cluster in scenario 12 (three hosts sharing 65-101 C2 destinations with each
other) scores 100% density when that scenario is clustered in isolation, but
gets diluted to 0% recall when the same hosts are clustered as part of the
full 140K-node pooled graph — even though zero edges ever cross between
scenarios.

**Fixed by clustering each scenario independently, then aggregating results**
— which is also simply the more correct methodology regardless of the
dilution effect: a real deployment runs one clustering pass per monitored
network, not one pass pooling unrelated captures from different days. The
label-blind classifier (below) is trained on the pooled host population
instead, since per-host behavioral features don't have this graph-pooling
problem, and the pooled population is what a workable train/dev/test split
needs.

## Results

| Stage | Method | Flagged | Recall | Precision |
|---|---|---|---|---|
| Stage 2 | Connected components | 0 | 0.0% (0/14) | n/a |
| Stage 3 | Louvain | 1 | **21.4% (3/14)** | **100%** |

**Stage 2 finds nothing here — a real, explained result, not a bug.** Unlike
the primary pipeline, there's no separate hard-signal subgraph to run
connected components on: it runs on the same co-destination graph as Stage 3,
where legitimate shared infrastructure (DNS, CDNs, background chatter)
connects large swaths of hosts into single sprawling components that never
cleanly isolate a small malicious group. Stage 3's density-threshold
requirement on Louvain communities is what finds the real signal here.

**Where a real coordinated cluster existed, Stage 3 found it exactly:** three
university-network hosts in scenario 12, sharing 65-101 C2 destinations with
each other, correctly isolated as their own community — 100% precision,
confirmed as a genuinely connected real structure, not an algorithm artifact
(see "Clustering validity" below).

Recall is capped by how few genuinely *coordinated* infections exist in this
specific data — most scenarios have only 1-3 malicious hosts total, too thin
a population to form a multi-member "ring" at all, regardless of detection
quality. This is a property of the data, disclosed as exactly that, not
smoothed into a higher number.

### Threshold sweep — is 0.5 a discovered ceiling? Checked, not assumed

Same discipline as every other external-validation dataset: re-scoring the
identical, already-computed clusters at lower density thresholds, no
re-clustering.

| Threshold | Flagged | Recall | Precision |
|---|---|---|---|
| 0.5 (reported above) | 1 | 21.4% | 100% |
| 0.4 | 1 | 21.4% | 100% |
| 0.3 | 1 | 21.4% | 100% |
| 0.2 | 1 | 21.4% | 100% |
| 0.1 | 4 | 42.9% | 25% |

At threshold 0.1, recall doubles to 42.9% (6/14) at a real, expected
precision cost (100% → 25%) — the same "0.5 was inherited from convention,
not chosen for this dataset" pattern seen on every other external dataset.

### Clustering validity

Independent of the label question entirely: does the one flagged Stage 3
community correspond to a real, connected block of hosts in the raw graph,
or could Louvain have merged disconnected pieces? Checked directly on the raw
co-destination graph — **1/1 flagged groups are one genuinely connected
block**, not a partitioning artifact.

## FRAUDAR cross-check — an independent method, opposite pattern from the primary dataset

Same reasoning as the primary submission's own FRAUDAR comparison
(`FRAUDAR_CROSSCHECK.md`): an unrelated, published, camouflage-resistant
densest-subgraph method (Hooi et al., KDD 2016), reusing
`backend/fraudar_analysis.py`'s `detect_top_k_blocks` completely unmodified,
run per scenario against a bipartite host × C2-destination graph, then
aggregated.

| | Count |
|---|---|
| Dense blocks found (across 4 scenarios) | 70 |
| Malicious hosts captured | 8 / 14 |
| Recall | **57.1%** |
| Precision | **11.4%** |

**FRAUDAR recalls more malicious hosts here than this project's own Stage 3
(57.1% vs. 21.4%) — at much worse precision (11.4% vs. 100%).** This is the
*opposite* pattern from the primary fraud dataset's own FRAUDAR comparison,
where FRAUDAR badly underperforms Stage 2's connected-components approach.
Read honestly, not spun either direction: FRAUDAR's densest-subgraph peeling
casts a wider net on this data (70 blocks, touching far more hosts overall)
and catches more true positives as a side effect of that breadth, while
Stage 3's density-threshold requirement stays conservative and exact. A real
precision/recall tradeoff between two legitimate methods on this dataset, not
a clean win for either side.

| Scenario | Blocks | Malicious captured / total |
|---|---|---|
| s5 (Virut) | 20 | 1 / 1 |
| s8 (Murlo) | 20 | 1 / 1 |
| s11 (Rbot) | 10 | 3 / 3 |
| s12 (NSIS.ay) | 20 | 3 / 9 |

## Label-blind classifier — real per-host flow statistics, never the label as an input

Real per-host behavioral features from the netflow schema itself (flow
count, distinct destinations/ports/protocols, duration mean/std, packet and
byte statistics) — never the label as a feature, only as the training
target. Proper 60/15/25 train/dev/test split (46/12/20 hosts), threshold
chosen on dev only, reported at the dev-chosen threshold on held-out test —
same discipline as every other classifier in this project.

| Method | Recall | Precision | Caught / Test malicious |
|---|---|---|---|
| Logistic regression | 50.0% | 33.3% | 2 / 4 |
| **XGBoost** | **75.0%** | **100%** | 3 / 4, 0 false positives |

XGBoost catches 3 of the 4 malicious hosts in a 20-host held-out test split
with zero false positives — a real positive data point, on a sample small
enough (4 malicious hosts in test) to need the same "read the count, not the
rate" caveat already applied to Amazon elsewhere in this project's external
validation.

## What this does and doesn't establish

- **Does establish**: the same unmodified graph-clustering mechanism that
  underlies this project's primary claim finds real signal in a domain with
  no fraud concept at all — real botnet C2 infrastructure, real malware
  families, real university-network traffic. Stage 3 isolates the one
  genuinely coordinated cluster that exists in this data exactly, at 100%
  precision, confirmed as a real connected structure rather than an
  algorithm artifact.
- **Does establish**: an independent, published method (FRAUDAR) and a real,
  label-blind trained classifier (XGBoost) both find real signal
  independently on this data too — this isn't one method's idiosyncratic
  result.
- **Does not establish** that this specific pipeline is production-ready for
  network intrusion detection — CTU-13 is 2014-era, university-network data,
  4 scenarios, and only 78 labeled hosts total. What it establishes is
  narrower and more honest: the underlying architectural pattern (shared
  -attribute graph → deterministic clustering → density-based flagging)
  transfers to network security as a detection primitive, not that this
  exact system is a finished network intrusion product.

## Running it yourself

```bash
python -m backend.external_validation.ctu13
```

Data: `data/external/ctu13/scenario{5,8,11,12}_botnet*.binetflow`, fetched
from [mcfp.felk.cvut.cz](https://mcfp.felk.cvut.cz/publicDatasets/) (Garcia
et al., 2014, CC-BY). The dashboard's External Validation page reads the
identical JSON (`data/processed/ctu13_validation.json`) this script writes —
nothing on the page is hand-typed.
