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
| Stage 5 — confounder filter | **New thresholds, same discipline.** A shared address alone is common and legitimate (a real hostel, a real family); a shared address *paired with* a refusal rate far above the organic ~10-15% baseline is not. |

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
