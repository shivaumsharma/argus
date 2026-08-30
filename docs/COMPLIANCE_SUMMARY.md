# Compliance summary — RBI FREE-AI alignment

*Auto-generated from the live audit_log and clusters store — 2026-08-30 10:08 UTC. Every number below is computed from this run, not asserted. Also rendered live in the dashboard's **Compliance** tab, from this exact same computed data.*

The RBI's FREE-AI framework (August 2025) sets explicit expectations that AI used in fraud detection be **F**air, **R**eliable, **E**xplainable, and **E**thical — responsible, auditable, "safety by design, not safety as an afterthought," in a former RBI Deputy Governor's words. This report is the concrete evidence for each of those, drawn from the system's own audit trail rather than claimed in prose.

## Explainable

Every one of the 74 currently-flagged clusters has a decision chain that traces back to specific graph edges and feature values — no black-box score. A worked example from this exact run:

**Cluster `C0001`** (hard-signal, 8 accounts)

1. **Stage 5 decision** (deterministic, no model): _Distinct accounts share a payment instrument -- near-certain farming signal; legitimate reason for this is rare, so organic behavior does not override it._
   Logged as audit_log row `1`, event `stage5_confounder_filter`, with the full Stage 4 feature vector as input evidence.
2. **Stage 8 writeup** (gemini): _"This cluster of 8 accounts exhibits textbook bonus-farming behavior, characterized by 100% device and payment instrument sharing, a tight 2.39-day signup burst, and immediate bonus claims followed by total dormancy. The ..."_
   Logged as audit_log row `175`, event `llm_investigation_gemini`, with the exact prompt text (Stage 4/5 evidence only, no raw account data) stored as input evidence and the full structured response stored as output.
3. **Recommended action**: `HOLD_BONUS` — bounded to HOLD_BONUS / MANUAL_REVIEW / NO_ACTION; a human executes.

## Auditable

The audit_log table currently holds **252 entries**, every one with its full input evidence and output stored as JSON, queryable by cluster ID:

- `llm_investigation_gemini`: 74
- `recommendation_finalized`: 1
- `recommendation_proposed`: 1
- `recommendation_reevaluated`: 1
- `recommendation_reviewed`: 1
- `stage5_confounder_filter`: 174

This means any flag can be reconstructed end to end after the fact — which graph edges fired, which Stage 4 features were computed, why Stage 5 did or didn't suppress the flag, and exactly what evidence the LLM saw before it wrote its case. Nothing is decided or discarded silently. This extends to backend/adversarial_recommender/'s own recommendation lifecycle (`recommendation_proposed` / `_reviewed` / `_reevaluated` / `_finalized`) via the same table, not a parallel log.

## Fair

The concrete fairness metric for this system is the **confounder false-positive rate: 2.5%** (1 of 40 planted legitimate clusters — real households, hostels, office networks, and organic referral trees — wrongly flagged). Stage 5 exists specifically to prevent dense, legitimate clusters from being punished for looking structurally similar to a fraud ring; this number is reported honestly rather than folded into an aggregate accuracy figure that would hide it.

Fairness is also architectural, not just measured: every recommendation is bounded to `HOLD_BONUS` / `MANUAL_REVIEW` / `NO_ACTION`, so a false positive costs a delayed payout pending human review, never an executed penalty. There is no code path in this system that can ban, block, or claw back funds automatically.

**Socioeconomic false-positive audit** (`backend/fairness_audit.py`, full writeup in [`FAIRNESS_AUDIT.md`](FAIRNESS_AUDIT.md)): does the confounder false-positive rate — and, separately, ring recall — skew by a real geographic/economic tier proxy (`home_pincode`, a real 3-tier city classification, no protected attribute used anywhere)? Both are reported honestly as too small a sample (40 confounders, 80 rings, split three ways) to support a statistically meaningful comparison in either direction, including the ring-recall spread that looks real at a glance (75% Tier-1 vs. 93.8% Tier-3) but traces to a single additional miss on only 8 Tier-1 rings. Confirmed by code inspection: `home_pincode` is never read anywhere in Stages 1-5, so no direct bias path exists today.

## Reliable

Hard-signal ring recall: **100.0%**. Soft-signal ring recall: **82.5%** — reported separately, not blended, because it is the genuinely harder detection case and the honest number is lower. Cluster-level precision: **98.6%**. All three are measured on a held-out split of ground truth never used to pick a threshold.

Stage 8's self-reported LLM confidence was checked against ground truth across 89 scored clusters (74 from the primary dataset, 15 from a purpose-built supplementary batch run through the real pipeline via `backend/custom_scenario.py`, isolated scratch space): **11 negative examples**, enough spread to see a genuine trend (accuracy rises with stated confidence). See the dashboard's Metrics page for the full decile breakdown.

## Ethical / human-in-the-loop

Of the 74 flagged clusters, 74 carry a real LLM-authored case (vs. 0 on the deterministic template fallback), and every one recommends exactly one of three bounded actions: `HOLD_BONUS` (73), `NO_ACTION` (1). The LLM never sees raw account data (no names, phones, emails) — only the aggregate evidence the deterministic pipeline already computed — and it never decides whether a cluster is suspicious; that decision is made by Stages 1-5 before the LLM is invoked at all.

---

_Dataset: 80 planted rings, 40 planted confounders. Regenerate this report after any pipeline run with `python -m backend.compliance_report`._