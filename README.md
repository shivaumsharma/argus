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

**Tested on real, independently-labeled fraud data too, not just our own construction — node-level, not ring-level, and reported with raw counts, not just rates.** The unmodified Stage 2/3 clustering, run against YelpChi (99.2% precision, 6.8x lift over base rate on real fake-review collusion, 1,143 flagged accounts — large enough to trust) and Elliptic (72.0% precision, 7.3x lift on a real Bitcoin transaction graph, 829 flagged accounts — the deliberately weakest-fit domain tested). Amazon's result doesn't make that list: only 4 clusters / 11 accounts total were ever flagged, so its 82%-looking figure is reported as the raw count it is (9 of 11 correct) rather than a rate — too small a sample to trust either way. Full methodology, raw counts, and the node-vs-ring-level distinction in [`docs/EXTERNAL_VALIDATION.md`](docs/EXTERNAL_VALIDATION.md).

**Fairness audit against RBI FREE-AI's "Fair" pillar**: shared device/IP is also just how families and hostel residents live, not fraud — so does Stage 5's confounder false-positive rate skew by geography? Code-level check confirms `home_pincode` is never read anywhere in Stages 1-5 (no direct bias path); tagging the 40 planted confounders by real Tier-1-metro pincode prefixes finds 0 FP in 4 Tier-1-linked confounders vs. 1 FP in 36 Tier-2/3 confounders — a real result, honestly reported as **too small a sample to mean anything either way** (1 total false positive across the whole dataset), with the indirect real-world risk named explicitly rather than papered over. Full methodology and the "what production would need" gap in [`docs/FAIRNESS_AUDIT.md`](docs/FAIRNESS_AUDIT.md).

**Cost-calibrated threshold sensitivity**: Stage 5's two judgment-call thresholds are swept 1-4 by replaying the exact production filter function against real evidence — with a false-negative cost computed from real data (Rs 1,041 average fraudulent payout per missed ring, from `data/raw/referrals.csv`) and a false-positive cost swept across 3 labeled assumption scenarios (support review time, plus a churn-risk estimate grounded in real order values). Real finding: the device-branch threshold has a strict, same-recall, fewer-false-positive improvement available (3→2) that the frozen defaults leave on the table — reported as a testable hypothesis for the next dev-split tuning pass, not applied here, to preserve the held-out discipline used everywhere else in this project. Full breakdown in [`docs/COST_THRESHOLD_SENSITIVITY.md`](docs/COST_THRESHOLD_SENSITIVITY.md).

**Scale stress test**: the exact same pipeline rerun at 10x and 50x this dataset's account count (75,000 and 375,000 accounts), measured, not asserted. Building it surfaced two real performance bugs — an unindexed per-cluster pandas scan in Stage 4 and an O(n²) list scan in the generator — both root-caused, fixed, and verified byte-identical against the frozen dataset's output before and after. Clean result: **under 80 seconds end to end at 375,000 accounts**, scaling close to linearly with volume. One anomalous 8,294-second measurement was caught, investigated, and confirmed as a one-off system artifact rather than reported as-is. Full writeup in [`docs/SCALE_STRESS_TEST.md`](docs/SCALE_STRESS_TEST.md).

**FRAUDAR cross-check**: an independent, published, camouflage-resistant densest-subgraph method (Hooi et al., KDD 2016 best paper) run standalone against the same frozen dataset's device/instrument/subnet attributes only — no referral timing, no order data, which means this specific check is scoped to hard-signal rings only (soft rings are defined by having no device/instrument signal at all, so they're structurally out of scope here). Algorithm verified against a public reference implementation, not approximated from memory. The one comparable number: **FRAUDAR recovers 15 of the 40 planted hard-signal rings exactly (37.5%), against Stage 2's 100% (40/40) on the identical 40 rings from the identical underlying signals** — real cross-validation for those 15 from a detection mechanism that never sees ground truth, and a concrete, measured illustration of why connected components (extracted whole regardless of relative density) outperforms generic density-peeling (which dilutes smaller rings into a larger residual block) for this specific problem. It also never cleanly flags a single one of the 40 planted confounders. "Independent" carries one honest asterisk though — building this surfaced a case where the stopping rule for how many blocks to report was first tuned using inside knowledge of our own ground truth, caught, and fixed to a dataset-blind threshold (verified to give an identical result). Full writeup, including that story and a real bug found and fixed along the way, in [`docs/FRAUDAR_CROSSCHECK.md`](docs/FRAUDAR_CROSSCHECK.md).

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
python -m backend.compliance_report                      # auto-generates docs/COMPLIANCE_SUMMARY.md from the live audit_log
python -m backend.demo_failure_injection                 # proves the pipeline survives missing device/IP/instrument data
python -m backend.adversarial_stress_test                 # finds where detection actually breaks (see Known Limitations)
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
    metrics.py                        precision/recall, dev/holdout split, recall-by-difficulty, confidence calibration
    audit_log.py                       full input-evidence/output audit trail
data/
  raw/                          synthetic accounts/sessions/referrals/instruments/orders
  ground_truth/                  planted rings + confounders (never read by the detector)
  processed/                      pipeline output (clusters.json, eval_report.json, cases.json)
  frozen_snapshot/                 reset point for the live-injection demo (see backend/snapshot.py)
  cod/                              second loss type's own separate dataset — never touches the above
  external/                          real third-party fraud datasets (gitignored, ~831MB — see below)
  scale_test/                         10x/50x synthetic cohorts for the scale stress test — never touches the above
docs/
  explainer.html                   standalone visual explainer — open this first
  ARCHITECTURE.md                   Stage 1-8 diagram + design rationale + known limitations
  SECOND_LOSS_TYPE.md                COD serial-refusal collusion — what's reused vs. new, and why
  EXTERNAL_VALIDATION.md              same clustering tested on real labeled fraud data (YelpChi/Amazon/Elliptic)
  FAIRNESS_AUDIT.md                     confounder false-positive rate by geographic tier (RBI FREE-AI "Fair")
  COST_THRESHOLD_SENSITIVITY.md          real-₹ cost sweep of Stage 5's two judgment-call thresholds
  SCALE_STRESS_TEST.md                    real 10x/50x runtime curve, two real bottlenecks found and fixed
  FRAUDAR_CROSSCHECK.md                   independent densest-subgraph method vs. our own flagged clusters
  COMPLIANCE_SUMMARY.md                auto-generated RBI FREE-AI alignment report (regenerate after any run)
  PITCH_SCRIPT.md                       5-minute pitch video script
```

## Scope

**In scope:** synthetic data with planted rings *and* planted legitimate confounders (both with known ground truth), deterministic graph clustering, cluster feature scoring, a rule-based confounder filter, a bounded LLM narrative layer, a confounder-aware eval harness, a graph-visualization dashboard, a live ring-injection demo control, and an adversarial stress test that measures — not just asserts — where detection breaks.

**Explicitly out of scope:** any auto-ban/auto-block/auto-clawback action path (recommendations only — a human executes), real device-fingerprinting/IP-intelligence integration (synthetic data only), real-time streaming detection (this is batch analysis of a synthetic cohort).

**Stretch, built but not held to the same rigor as the primary system:** a second loss type (COD serial-refusal collusion) proving the graph/clustering architecture generalizes — see [`docs/SECOND_LOSS_TYPE.md`](docs/SECOND_LOSS_TYPE.md).

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full stage-by-stage design and the honest limitations section.
