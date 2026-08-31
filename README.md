# Promo/Referral Abuse-Ring Sentinel

**Razorpay AI Buildathon 2026 — Track 02 (AI Risk Manager)**

**[Read the visual explainer](docs/explainer.html)** — the argument, the pipeline, and the honest numbers in five minutes, before diving into the dashboard below.

## The actual technical argument

Fraud detection almost always means scoring one row at a time: is *this* transaction fraudulent, is *this* account risky. That architecture is mathematically incapable of catching a promo/referral abuse ring, no matter how good the model is — because a farmed account, viewed alone, is designed to look ordinary. Real-looking phone number, plausible order, no red flag. **The signal only exists across multiple rows at once**: the same device behind thirteen "different" signups, the same payment instrument reused across accounts, a referral chain that pays out in hours instead of the weeks an organic referral takes.

So this isn't a classifier. It's a graph problem:

1. **Build the entity graph** — accounts as nodes, edges wherever two accounts share a device, a payment instrument, an IP subnet, or a referral link, weighted by how strong that signal is.
2. **Cluster it deterministically** — hard-signal connected components first (near-certain: two people sharing a payment instrument is rare and legitimate), then weighted community detection (Louvain) over the full graph to catch rings that share nothing but IP overlap and referral timing.
3. **Score every candidate cluster** on real behavioral features — signup burst tightness, order-value templating, claim-then-dormant pattern, post-signup engagement.
4. **Filter out confounders** — real households, hostels, office networks, and organic referral trees are *also* dense clusters that share attributes. An explicit, explainable rule stage actively looks for the evidence that a cluster is legitimate (spread-out activity, diverse order values, ongoing engagement) and suppresses the flag.
5. **Only then does an LLM see it** — and only to write up a plain-English case for a human analyst. It never decides whether a cluster is suspicious; that's already been decided by four deterministic stages before it gets there. Every LLM recommendation is bounded to `HOLD_BONUS` / `MANUAL_REVIEW` / `NO_ACTION`. **There is no code path anywhere in this system that bans, blocks, or moves money.** A human always executes the final action.

This is also, not incidentally, what the RBI's FREE-AI framework (Aug 2025) asks for: AI used in fraud detection should be explainable and auditable by design. Every flag here traces back to a specific graph edge and a specific feature score — not a black-box judgment call.

## Results (frozen, single-pass, fresh-seed holdout)

Synthetic cohort: **7,500 accounts** — 40 hard-signal rings, 40 soft-signal rings, and 40 planted legitimate confounders (120 planted cases, ~1,536 labeled accounts), plus ~5,964 unconnected background accounts as noise. Generated with `SEED=20260828`, never seen while Stage 5's thresholds or Stage 3's Louvain resolution were being set — `generate -> pipeline -> eval` was run exactly once and these numbers are reported as-is, not iterated on.

| Metric | Value |
|---|---|
| Hard-signal ring recall | **100%** (40/40) |
| Soft-signal ring recall | **82.5%** (33/40) — the real test of the approach |
| Confounder false-positive rate | **2.5%** (1/40) |
| Cluster-level precision | **98.6%** |

