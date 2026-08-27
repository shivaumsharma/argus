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

| Metric | Value |
|---|---|
| Hard-signal ring recall | **100%** (9/9) |
| Soft-signal ring recall | **88.9%** (8/9) — the real test of the approach |
| Confounder false-positive rate | **8.3%** (1/12) |
| Cluster-level precision | **94.4%** |

Both misses are individually traceable to specific feature values, not bugs — see [`data/processed/eval_report.json`](data/processed/eval_report.json) and [Known Limitations](docs/ARCHITECTURE.md#known-limitations-honest) below. The dataset deliberately includes a "hard mode" ring variant (slower claims, noisier order values) and a "tight" household confounder (compressed signup window) specifically so these numbers aren't a suspiciously perfect 100% — a synthetic benchmark that never misses anything isn't testing the hard cases.

## Quickstart

```bash
python -m venv venv
venv\Scripts\pip install -r requirements.txt          # Windows
# source venv/bin/activate && pip install -r requirements.txt   # macOS/Linux

python -m backend.generate_data                        # Day 1 — synthetic accounts + planted rings/confounders
python -m backend.pipeline.run_pipeline                 # Stages 1-5 — graph, clustering, scoring, filter
python -m backend.pipeline.eval                          # precision/recall vs. ground truth
python -m backend.llm_investigate                        # Stage 8 — LLM case writeups (set ANTHROPIC_API_KEY for live mode)
python -m backend.demo_failure_injection                 # proves the pipeline survives missing device/IP/instrument data

streamlit run frontend/app.py                             # dashboard
uvicorn backend.api:app --reload                          # optional: read-only REST API over the same store
```

Without `ANTHROPIC_API_KEY` set, the LLM stage falls back to a clearly-labeled deterministic template writeup so the pipeline still runs end to end.

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
  app.py                       Streamlit dashboard — case cards, confounder callout, graph explorer, metrics, audit log
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
