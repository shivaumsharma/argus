# Second loss type: COD serial-refusal collusion

Stretch scope per the BRD ("only if Days 1-7 land on schedule... reusing Stages 1-5 unchanged, since the detection mechanism is identical, only the edge types differ"). This is a **separate, smaller, self-contained** system — it never touches `data/raw`, `data/ground_truth`, or the frozen promo/referral eval snapshot. Its own dataset lives under `data/cod/`.

## The loss

Accounts that repeatedly order high-value goods cash-on-delivery and refuse them at the door — a real cost to a merchant (reverse logistics, restocking, sometimes damaged goods) that has nothing to do with referral bonuses. The graph question is the same shape as the promo-abuse one: a single serial refuser looks like an unlucky customer; a *group* of accounts sharing a delivery address or a block of phone numbers, all refusing 80-100% of their COD orders, is a collusion ring.

## What's actually reused, and what isn't

| Stage | Reused? |
|---|---|
| Stage 1 — graph construction | **New.** Edges are shared `delivery_address_hash` (hard signal) and shared phone-number prefix — same first 9 characters, e.g. a block of SIMs bought together (soft signal) — instead of device/instrument/IP/referral. |
| Stage 2 — hard-signal connected components | **Unchanged.** `backend/cod_collusion/run.py` imports `stage2_hard_clusters` directly from `backend.pipeline.clustering` — the literal same function, not a reimplementation. |
| Stage 3 — Louvain community detection | **Unchanged.** Same import, same function, fed a differently-sourced graph. |
| Stage 4 — feature scoring | **New.** `refusal_rate`, `cod_fraction`, `avg_order_value`, `shared_address_frac` replace signup-burst/templating/dormancy — genuinely different behavioral tells for a genuinely different fraud pattern. |
| Stage 5 — confounder filter | **New thresholds, same discipline.** A shared address alone is common and legitimate (a real hostel, a real family); a shared address *paired with* a refusal rate far above the organic 20-40% baseline is not. |

The concrete claim this proves: the graph-and-cluster *architecture* generalizes across loss types — the same two clustering algorithms, unmodified, work against a completely different edge vocabulary. The claim it does **not** make: this has been tuned or stress-tested as rigorously as the primary system. There's no "hard mode" / "tight" difficulty tiering here, no held-out split, no LLM narrative layer, and no dashboard integration — it's a working proof of the reuse claim, not a second full submission.

## Run it

```bash
python -m backend.cod_collusion.generate_data   # 1,500-account synthetic cohort: 10 planted rings, 6 planted confounders
python -m backend.cod_collusion.run              # Stages 1-5, then a quick eval against the planted ground truth
```

## Result (single run, small sample — read accordingly)

| Metric | Value |
|---|---|
| Ring recall | 100% (10/10) |
| Confounder false-positive rate | 0% (0/6) |

With only 10 rings and 6 confounders, these percentages move in 10-17-point steps per case — treat this as "the mechanism works, cleanly, on an easier-by-construction dataset," not as evidence at the statistical resolution of the primary system's 40/40/40 held-out numbers.

## Grounded in real statistics, not invented parameters

The organic (non-colluding) COD refusal rate used to generate this dataset was originally 10-12%, an invented number. Recalibrated against India's real average COD Return-to-Origin (RTO) rate — commonly cited at 20-25%, rising to 28-35% for less-optimized operations (GoKwik 2026 data), and corroborated by Razorpay's own published guide to Cash on Delivery in India — both fetched and verified via web search before use, not assumed. `ORGANIC_COD_REFUSAL_RATE = (0.20, 0.40)` now sits directly in `backend/cod_collusion/generate_data.py`, cited in a comment at the point of use. Stage 5's `NORMAL_REFUSAL_RATE` (`backend/cod_collusion/filter.py`) was raised from 0.30 to 0.45 to match — the old threshold, and its own comment claiming "organic e-commerce refusal is roughly 5-15%," were both stale relative to the real number and have been corrected together, not left inconsistent.

**This is a change to the data-generation logic, so per this project's eval integrity protocol it required a full fresh freeze-and-reevaluate cycle, not a quiet patch:** a new seed never used before (`SEED = 48391027`, replacing `2026828`), one clean generate → pipeline → eval run, numbers reported exactly as they came out. Result: **identical headline numbers** (100% ring recall, 0% confounder FP) — the detection held up cleanly even against a harder, more realistic organic baseline, which is the honest way this recalibration was supposed to land: making the problem more realistic without making the numbers look worse *or* better than what the mechanism actually does.