Every miss is individually traceable, not a bug: all 7 missed soft rings are the deliberately "hard mode" variant (slower referral claims, noisier order-value templating); the 1 wrongly-flagged confounder is a "tight" household (a compressed, borderline-organic signup window). Zero misses on the easy cases of either category — see [`data/processed/eval_report.json`](data/processed/eval_report.json) and [Known Limitations](docs/ARCHITECTURE.md#known-limitations-honest) below.

This exact dataset is also frozen at `data/frozen_snapshot/` as the reset point for the dashboard's live-injection demo (see below) — injecting a ring during a demo mutates the live data on purpose; resetting restores precisely this run.

**Tested on real, independently-labeled fraud data too, not just our own construction — node-level, not ring-level, and reported with raw counts, not just rates.** The unmodified Stage 2/3 clustering, run against YelpChi (99.2% precision, 6.8x lift over base rate on real fake-review collusion, 1,143 flagged accounts — large enough to trust) and Elliptic (72.0% precision, **7.3x lift** on a real Bitcoin transaction graph, 829 flagged accounts — deliberately the hardest test available, zero device/payment-instrument analog to lean on, read as a generalization proof-of-concept: the floor, not the ceiling, for what the same architecture should do on Razorpay-native signals). Amazon's result doesn't make that list: only 4 clusters / 11 accounts total were ever flagged, so its 82%-looking figure is reported as the raw count it is (9 of 11 correct) rather than a rate — too small a sample to trust either way; its unused third relation type was tested 3 ways and confirmed to add nothing. Full methodology, raw counts, and the node-vs-ring-level distinction in [`docs/EXTERNAL_VALIDATION.md`](docs/EXTERNAL_VALIDATION.md).

**Fairness audit against RBI FREE-AI's "Fair" pillar**: shared device/IP is also just how families and hostel residents live, not fraud — so does Stage 5's confounder false-positive rate, and separately ring recall, skew by geography? Code-level check confirms `home_pincode` is never read anywhere in Stages 1-5 (no direct bias path); tagging the 40 confounders and 80 rings by a real, 3-tier city classification (Tier-1 metro / Tier-2 city / Tier-3-other, using verified real PIN prefixes — explicitly *not* RBI's own, much broader 100K+ banking definition, a distinction worth getting right rather than conflating) finds 0 FP in Tier-1/Tier-2 vs. 1 FP in Tier-3 confounders, and a ring-recall spread (75% Tier-1 vs. 93.8% Tier-3) that traces to a single miss on only 8 Tier-1 rings — honestly reported as **too small a sample to mean anything either way**, not smoothed over just because the raw numbers look uncomfortable at a glance. Full methodology, the RBI-classification clarification, and the "what production would need" gap in [`docs/FAIRNESS_AUDIT.md`](docs/FAIRNESS_AUDIT.md).

**Synthetic-generator parameters grounded in real Indian statistics, not invented**: household/hostel device-sharing probabilities were arbitrary (0.5 and 0.0); real grounding — 18% of Indian internet users share a device (IAMAI-KANTAR, 2025), and a majority of Indian phone users share their phone with a family member (NSO CAMS, 2022-23) — now sits behind an opt-in `USE_GROUNDED_DEVICE_SHARING` flag in `backend/generate_data.py`, cited in code, verified to reproduce the frozen dataset byte-for-byte with the flag off. The second-loss-type COD dataset's organic refusal rate was fully recalibrated to India's real 20-40% COD RTO range and re-frozen on a fresh seed (see [`docs/SECOND_LOSS_TYPE.md`](docs/SECOND_LOSS_TYPE.md)). Full reasoning, what's staged vs. applied, and why in [Known Limitations](docs/ARCHITECTURE.md#known-limitations-honest).

**Cost-calibrated threshold sensitivity**: Stage 5's two judgment-call thresholds are swept 1-4 by replaying the exact production filter function against real evidence — with a false-negative cost computed from real data (Rs 1,041 average fraudulent payout per missed ring, from `data/raw/referrals.csv`) and a false-positive cost swept across 3 labeled assumption scenarios (support review time, plus a churn-risk estimate grounded in real order values). Real finding: the device-branch threshold has a strict, same-recall, fewer-false-positive improvement available (3→2) that the frozen defaults leave on the table — reported as a testable hypothesis for the next dev-split tuning pass, not applied here, to preserve the held-out discipline used everywhere else in this project. Full breakdown in [`docs/COST_THRESHOLD_SENSITIVITY.md`](docs/COST_THRESHOLD_SENSITIVITY.md).

**Scale stress test**: the exact same pipeline rerun at 10x and 50x this dataset's account count (75,000 and 375,000 accounts), measured, not asserted. Building it surfaced two real performance bugs — an unindexed per-cluster pandas scan in Stage 4 and an O(n²) list scan in the generator — both root-caused, fixed, and verified byte-identical against the frozen dataset's output before and after. Clean result: **under 80 seconds end to end at 375,000 accounts**, scaling close to linearly with volume. One anomalous 8,294-second measurement was caught, investigated, and confirmed as a one-off system artifact rather than reported as-is. Full writeup in [`docs/SCALE_STRESS_TEST.md`](docs/SCALE_STRESS_TEST.md).

**FRAUDAR cross-check**: an independent, published, camouflage-resistant densest-subgraph method (Hooi et al., KDD 2016 best paper) run standalone against the same frozen dataset's device/instrument/subnet attributes only — no referral timing, no order data, which means this specific check is scoped to hard-signal rings only (soft rings are defined by having no device/instrument signal at all, so they're structurally out of scope here). Algorithm verified against a public reference implementation, not approximated from memory. The one comparable number: **FRAUDAR recovers 15 of the 40 planted hard-signal rings exactly (37.5%), against Stage 2's 100% (40/40) on the identical 40 rings from the identical underlying signals** — real cross-validation for those 15 from a detection mechanism that never sees ground truth, and a concrete, measured illustration of why connected components (extracted whole regardless of relative density) outperforms generic density-peeling (which dilutes smaller rings into a larger residual block) for this specific problem. It also never cleanly flags a single one of the 40 planted confounders. "Independent" carries one honest asterisk though — building this surfaced a case where the stopping rule for how many blocks to report was first tuned using inside knowledge of our own ground truth, caught, and fixed to a dataset-blind threshold (verified to give an identical result). Full writeup, including that story and a real bug found and fixed along the way, in [`docs/FRAUDAR_CROSSCHECK.md`](docs/FRAUDAR_CROSSCHECK.md).

**Time-drift simulation**: every other eval is a single point in time — this asks whether static detection decays as fraud tactics evolve across 4 sequential periods, with Stage 1-5 held completely frozen throughout (no retraining, no fix applied mid-simulation). Two ring populations escalate adaptively (only if still being caught) from naive toward the already-proven evasive archetype. Real result: the no-shared-device population collapses 100%→0% recall in one step between periods 1-2 (a genuine hard-threshold cliff in the underlying logic, not smoothed into a slope); the shared-device population holds at 100% through period 3 before dropping to 25% at period 4. Confounder false positives stayed flat at 2.5% throughout — no new collateral damage from evolving tactics. The first attempt at this test had a real construction bug (reused the wrong generator, which structurally could never be caught, giving 0% recall with nowhere to decay from) — found, fixed, and re-verified rather than left standing. Full writeup in [`docs/TIME_DRIFT_SIMULATION.md`](docs/TIME_DRIFT_SIMULATION.md).

**Infrastructure failure resilience test**: does the system hold up under realistic mid-run failures, not just detection accuracy? Two scenarios run for real against the actual production code: (a) a slow/rate-limited/timing-out LLM call during Stage 8 — the existing retry-with-backoff, degrade-to-next-provider, and template-fallback paths all worked exactly as designed, no code change needed. (b) malformed records (wrong type, missing field, out-of-range value) spliced into the *middle* of a batch — this found two real bugs: a hard crash on one malformed timestamp/order-value anywhere in 16,000+ rows, and silent data loss (a missing/negative order value or missing user_id passing through unlogged). Both fixed in `backend/pipeline/data_io.py` and re-verified: 5/5 injected corruptions now dropped and logged with zero crash, and — critically — **zero rows dropped and identical headline numbers** on the real frozen dataset, confirming no regression. Full writeup in [`docs/INFRASTRUCTURE_RESILIENCE_TEST.md`](docs/INFRASTRUCTURE_RESILIENCE_TEST.md).

**Concurrent multi-ring attack stress test**: every other adversarial test injects one evasive ring at a time — this one injects 8 at once (4 masking hard signals via the existing, unchanged evasion logic; 4 masking soft signals via a new shared-device organic-mimicking archetype), to check for an interference/overload failure mode a single-ring test structurally can't see. Raw result: 1/8 rings caught (0/4 and 1/4 by strategy, never blended). The interference check needed a proper zero-attack baseline control to avoid misattributing the dataset's one already-known false positive to "interference" — with that control in place, **zero new confounder false positives** from adding 8 simultaneous attacks. Full methodology and the baseline-control story in [`docs/CONCURRENT_ATTACK_STRESS_TEST.md`](docs/CONCURRENT_ATTACK_STRESS_TEST.md).

**Continuous adversarial recommendation engine**: a five-stage subsystem — attack generation, gap characterization, recommendation drafting, mandatory impact simulation, two-gate human approval — that probes the frozen pipeline round over round, following the methodology of a real, verified paper ("A multi-rounded adversarial scenario for graph-based promo fraud detection," SNAM, Dec 2025, DOI 10.1007/s13278-025-01566-0). One hard rule, never relaxed: **it recommends, it never modifies live detection logic.** Real result: round 2 found a genuine gap and drafted a bounded fix with a clean **73→73 rings, 1→1 confounder FPs (zero change)** simulated impact — and the mandatory Stage 4 check caught something easy to miss: **the fix doesn't actually flag the attack that motivated it**, landing it in Stage 5's conservative middle ground instead of a true flag. Approved and re-validated on a fresh, never-used seed anyway, reported exactly as what it is. Resolved, not left open: the audit trail was checked directly (all 4 lifecycle events present; real status is `validated_approved`, not rejected), the root cause was computed (the attack's `suspicion_score=0` by design, and Stage 5's organic-clear/suspicion-flag branches are structurally disjoint), and a genuinely different fix targeting the suspicion side was drafted, simulated, and still didn't close the gap — an exhaustive sweep of all ten tunable parameters confirms none ever could. Full design, the resolution, and all required limitations in [`docs/ADVERSARIAL_RECOMMENDER.md`](docs/ADVERSARIAL_RECOMMENDER.md).

## Quickstart

```bash
python -m venv venv
venv\Scripts\pip install -r requirements.txt          # Windows
# source venv/bin/activate && pip install -r requirements.txt   # macOS/Linux

python -m backend.generate_data                        # Day 1 — synthetic accounts + planted rings/confounders
python -m backend.pipeline.run_pipeline                 # Stages 1-5 — graph, clustering, scoring, filter
python -m backend.pipeline.eval                          # precision/recall vs. ground truth
python -m backend.llm_investigate                        # Stage 8 — LLM case writeups (set ANTHROPIC_API_KEY or GEMINI_API_KEY for live mode)
python -m backend.confidence_calibration                 # does self-reported LLM confidence track ground truth?
python -m backend.fairness_audit                          # does the confounder false-positive rate skew by geographic tier?
python -m backend.cost_threshold_sensitivity               # real ₹ FN cost + assumption-labeled FP cost -> does the "right" threshold shift?
python -m backend.scale_stress_test                        # reruns the pipeline at 10x/50x account count, reports real runtime
python -m backend.fraudar_analysis                         # independent FRAUDAR densest-subgraph cross-check (standalone, read-only)
python -m backend.adversarial_recommender.run --force        # one round: generate attack, characterize gap, draft + simulate a recommendation
python -m backend.compliance_report                      # auto-generates docs/COMPLIANCE_SUMMARY.md from the live audit_log
python -m backend.demo_failure_injection                 # proves the pipeline survives missing device/IP/instrument data
python -m backend.adversarial_stress_test                 # finds where detection actually breaks (see Known Limitations)
python -m backend.concurrent_attack_stress_test            # 8 simultaneous evasive rings + a baseline-controlled interference check
python -m backend.infra_resilience_test                     # LLM-call resilience + malformed-record handling, both tested for real
python -m backend.time_drift_simulation                     # does detection decay across 4 sequential periods of evolving fraud tactics?
python -m backend.snapshot                                  # freezes data/raw + the DB as the live-injection demo's reset point
python -m backend.live_injection hard 9                      # CLI version of the dashboard's live-injection control

python -m backend.external_validation.run both              # same Stage 2/3 clustering vs. real YelpChi + Amazon fraud labels
python -m backend.external_validation.elliptic                # same clustering vs. a real Bitcoin transaction graph

streamlit run frontend/streamlit_app.py                    # dashboard, including the live-injection demo page
uvicorn backend.api:app --reload                          # optional: read-only REST API over the same store
```

Stage 8 tries providers in order and degrades gracefully: **Claude** (`ANTHROPIC_API_KEY`) → **Gemini free tier** (`GEMINI_API_KEY` or `GOOGLE_API_KEY`, no billing required — get one at [aistudio.google.com/apikey](https://aistudio.google.com/apikey)) → a clearly-labeled deterministic template writeup. With no credentials at all, the pipeline still runs end to end on the template. Model choice matters here: the newest `gemini-3.6-flash` turned out to carry a free-tier quota of only 20 requests/**day** (not minute) per project — it's a brand-new model, presumably still ramping up its free allocation — so Stage 8 uses `gemini-flash-lite-latest` instead, whose free tier is roughly 1,000 requests/day and ~30/minute, comfortably enough for a full investigation run.

## Project layout

```
backend/
  generate_data.py         Day 1 — synthetic dataset + planted rings/confounders, ground truth never exposed to the detector
  pipeline/
    graph_build.py          Stage 1 — weighted entity graph
    clustering.py            Stage 2 (hard connected components) + Stage 3 (Louvain)
    features.py               Stage 4 — deterministic cluster feature scoring
    confounder_filter.py      Stage 5 — explainable rule-based filter
    run_pipeline.py            orchestrates Stages 1-5
    eval.py                     Day 4 — held-out precision/recall/FP-rate harness
  llm_investigate.py         Day 5 — bounded LLM case-writeup layer (+ template fallback)
  graph_viz.py                interactive pyvis subgraph rendering
  db.py                        SQLite store: clusters + audit_log
  reporting.py                  cross-cutting queries joining ground truth with detector output
  api.py                         FastAPI read-only service over the same store
  demo_failure_injection.py       Day 7 — proves graceful handling of missing device/IP/instrument fields
  adversarial_stress_test.py       finds where detection actually breaks: a ring that fakes every organic tell
  live_injection.py                 drops a brand-new ring into the live dataset and detects it in real time
  snapshot.py                        freeze/reset the live dataset around live-injection demos
  confidence_calibration.py           buckets real LLM confidence into deciles and checks it against ground truth
  fairness_audit.py                    checks confounder false-positive rate by geographic tier (RBI FREE-AI "Fair")
  cost_threshold_sensitivity.py         real-₹ cost sweep of Stage 5's two judgment-call thresholds
  scale_stress_test.py                   reruns Stages 1-5 at 10x/50x account count, measures real runtime
  fraudar_analysis.py                     independent FRAUDAR densest-subgraph cross-check (standalone, Stages 1-5 untouched)
  compliance_report.py                 auto-generates docs/COMPLIANCE_SUMMARY.md from the live audit_log
  concurrent_attack_stress_test.py       8 simultaneous evasive rings + baseline-controlled interference check
  infra_resilience_test.py                LLM-call resilience + malformed-record handling, both tested for real
  time_drift_simulation.py                 does detection decay across sequential periods of evolving fraud tactics?
  adversarial_recommender/               5-stage recommend-only engine: probes for gaps, never modifies live logic
  cod_collusion/                        second loss type (stretch) — reuses Stage 2/3 clustering unchanged
  external_validation/                   same Stage 2/3 clustering vs. real YelpChi/Amazon/Elliptic fraud data
frontend/
  streamlit_app.py             entry point — page config, sidebar pipeline controls, navigation
  shared.py                     shared cached loaders (graph, clusters, eval report) used by every page
  app_pages/
    overview.py                  landing page — the thesis, headline KPIs, pipeline walkthrough
    flagged_clusters.py           filterable/searchable table + case detail with embedded graph
    confounders.py                 filterable confounder callout — correctly-left-alone vs. wrongly-flagged
    graph_explorer.py               free-form subgraph viewer
    live_injection.py                drop a new ring into the running system and watch it get flagged
    metrics.py                        precision/recall, dev/holdout split, recall-by-difficulty, confidence calibration, FRAUDAR, scale stress test, cost sensitivity
    compliance.py                       live RBI FREE-AI report (Fair/Reliable/Explainable/Auditable/Ethical) incl. the fairness audit
    recommendations.py                 pending/awaiting-confirmation/history queue for the recommendation engine
    audit_log.py                       full input-evidence/output audit trail
data/
  raw/                          synthetic accounts/sessions/referrals/instruments/orders
  ground_truth/                  planted rings + confounders (never read by the detector)
  processed/                      pipeline output (clusters.json, eval_report.json, cases.json)
  frozen_snapshot/                 reset point for the live-injection demo (see backend/snapshot.py)
  cod/                              second loss type's own separate dataset — never touches the above
  external/                          real third-party fraud datasets (gitignored, ~831MB — see below)
  scale_test/                         10x/50x synthetic cohorts for the scale stress test — never touches the above
  adversarial_recommender/             used-seed manifest, cadence state, disposable fresh-eval runs (gitignored)
docs/
  explainer.html                   standalone visual explainer — open this first
  ARCHITECTURE.md                   Stage 1-8 diagram + design rationale + known limitations
  SECOND_LOSS_TYPE.md                COD serial-refusal collusion — what's reused vs. new, and why
  EXTERNAL_VALIDATION.md              same clustering tested on real labeled fraud data (YelpChi/Amazon/Elliptic)
  FAIRNESS_AUDIT.md                     confounder false-positive rate by geographic tier (RBI FREE-AI "Fair")
  COST_THRESHOLD_SENSITIVITY.md          real-₹ cost sweep of Stage 5's two judgment-call thresholds
  SCALE_STRESS_TEST.md                    real 10x/50x runtime curve, two real bottlenecks found and fixed
  FRAUDAR_CROSSCHECK.md                   independent densest-subgraph method vs. our own flagged clusters
  ADVERSARIAL_RECOMMENDER.md               5-stage recommend-only engine: design, SNAM citation, real results, round-2 resolution
  COMPLIANCE_SUMMARY.md                auto-generated RBI FREE-AI alignment report (regenerate after any run)
  CONCURRENT_ATTACK_STRESS_TEST.md          8 simultaneous evasive rings, baseline-controlled interference check
  INFRASTRUCTURE_RESILIENCE_TEST.md          LLM-call resilience + malformed-record handling, 2 real bugs found & fixed
  TIME_DRIFT_SIMULATION.md                    does detection decay as tactics evolve over 4 sequential periods?
  PRE_SUBMISSION_CHECK.md                      final cross-doc consistency pass before submission
  PITCH_SCRIPT.md                       5-minute pitch video script
```

## Scope

**In scope:** synthetic data with planted rings *and* planted legitimate confounders (both with known ground truth), deterministic graph clustering, cluster feature scoring, a rule-based confounder filter, a bounded LLM narrative layer, a confounder-aware eval harness, a graph-visualization dashboard, a live ring-injection demo control, and an adversarial stress test that measures — not just asserts — where detection breaks.

**Explicitly out of scope:** any auto-ban/auto-block/auto-clawback action path (recommendations only — a human executes), real device-fingerprinting/IP-intelligence integration (synthetic data only), real-time streaming detection (this is batch analysis of a synthetic cohort).

**Stretch, built but not held to the same rigor as the primary system:** a second loss type (COD serial-refusal collusion) proving the graph/clustering architecture generalizes — see [`docs/SECOND_LOSS_TYPE.md`](docs/SECOND_LOSS_TYPE.md).

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full stage-by-stage design and the honest limitations section.
