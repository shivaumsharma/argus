# Architecture

## Pipeline

```mermaid
flowchart TD
    A[accounts / sessions / referrals /<br/>payment_instruments / orders] --> B["Stage 1 — Graph construction<br/>(graph_build.py)"]
    B -->|shared instrument, shared device,<br/>IP-subnet overlap, referral link| C["Stage 2 — Hard-signal clustering<br/>connected components on device/instrument edges only"]
    B -->|full weighted graph| D["Stage 3 — Soft-signal clustering<br/>Louvain community detection"]
    C --> E["Stage 4 — Cluster feature scoring<br/>(features.py) — still deterministic"]
    D --> E
    E --> F["Stage 5 — Confounder filter<br/>(confounder_filter.py) — explainable rules"]
    F -->|suppressed| G[Left alone — no further action]
    F -->|flagged| H["Stage 8 — LLM investigation layer<br/>(llm_investigate.py)"]
    H --> I["case_summary, confidence,<br/>recommended_action ∈ {HOLD_BONUS, MANUAL_REVIEW, NO_ACTION},<br/>key_evidence"]
    I --> J[SQLite: clusters + audit_log]
    J --> K[Streamlit dashboard]
    J --> L[FastAPI read-only service]
```

## Why deterministic-first, LLM last

Stages 1-5 are 100% deterministic — NetworkX graph algorithms and explicit feature thresholds, no model calls. The LLM only ever sees a cluster that has *already* survived five stages of scrutiny, and it receives nothing but the aggregate evidence those stages computed (edge signals, feature scores, the filter's own stated reason) — never raw account data. This means:

- **Every flag is traceable.** A judge, auditor, or analyst can walk from a flagged cluster back to the exact graph edges and feature values that produced it, with no black-box step in between. This is the direct answer to the RBI FREE-AI framework's explainability/auditability expectation.
- **Cost and latency are bounded.** The LLM runs once per *already-flagged* cluster (typically a few dozen calls per cohort of thousands of accounts), not once per account or per transaction.
- **The LLM cannot expand scope.** It writes up a case the deterministic pipeline already built; it cannot go looking for new rings on its own, and its output is constrained to three actions, none of which touch money or accounts directly.

## Stage-by-stage detail

**Stage 1 — Graph construction** (`backend/pipeline/graph_build.py`). Nodes are accounts. Edges come from four signal types, weighted by strength: shared `instrument_hash` (4.0) > shared `device_fingerprint_id` (3.0) > IP-subnet overlap, first three octets (2.0) > referral link (0.8–2.0, scaled up when the bonus claim happens within hours of signup). Every edge records which signal(s) produced it — the basis for the "edges labeled by shared attribute" UI requirement and for every downstream explanation.

**Stage 2 — Hard-signal clustering.** Connected components computed on a subgraph containing *only* shared-device and shared-instrument edges. Two different people legitimately sharing a payment instrument is rare; this stage exists because that signal alone is close to a ground-truth label.

**Stage 3 — Soft-signal clustering.** Louvain community detection (resolution 1.3, tuned against the dev split) over the *full* weighted graph — the only stage that can see rings connected purely by IP overlap and referral-chain timing, with no shared device or instrument at all. This is deliberately the harder case: the eval harness reports its recall separately from Stage 2's, and it is lower (88.9% vs. 100%), honestly.

**Stage 4 — Cluster feature scoring** (`features.py`). For every candidate cluster from Stage 2 or 3: size, edge density, signup-span tightness, average gap between signups, bonus-claim velocity, the fraction of members who claimed a bonus and then went silent for 3+ days ("claim-then-dormant"), order-value coefficient of variation (low = templated/near-identical amounts), and post-signup engagement (sessions occurring more than 7 days after signup — the organic-activity signal).

**Stage 5 — Confounder filter** (`confounder_filter.py`). Rule-based, not learned. A shared instrument is treated as near-certain fraud regardless of other signals (the "legitimate reason for this is rare" argument). A shared device is checked against an *organic score* (spread-out signups ≥21 days, order-value CV ≥0.28, post-signup engagement ≥1.5 sessions/member) — if organic evidence dominates, the flag is suppressed even though a hard signal fired, exactly the household-with-a-shared-tablet case. Soft-signal-only clusters (IP/referral) need either a strong organic score (≥2/3) to be actively cleared, or a strong suspicion score (≥3/4: burst timing, templating, fast claims, dormancy) to be flagged; anything in between defaults to *not* flagging, which is the conservative choice given the cost asymmetry (see below).

**Stage 8 — LLM investigation** (`llm_investigate.py`). Tries a provider chain, degrading on failure: Claude (`claude-opus-5` via `client.messages.parse` structured output) → Gemini free tier (`gemini-flash-lite-latest` via `response_json_schema`) → a deterministic template writeup, same schema, clearly labeled `llm_mode="fallback_template"`. Every provider receives only the Stage 4 evidence and the Stage 5 verdict — never raw account data. Returns `case_summary`, `confidence`, `recommended_action`, `key_evidence`.

Free-tier LLM quotas turned out to be a real engineering constraint worth documenting honestly: the first model tried, `gemini-3.6-flash`, carries a free-tier quota of only 20 requests per **day** per project (discovered empirically — the docs don't clearly state per-model daily caps), which a handful of test calls exhausted immediately. `gemini-flash-lite-latest` has its own, separate, much larger quota (~1,000/day, ~30/minute) and is what Stage 8 actually uses. The pipeline proactively spaces calls to stay under the per-minute limit and retries with the server-suggested backoff on a 429 (up to 3 attempts) before giving up on that provider for the rest of the run — a daily quota exhausting mid-run isn't something a retry can fix, so at that point it correctly degrades to the template for the remaining clusters rather than retrying forever. The system is never blocked on API access either way: with zero credentials it still produces a complete, clearly-labeled result set.

## Cost-weighted framing

A **missed ring** (false negative) means paid-out fraudulent referral bonuses — direct financial loss, recoverable only via clawback if caught later, and often not caught at all. A **wrongly-flagged legitimate cluster** (false positive) means, at most, a delayed bonus payout pending human review — because nothing here auto-executes, the real-world cost is friction and possible churn, not a wrongful punishment. That asymmetry is exactly why Stage 5's soft-signal branch defaults to *not* flagging on ambiguous evidence: an aggressive filter would trade a small, reversible cost (delay) for a larger, less reversible one (an angry legitimate customer whose bonus visibly vanished).

## Scalability

Everything above is measured at this project's demo scale (7,500 accounts).
`backend/scale_stress_test.py` reruns the exact same Stage 1-5 pipeline at
10x and 50x that account count (75,000 and 375,000 accounts) and reports the
real, measured runtime curve — not an assertion that it scales. Building it
surfaced two genuine performance bugs (an unindexed per-cluster pandas scan
in Stage 4, and an O(n²) list scan in the data generator), both root-caused
via profiling, fixed, and verified byte-identical against the frozen
dataset's stored output before and after — the primary eval numbers above
are unaffected. Clean result: **2.42s at 1x, 26.65s at 10x, 79.27s at
375,000 accounts (50x)** — close to linear scaling, not the blowup either
unfixed bottleneck would have produced. One anomalous 8,294-second
measurement was caught mid-process, investigated (re-run in isolation,
degree-distribution check for a pathological hub), confirmed as a one-off
system artifact rather than a real property of the graph, and excluded
rather than reported as-is. Full breakdown, including which pipeline stage
becomes the largest cost at scale, in [`SCALE_STRESS_TEST.md`](SCALE_STRESS_TEST.md).

## External validation

Everything above is measured on our own synthetic construction — honest about being synthetic, but still our own. `backend/external_validation/` tests the same unmodified Stage 2/3 clustering against real, independently-labeled fraud data from three external sources. These numbers are **node-level** (individual accounts), not **ring-level** like the primary system's headline numbers above — the external datasets only label individual accounts as fraud, not whole rings, so the two aren't directly comparable. Full results, methodology, and raw counts in [`docs/EXTERNAL_VALIDATION.md`](EXTERNAL_VALIDATION.md):

- **YelpChi** (Rayana & Akoglu, KDD 2015) — real fake-review collusion, 45,954 reviews: **99.2% precision, 17.0% recall, 6.8x lift** over the 14.5% base rate, on a sample large enough to trust (1,143 flagged accounts).
- **Amazon** (McAuley & Leskovec) — same task, a domain with a much weaker identity-signal analog available: recall is a real 1.1% (9 of 821 fraud accounts, a large-enough denominator), but the precision figure is not — only **4 clusters, 11 accounts total, 9 of them fraud**, too small a sample for "82%" to mean anything as a rate. Reported as raw counts, not a percentage, for exactly that reason.
- **Elliptic** (Weber et al., 2019) — a generalization proof-of-concept, not just a weak-domain test: real Bitcoin transaction graph, the most different domain available (single relation, no device/payment-instrument analog, no ring-shaped ground truth). Stage 2 correctly finds nothing, and the reason is confirmed rather than assumed — a payment edge is the same *kind* of relation as this system's own `referral_link` (soft, never hard), and the data shows ten large, low-density transaction-chain components (4,500–7,880 nodes, 0.4–32% illicit density) rather than one clean signal to exploit. Stage 3 alone still gets **72.0% precision, 13.1% recall, 7.3x lift** over a 9.8% base rate, on a trustworthy sample (829 flagged accounts) — real Bitcoin data, not Razorpay data, and 7.3x is the number as measured, not adjusted. This is the floor, not the ceiling: the same unmodified clustering, pointed at the real identity-linking signals it was actually designed for instead of Bitcoin's payment-flow-only graph, should be expected to perform at least this well. Full framing in [`EXTERNAL_VALIDATION.md`](EXTERNAL_VALIDATION.md).

Precision beats base rate on every result backed by a large-enough sample — the honest signal that the underlying clustering mechanism generalizes, not just an artifact of how our own synthetic data happens to be constructed. Amazon's small sample is reported as exactly that, not stretched into a rate it can't support.

Separately, **TravelFraudBench** (Sajja, arXiv:2604.21093, April 2026) is cited, not run against: an independently-built benchmark that reaches the same starting observation this project did — existing fraud data doesn't test multiple distinct ring *shapes* — and one of its three planted ring types is described as "star topology with shared device/IP clusters," structurally identical to this system's hard-signal pattern, arrived at independently. External validation that the pattern this system is built around is a real, recognized fraud shape, not an artifact of our own construction.

## FRAUDAR cross-check

A different kind of external validation from the section above: instead of
testing this project's own clustering against someone else's labeled data,
`backend/fraudar_analysis.py` runs someone else's published algorithm,
independent in the sense that matters most (the detection mechanism never
sees ground truth) with one honest qualification below — FRAUDAR (Hooi et
al., KDD 2016 best paper award), a
camouflage-resistant densest-subgraph method verified against a public
reference implementation before writing this, not approximated from memory
— against this project's own frozen dataset, standalone and read-only
(never imports from or modifies Stages 1-5). Built as a users-vs-attribute
-values bipartite graph using device/instrument/subnet only, deliberately no
referral timing — which scopes this check to hard-signal rings alone; soft
rings are defined by having no device/instrument signal, so they're
structurally out of reach here, not a capability gap being measured. The one
comparable number: **FRAUDAR exactly recovers 15 of the 40 planted
hard-signal rings (37.5%), against Stage 2's 100% (40/40) on the identical
40 rings from the identical underlying signals** — real cross-validation for
those 15, and a measured illustration of why: generic greedy density-peeling
correctly isolates the largest/densest rings first but dilutes smaller ones
into a residual leftover block, while connected components extract every
component whole regardless of relative density. It never cleanly flags a
single one of the 40 planted confounders either. The qualification: the rule
for how many blocks to report was first tuned using inside knowledge of this
project's own ground truth (a smaller version of the exact leakage this
project avoids everywhere else via dev/holdout splits), caught, and replaced
with a dataset-blind threshold that verifiably gives an identical result —
so the detection mechanism stayed genuinely blind throughout, but
"independent" doesn't get to stand completely unqualified. Full results,
including that story and a real stopping-rule bug found and fixed while
building it, in [`FRAUDAR_CROSSCHECK.md`](FRAUDAR_CROSSCHECK.md).

## Continuous adversarial recommendation engine

A different question from the FRAUDAR/external-validation sections above:
not "does the same data support a different method" but "does detection
keep breaking as an adversary adapts, round over round." `backend/adversarial_recommender/`
is a five-stage subsystem -- attack generation, gap characterization,
recommendation drafting, mandatory impact simulation, and a two-gate human
approval -- built around one hard rule that is never relaxed: **it
recommends, it never modifies live detection logic.** No code path in this
package writes to `backend/pipeline/*.py`, `data/raw/`, or
`data/frozen_snapshot/`; applying a validated recommendation to production
remains a separate, manual, human action. Round 1 reuses
`adversarial_stress_test.py`'s existing evasion ring unchanged; later
rounds follow the round-over-round methodology of "A multi-rounded
adversarial scenario for graph-based promo fraud detection" (Springer,
*Social Network Analysis and Mining*, Dec 2025, DOI
10.1007/s13278-025-01566-0 -- fetched and verified before citing).

