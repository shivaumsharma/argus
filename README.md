# Promo/Referral Abuse-Ring Sentinel

**Razorpay AI Buildathon 2026 — Track 02 (AI Risk Manager)**

## The actual technical argument

Fraud detection almost always means scoring one row at a time: is *this* transaction fraudulent, is *this* account risky. That architecture is mathematically incapable of catching a promo/referral abuse ring, no matter how good the model is — because a farmed account, viewed alone, is designed to look ordinary. Real-looking phone number, plausible order, no red flag. **The signal only exists across multiple rows at once**: the same device behind thirteen "different" signups, the same payment instrument reused across accounts, a referral chain that pays out in hours instead of the weeks an organic referral takes.

So this isn't a classifier. It's a graph problem:

1. **Build the entity graph** — accounts as nodes, edges wherever two accounts share a device, a payment instrument, an IP subnet, or a referral link, weighted by how strong that signal is.
2. **Cluster it deterministically** — hard-signal connected components first (near-certain: two people sharing a payment instrument is rare and legitimate), then weighted community detection (Louvain) over the full graph to catch rings that share nothing but IP overlap and referral timing.
3. **Score every candidate cluster** on real behavioral features — signup burst tightness, order-value templating, claim-then-dormant pattern, post-signup engagement.
4. **Filter out confounders** — real households, hostels, office networks, and organic referral trees are *also* dense clusters that share attributes. An explicit, explainable rule stage actively looks for the evidence that a cluster is legitimate (spread-out activity, diverse order values, ongoing engagement) and suppresses the flag.
5. **Only then does an LLM see it** — and only to write up a plain-English case for a human analyst. It never decides whether a cluster is suspicious; that's already been decided by four deterministic stages before it gets there. Every LLM recommendation is bounded to `HOLD_BONUS` / `MANUAL_REVIEW` / `NO_ACTION`. **There is no code path anywhere in this system that bans, blocks, or moves money.** A human always executes the final action.

This is also, not incidentally, what the RBI's FREE-AI framework (Aug 2025) asks for: AI used in fraud detection should be explainable and auditable by design. Every flag here traces back to a specific graph edge and a specific feature score — not a black-box judgment call.

## Results (held-out split, never used to tune thresholds)

Synthetic cohort: **7,500 accounts** — 40 hard-signal rings, 40 soft-signal rings, and 40 planted legitimate confounders (120 planted cases, ~1,536 labeled accounts), plus ~5,964 unconnected background accounts as noise.

| Metric | Value |
|---|---|
| Hard-signal ring recall | **100%** (40/40) |
| Soft-signal ring recall | **77.5%** (31/40) — the real test of the approach |
| Confounder false-positive rate | **5.0%** (2/40) |
| Cluster-level precision | **97.3%** |

Every miss is individually traceable, not a bug: all 9 missed soft rings are the deliberately "hard mode" variant (slower referral claims, noisier order-value templating); both wrongly-flagged confounders are "tight" households (a compressed, borderline-organic signup window). Zero misses on the easy cases of either category — see [`data/processed/eval_report.json`](data/processed/eval_report.json) and [Known Limitations](docs/ARCHITECTURE.md#known-limitations-honest) below.

## Quickstart

```bash
python -m venv venv
venv\Scripts\pip install -r requirements.txt          # Windows
# source venv/bin/activate && pip install -r requirements.txt   # macOS/Linux

python -m backend.generate_data                        # Day 1 — synthetic accounts + planted rings/confounders
python -m backend.pipeline.run_pipeline                 # Stages 1-5 — graph, clustering, scoring, filter
python -m backend.pipeline.eval                          # precision/recall vs. ground truth
python -m backend.llm_investigate                        # Stage 8 — LLM case writeups (set ANTHROPIC_API_KEY or GEMINI_API_KEY for live mode)
python -m backend.demo_failure_injection                 # proves the pipeline survives missing device/IP/instrument data

streamlit run frontend/streamlit_app.py                    # dashboard
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
frontend/
  streamlit_app.py             entry point — page config, sidebar pipeline controls, navigation
  shared.py                     shared cached loaders (graph, clusters, eval report) used by every page
  app_pages/
    overview.py                  landing page — the thesis, headline KPIs, pipeline walkthrough
    flagged_clusters.py           filterable/searchable table + case detail with embedded graph
    confounders.py                 filterable confounder callout — correctly-left-alone vs. wrongly-flagged
    graph_explorer.py               free-form subgraph viewer
    metrics.py                       precision/recall, dev/holdout split, recall-by-difficulty breakdown
    audit_log.py                      full input-evidence/output audit trail
data/
  raw/                          synthetic accounts/sessions/referrals/instruments/orders
  ground_truth/                  planted rings + confounders (never read by the detector)
  processed/                      pipeline output (clusters.json, eval_report.json, cases.json)
docs/
  ARCHITECTURE.md                Stage 1-8 diagram + design rationale + known limitations
  PITCH_SCRIPT.md                 5-minute pitch video script
```

## Scope

**In scope:** synthetic data with planted rings *and* planted legitimate confounders (both with known ground truth), deterministic graph clustering, cluster feature scoring, a rule-based confounder filter, a bounded LLM narrative layer, a confounder-aware eval harness, and a graph-visualization dashboard.

**Explicitly out of scope:** any auto-ban/auto-block/auto-clawback action path (recommendations only — a human executes), real device-fingerprinting/IP-intelligence integration (synthetic data only), multi-loss-type coverage beyond promo/referral abuse, real-time streaming detection (this is batch analysis of a synthetic cohort).

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full stage-by-stage design and the honest limitations section.
