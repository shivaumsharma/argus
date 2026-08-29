# Fairness audit — false-positive rate by geographic tier

RBI's FREE-AI framework names **Fair** as one of its four pillars. The concrete
risk this audit checks for isn't abstract: two of this system's own confounder
archetypes — `household` (shared family device) and `hostel` (shared campus
wifi subnet) — exist specifically because sharing a device or an IP is how
real families and hostel residents actually live, not fraud. If Stage 5 clears
those legitimately shared-attribute clusters *unevenly* across geography or
income, that's a fairness failure this system's own detection signals could
cause. The aggregate 2.5% confounder false-positive rate reported elsewhere in
this repo says nothing about whether that one miss — or a hypothetical future
one — lands harder on one group than another.

## What was checked, and how

`home_pincode` is the only field in the schema that could serve as a
geographic/socioeconomic proxy. This audit (`backend/fairness_audit.py`)
classifies every account's pincode against 8 verified Tier-1 metro postal
prefixes and checks Stage 5's behavior by tier.

**Tier-1 prefixes used** (real, verified against India Post's PIN structure —
the first 3 digits identify the sorting district, and each of these cities'
full delivery area sits inside one 3-digit prefix):

| City | Prefix | City | Prefix |
|---|---|---|---|
| Delhi | 110 | Hyderabad | 500 |
| Mumbai | 400 | Kolkata | 700 |
| Pune | 411 | Ahmedabad | 380 |
| Bangalore | 560 | Chennai | 600 |

These 8 are the commonly used "Tier-1" set by population (>4M, 2001-census
basis) — the same population-tier logic behind RBI's own regional
classifications. A cluster is tagged `tier1_metro` if **any** member's
pincode hits one of these prefixes, else `tier2_3_other` — a deliberately
generous proxy for "this cluster touches a Tier-1 metro at all," stated
plainly as a coarse heuristic rather than a precise per-member classification.

## Two things confirmed before trusting any result

**1. Code-level: no direct bias path exists.** Grep-verified — `home_pincode`
is never read by `graph_build.py`, `clustering.py`, `features.py`, or
`confounder_filter.py`. It cannot directly influence a graph edge, a feature
score, or a filter decision, because nothing in the detection pipeline ever
looks at it. Whatever this audit finds, it isn't finding *direct* disparate
treatment, because that's structurally impossible today.

**2. Data-level: pincode is real but uncorrelated by construction.**
`rand_pincode()` in `generate_data.py` assigns each account an independent,
uniformly random 6-digit code — not shared within a cluster, not correlated
with confounder type, ring type, or anything else. This means the split below
is computed against real, unmanipulated values already in the frozen dataset
(not a constructed or fabricated scenario) — but it also means the sample
available per tier bucket is small by construction: each specific 3-digit
prefix has roughly a 1-in-800 chance per account (8 first-digit choices ×
100 two-digit suffixes), so ~9-13 of the dataset's 7,500 accounts land on any
one given metro prefix purely by chance.

## Results (run against the frozen `SEED=20260828` dataset)

| Tier | Confounders | False positives | FP rate |
|---|---|---|---|
| Tier-1 metro (any member) | 4 | 0 | 0.0% |
| Tier-2/3 / other | 36 | 1 | 2.8% |

By confounder type (raw counts — cells this small can't support a rate):

| Type | Tier-1 (n / FP) | Tier-2/3 (n / FP) |
|---|---|---|
| hostel | 1 / 0 | 9 / 0 |
| household | 0 / 0 | 13 / 1 |
| influencer | 1 / 0 | 6 / 0 |
| office | 2 / 0 | 8 / 0 |

Account level: of 749 accounts across all 40 confounder clusters, only **5**
land in one of the 8 Tier-1 metro prefixes checked.

## Honest read

With 40 confounders total and exactly 1 false positive in the whole frozen
set, no split of this data — by tier or by anything else — has enough false
positives to support a statistically meaningful rate comparison in either
direction. The single real FP (a "tight" household, see
[`ARCHITECTURE.md`](ARCHITECTURE.md#known-limitations-honest)) happened to
fall in the `tier2_3_other` bucket by chance; one data point proves nothing
about disparate impact.

What this audit *does* establish:

- **No direct bias mechanism exists in the code today** — confirmed by
  inspection, not assumed.
- **The methodology is real, runs against real (unmanipulated) data, and is
  reproducible** — re-running `python -m backend.fairness_audit` after any
  future pipeline change re-computes this from scratch.
- **The audit has teeth the moment the data does**: it would surface a real
  disparity immediately if either (a) confounder volume were large enough for
  the rate comparison to carry weight, or (b) `home_pincode` reflected real,
  non-random geography instead of independent random draws.

**The risk this audit exists to guard against is real and correctly named,
even though this dataset can't yet measure it.** Shared device/IP signals
genuinely correlate with hostel living and lower-income shared housing in the
real world — that correlation is exactly why `household` and `hostel`
confounders are in this system's ground truth at all. Stage 5's
organic-evidence thresholds (signup-window spread, order-value diversity,
post-signup engagement) have never been tested against a sample where a real
geography/behavior correlation is present, because no such labeled sample
exists in this synthetic generator, and — as far as this project is aware —
none exists in any public fraud-detection benchmark either. Naming that gap
plainly is more honest than constructing a synthetic correlation to make the
audit "pass" or "fail" on demand, which would just be manufacturing the
result being tested for.

## What a production version of this check would need

- Real (or realistically-distributed) pincode/geography data, not random
  draws — even a coarse urban-density or income-decile proxy would be enough
  to make the tier split mean something.
- Enough confounder volume per tier cell for a false-positive-rate comparison
  to have statistical power — at real-world scale this is achievable; at this
  project's synthetic 40-confounder scale, it structurally isn't.
- The same check re-run on Stage 3's soft-ring recall by tier, not just
  Stage 5's confounder FP rate — this audit focused on the false-positive
  side because that's where a fairness *harm* to real, innocent users would
  land; a recall gap would be a different (accuracy, not fairness) failure
  mode, worth its own check at production scale.