Real result from testing it: round 2 found a genuine gap (`spread_out_days`,
attack value 22.96 vs. threshold 21) and drafted a bounded fix -- simulated
impact on the full 80-ring/40-confounder set was a clean **73->73 rings,
1->1 confounder FPs (zero change either way)**, and Stage 4's mandatory
"does this actually flag the attack" check caught something a less
rigorous simulator would have missed: **the fix doesn't actually flag the
attack that motivated it** -- it only stops actively clearing it as
organic, landing it in Stage 5's conservative default-no-flag middle
ground instead. Approved and re-validated on a fresh, never-used seed
anyway (identical zero-delta result), and reported exactly as that: a
real, bounded, fully-simulated recommendation that still doesn't close the
gap it was drafted for. Full design, the SNAM citation, cadence
justification, and both required limitations (this can only imagine
evasions within the attack generator's own designed family, and an
unmanaged review cadence risks becoming a rubber-stamp) in
[`ADVERSARIAL_RECOMMENDER.md`](ADVERSARIAL_RECOMMENDER.md).

## Known limitations (honest)

- **Real fraud rings are adversarial, not static.** They actively evolve to evade exactly this kind of detection. The planted rings here are necessarily more obvious than a real ring built by someone who has seen a system like this before — this is a demonstration of the *technique*, not a claim that it's evasion-proof.
- **Measured, not just asserted: a patient adversary defeats Stage 5 by design.** `backend/adversarial_stress_test.py` builds one additional ring — a pure referral chain, no shared device, no shared instrument, no shared IP subnet, claims spread 0.5–14 days after signup instead of hours, organic-variance order values (CV 0.48), and ongoing engagement (14.75 sessions/member post-signup) instead of going dormant. Injected into a disposable copy of the real dataset and run through the unmodified pipeline: **Stage 3 does cluster it** — the referral-chain topology alone is enough for Louvain to separate all 8 members into one community — but **Stage 5 does not flag it**, for exactly the reason it's designed to trust: `"spread-out timing, diverse orders, and ongoing engagement dominate — looks like an organic cluster."` An adversary patient enough to fake the confounder signals is, by construction, indistinguishable from the confounders those signals exist to protect. This isn't a bug to fix — loosening Stage 5 to catch this ring would also catch real organic referral trees, trading the false-negative for the false-positive it was built to avoid.
- **This approach is structurally blind to a ring that shares zero attributes.** Push the adversary one step further — no referral link either, fully independent "clean" burner identities — and there is no edge at all for Stage 1 to find. That case wasn't built because it's definitionally untestable: zero edges means zero candidate cluster, with nothing for any graph-clustering approach to see.
- **LLM confidence scores are self-reported, not calibrated probabilities — but there's now a real check, not just a caveat.** The primary dataset alone only ever produces 1 negative example (73 correct of 74 flagged), too thin to test calibration. `backend/confidence_calibration.py` was rebuilt to combine that base with a purpose-built supplementary batch run through `custom_scenario.py`'s real pipeline+Stage 8 path (isolated scratch space, same guarantee as every other custom-scenario run): clear rings, clear organic clusters, and a shared-device "tight household" replication matching the real archetype behind the primary dataset's one known miss. That batch reproduced the edge case for real (10 of 12 tight-household replications wrongly flagged), giving **11 negative examples across 89 scored clusters** — enough spread to see a genuine trend: 0% accuracy at 0.6–0.7 confidence, 67% at 0.8–0.9, 100% at 0.9–1.0. Confidence does track accuracy on this combined dataset. See the Metrics page for the full decile breakdown, and the caveat that the supplementary batch deliberately over-samples the known edge case for calibration purposes — it is not a claim about how often this failure mode occurs naturally.
- **The primary system is a synthetic, bounded demonstration.** It has no access to Razorpay's actual cross-merchant network data (Vulcan) or any real device-fingerprinting/IP-intelligence vendor. The external validation above tests the same clustering machinery against real, independently-labeled fraud data — which strengthens the technique claim — but that data is still review-fraud and blockchain data, not Razorpay's own domain; it is not a claim to outperform network-scale fraud infrastructure.
- **Fairness audit ran for real, but the current dataset can't yet prove or disprove disparate impact.** RBI FREE-AI names "Fair" as a pillar, and the concrete risk is real: shared device/IP is also just how families and hostel residents live, not fraud. `backend/fairness_audit.py` confirms by code inspection that `home_pincode` is never read anywhere in Stages 1-5 (no direct bias path exists), then checks both Stage 5's confounder false-positive rate *and* ring recall by a real, 3-tier city classification (Tier-1 metro / Tier-2 city / Tier-3-other — explicitly distinguished from RBI's own separate, much broader 100K+ "Tier-1" banking classification, a distinction worth stating precisely rather than conflating). Result: 0 FP in Tier-1/Tier-2 confounders vs. 1 FP in Tier-3; ring recall 75% (Tier-1, 6/8) vs. 93.8% (Tier-3, 61/65) — a gap that traces to a single additional miss on only 8 Tier-1 rings, reported plainly as what small-N produces, not evidence of a real tier-linked pattern. 1 total confounder false positive across 40 confounders is too few to support a rate split in any direction, and pincode is generated as an independent random value uncorrelated with anything else, so this audit is currently measuring real (unmanipulated) but statistically thin data — reported exactly as it came out, including the number that looks uncomfortable at first glance. The indirect real-world risk — shared-device/IP signals genuinely correlating with hostel and lower-income shared housing — is named explicitly as untested rather than papered over. Full writeup in [`FAIRNESS_AUDIT.md`](FAIRNESS_AUDIT.md).
- **Cost-calibrated threshold sensitivity finds a real, unclaimed improvement -- deliberately not applied here.** `backend/cost_threshold_sensitivity.py` sweeps Stage 5's two judgment-call thresholds by replaying the exact production filter function against real evidence, with a false-negative cost computed from real data (Rs 1,041 average fraudulent payout per missed ring) and a false-positive cost swept across 3 labeled assumption scenarios. Finding: the shared-device organic-clear threshold could move from 3 to 2 with the exact same recall (73/80 rings, unaffected across the whole 1-4 range tested) while eliminating the dataset's sole confounder false positive entirely. This is not applied to production: it was found by evaluating against the full ring/confounder set, including the holdout split this project has deliberately never tuned against anywhere else -- acting on it now would break that discipline. Reported as a testable hypothesis for the next dev-split tuning pass. Full breakdown in [`COST_THRESHOLD_SENSITIVITY.md`](COST_THRESHOLD_SENSITIVITY.md).
- **Synthetic generator parameters are being grounded in real statistics, deliberately staged rather than silently swapped in.** Household/hostel device-sharing probabilities in `backend/generate_data.py` were invented (0.5 and 0.0 respectively) rather than sourced. Real grounding: IAMAI-KANTAR's "Internet in India Report 2025" (~100,000-consumer survey) found 18% of Indian internet users go online through someone else's device (~80% of those rural); the NSO's Comprehensive Annual Modular Survey (Round 79, 2022-23) found a majority of Indian phone users share their phone with a family member. A `USE_GROUNDED_DEVICE_SHARING` flag (default `False`) now carries `GROUNDED_HOUSEHOLD_DEVICE_SHARE_PROB` (0.55) and `GROUNDED_HOSTEL_DEVICE_SHARE_PROB` (0.15, matching the hostel docstring's long-standing but never-implemented "rarely shared device" claim) — cited directly in code, wired in behind the flag, and verified to regenerate the frozen `SEED=20260828` dataset byte-for-byte identical with the flag off. Background accounts remain unaddressed on purpose: unlike household/hostel, they're generated independently with no grouping structure, so giving them realistic device-sharing needs new pairing logic, not a probability tweak — flagged here as a recommended next step rather than rushed in. Per this project's eval integrity protocol, flipping the flag on requires a full fresh freeze-and-reevaluate cycle (new seed, single run, numbers reported as-is) before any resulting number is trusted — not yet done in this session, since it would cascade into re-verifying the fairness audit, cost-threshold sensitivity, FRAUDAR cross-check, and confidence calibration numbers above, all computed against the currently-frozen dataset. Order-value generation has no settlement/fee layer at all; if one is ever added, `order_row()` now carries a cited note on the real numbers to use (credit-card MDR ~1.5-2.5%, ~2% a defensible midpoint; 18% GST on the fee, not the transaction value — both from Razorpay's own published guidance). The second-loss-type COD dataset's own grounding (organic refusal rate recalibrated to the real 20-40% COD RTO range, full re-freeze completed and re-verified) is already fully applied, not staged — see [`SECOND_LOSS_TYPE.md`](SECOND_LOSS_TYPE.md).
- **The eval misses are real, not hidden.** On the frozen-seed held-out run (`SEED=20260828`, never seen during threshold tuning): 7 of 40 soft-signal rings are missed, and all 7 are the deliberately "hard mode" variant (slower referral claims, noisier order-value templating) — correctly clustered by Stage 3 but caught by Stage 5's conservative default-no-flag branch, a genuine gap in the soft-signal thresholds, not a pipeline bug. 1 of 40 confounders is wrongly flagged, and it's the deliberately "tight" household variant — a compressed signup window that fails the ≥21-day spread-out check despite otherwise-organic order diversity and engagement. Zero misses on the "easy" variant of either category. See the Metrics page's difficulty breakdown for the live numbers.
