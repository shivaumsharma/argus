# Compliance summary — RBI FREE-AI alignment

*Auto-generated from the live audit_log and clusters store — 2026-08-28 09:10 UTC. Every number below is computed from this run, not asserted.*

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

The audit_log table currently holds **248 entries**, every one with its full input evidence and output stored as JSON, queryable by cluster ID:

- `llm_investigation_gemini`: 74
- `stage5_confounder_filter`: 174

This means any flag can be reconstructed end to end after the fact — which graph edges fired, which Stage 4 features were computed, why Stage 5 did or didn't suppress the flag, and exactly what evidence the LLM saw before it wrote its case. Nothing is decided or discarded silently.

## Fair

The concrete fairness metric for this system is the **confounder false-positive rate: 2.5%** (1 of 40 planted legitimate clusters — real households, hostels, office networks, and organic referral trees — wrongly flagged). Stage 5 exists specifically to prevent dense, legitimate clusters from being punished for looking structurally similar to a fraud ring; this number is reported honestly rather than folded into an aggregate accuracy figure that would hide it.

Fairness is also architectural, not just measured: every recommendation is bounded to `HOLD_BONUS` / `MANUAL_REVIEW` / `NO_ACTION`, so a false positive costs a delayed payout pending human review, never an executed penalty. There is no code path in this system that can ban, block, or claw back funds automatically.

## Reliable

Hard-signal ring recall: **100.0%**. Soft-signal ring recall: **82.5%** — reported separately, not blended, because it is the genuinely harder detection case and the honest number is lower. Cluster-level precision: **98.6%**. All three are measured on a held-out split of ground truth never used to pick a threshold.

Stage 8's self-reported LLM confidence was checked against ground truth across 74 live-LLM cases: 1 negative example(s) exist in the flagged set, which is too few for a statistically meaningful calibration curve, and this report says so rather than present one. See the dashboard's Metrics page for the full decile breakdown.

## Ethical / human-in-the-loop

Of the 74 flagged clusters, 74 carry a real LLM-authored case (vs. 0 on the deterministic template fallback), and every one recommends exactly one of three bounded actions: `HOLD_BONUS` (73), `NO_ACTION` (1). The LLM never sees raw account data (no names, phones, emails) — only the aggregate evidence the deterministic pipeline already computed — and it never decides whether a cluster is suspicious; that decision is made by Stages 1-5 before the LLM is invoked at all.

---

_Dataset: 80 planted rings, 40 planted confounders. Regenerate this report after any pipeline run with `python -m backend.compliance_report`._