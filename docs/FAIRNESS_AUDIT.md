# Fairness audit — false-positive rate and ring recall by geographic tier

RBI's FREE-AI framework names **Fair** as one of its four pillars. The
concrete risk this audit checks for isn't abstract: two of this system's own
confounder archetypes — `household` (shared family device) and `hostel`
(shared campus wifi subnet) — exist specifically because sharing a device or
an IP is how real families, hostel residents, and lower-income multi-person
households actually live, not fraud. If Stage 5 clears those legitimately
shared-attribute clusters *unevenly* across geography, that's a fairness
failure this system's own detection signals could cause. The aggregate 2.5%
confounder false-positive rate reported elsewhere in this repo says nothing
about whether that one miss — or a hypothetical future one — lands harder on
one group than another.

**No protected attribute (religion, caste, or similar) is used anywhere in
this audit or anywhere in this codebase.** Pincode-derived tier is a
geographic/economic proxy and nothing more.

## Which "Tier 1/2/3," and why the distinction matters

There are two genuinely different classifications both called "Tier
1/2/3" in India, and conflating them is a real, easy-to-make mistake — an
earlier draft of this audit implicitly did, describing an 8-metro list as
"the RBI's own Tier-1 classification" without checking that claim against
the actual RBI document:

- **RBI's own official 6-tier banking classification** (branch
  authorisation, 2001-census population bands): Tier-1 = population
  ≥100,000. Verified against Wikipedia's cross-referenced summary of the
  source RBI circular (the RBI PDF itself sits behind a CAPTCHA and
  couldn't be fetched directly). That's an extremely broad band — hundreds
  of Indian towns qualify — built for bank-branch licensing, not a useful
  urban-metro-vs-everything-else proxy.
- **The informal "Tier-1/2/3 city" classification** used in real estate,
  logistics, and retail — **the one this audit actually uses**: Tier-1 =
  the ~8 megacities with population >4M (2001 census). Tier-2 here is a
  real, verified list of major mid-size cities. This is the classification
  that actually distinguishes "dense urban metro" from "mid-size city" from
  "everything else," which is the real question a fairness proxy needs to
  answer — RBI's own 100K+ "Tier-1" would classify most of urban India as
  one undifferentiated bucket and defeat the purpose.

This audit uses the second definition throughout, states that choice
explicitly, and does not use the phrase "RBI Tier-1" to describe it.

## Tier classification used

**Tier-1 metro** (8 cities, population >4M, 2001 census) — real 3-digit PIN
prefixes, each verified against India Post's PIN structure (mapsofindia.com)
this session:

| City | Prefix | City | Prefix |
|---|---|---|---|
| Delhi | 110 | Hyderabad | 500 |
| Mumbai | 400 | Kolkata | 700 |
| Pune | 411 | Ahmedabad | 380 |
| Bangalore | 560 | Chennai | 600 |

**Tier-2 city** (11 major mid-size cities) — real 3-digit PIN prefixes.
Jaipur, Coimbatore, and Indore directly confirmed via web search this
session; the remaining 8 are well-established standard facts, cross-checked
for consistency against each city's own state's real India Post postal zone
(e.g. Nagpur=440 correctly sits inside Maharashtra's zone-4 range, Patna=800
inside Bihar's zone-8 range) rather than asserted from memory alone:

| City | Prefix | City | Prefix | City | Prefix |
|---|---|---|---|---|---|
| Jaipur | 302 | Coimbatore | 641 | Bhopal | 462 |
| Lucknow | 226 | Indore | 452 | Patna | 800 |
| Kochi | 682 | Nagpur | 440 | Chandigarh | 160 |
| Surat | 395 | Visakhapatnam | 530 | | |

**Tier-3 / other**: everything else. A cluster is tagged by the *highest*
tier present among its members (Tier-1 beats Tier-2 beats Tier-3 if a
cluster happens to mix) — a deliberately generous proxy, stated plainly
rather than hidden.

## Two things confirmed before trusting any result

**1. Code-level: no direct bias path exists.** Grep-verified — `home_pincode`
is never read by `graph_build.py`, `clustering.py`, `features.py`, or
`confounder_filter.py`. It cannot directly influence a graph edge, a feature
score, or a filter decision, because nothing in the detection pipeline ever
looks at it.

**2. Data-level: pincode is real but uncorrelated by construction.**
`rand_pincode()` in `generate_data.py` assigns each account an independent,
uniformly random 6-digit code — not shared within a cluster, not correlated
with confounder type, ring type, or anything else. This means the split
below is computed against real, unmanipulated values already in the frozen
dataset — not a constructed or fabricated scenario.

## Results (run against the frozen `SEED=20260828` dataset)

| Tier | Confounders (n / FP) | FP rate | Rings (n / detected) | Recall |
|---|---|---|---|---|
| Tier-1 metro | 4 / 0 | 0.0% | 8 / 6 | 75.0% |
| Tier-2 city | 7 / 0 | 0.0% | 7 / 6 | 85.7% |
| Tier-3 / other | 29 / 1 | 3.5% | 65 / 61 | 93.8% |

By confounder type (raw counts — cells this small can't support a rate):

| Type | Tier-1 (n/FP) | Tier-2 (n/FP) | Tier-3 (n/FP) |
|---|---|---|---|
| hostel | 1/0 | 2/0 | 7/0 |
| household | 0/0 | 0/0 | 13/1 |
| influencer | 1/0 | 2/0 | 4/0 |
| office | 2/0 | 3/0 | 5/0 |

Account level: of 749 accounts across all 40 confounder clusters, 5 land in
a Tier-1 metro prefix, 12 in a Tier-2 city prefix, 732 in Tier-3/other.

## Honest read

**The ring-recall column has a gap that looks real if you only read the
percentages — 75% for Tier-1 metro vs. 93.8% for Tier-3/other.** Read the
counts before the rate, exactly the discipline this project applies
everywhere else: Tier-1 metro is 6 of 8 rings detected — missing 2 out of 8
is a 25-percentage-point swing from a single additional miss, which is what
small-N does, not evidence of a real tier-linked gap. With only 40
confounders and 80 rings split three ways, and 1 real confounder false
positive across the whole frozen set, **no split of this data has enough
events to support a statistically meaningful rate comparison in any
direction** — for confounder FP or for ring recall. This is reported
exactly as it came out: not stretched into a finding it can't support, and
not smoothed over to hide a number that looks uncomfortable at first glance
either.

What this audit *does* establish:

- **No direct bias mechanism exists in the code today** — confirmed by
  inspection, not assumed.
- **The methodology is real, runs against real (unmanipulated) data, uses
  no protected attribute, and is reproducible** — re-running
  `python -m backend.fairness_audit` after any future pipeline change
  re-computes this from scratch.
- **The audit has teeth the moment the data does**: it would surface a real
  disparity immediately if either (a) confounder/ring volume were large
  enough for the rate comparisons to carry weight, or (b) `home_pincode`
  reflected real, non-random geography instead of independent random draws.

**The risk this audit exists to guard against is real and correctly named,
even though this dataset can't yet measure it.** Shared device/IP signals
genuinely correlate with hostel living and lower-income shared housing in
the real world — that correlation is exactly why `household` and `hostel`
confounders are in this system's ground truth at all. Stage 5's
organic-evidence thresholds (signup-window spread, order-value diversity,
post-signup engagement) have never been tested against a sample where a real
geography/behavior correlation is present, because no such labeled sample
exists in this synthetic generator, and — as far as this project is aware —
none exists in any public fraud-detection benchmark either.

## What a production version of this check would need

- Real (or realistically-distributed) pincode/geography data, not random
  draws — even a coarse urban-density or income-decile proxy would be enough
  to make the tier split mean something.
- Far more confounder and ring volume per tier cell for a rate comparison to
  have statistical power — at real-world scale this is achievable; at this
  project's synthetic 40-confounder/80-ring scale, it structurally isn't.
- A genuine urban/rural classification (Census of India's own statutory
  urban-area definition) layered on top of the city-tier split used here,
  for a finer-grained rural vs. semi-urban vs. urban-metro read than city
  -tier alone provides.
