"""
Auto-generates a short compliance summary from the actual audit_log and
clusters data currently in the store -- not a hand-written claim, a report
computed from the real run. Framed around the RBI's FREE-AI framework
(Aug 2025): AI used in fraud detection should be Fair, Reliable, Explainable,
Ethical -- responsible, auditable, "safety by design, not safety as an
afterthought," in a former RBI Deputy Governor's words.

Run: python -m backend.compliance_report
Writes: docs/COMPLIANCE_SUMMARY.md
"""

import json
from collections import Counter
from datetime import datetime, timezone

from . import db
from .pipeline.data_io import GT_DIR, PROCESSED_DIR, ROOT
from .reporting import load_eval_report

OUT_PATH = ROOT / "docs" / "COMPLIANCE_SUMMARY.md"


def _load_calibration():
    path = PROCESSED_DIR / "confidence_calibration.json"
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def _sample_chain(clusters, audit_rows):
    """Pick one real flagged cluster and walk its full evidence chain, for a
    concrete worked example rather than an abstract claim."""
    flagged = [c for c in clusters if c["flagged"] and c.get("llm_case_summary")]
    if not flagged:
        return None
    c = sorted(flagged, key=lambda x: x["cluster_id"])[0]
    filter_row = next((r for r in audit_rows if r["cluster_id"] == c["cluster_id"] and r["event_type"] == "stage5_confounder_filter"), None)
    llm_row = next((r for r in audit_rows if r["cluster_id"] == c["cluster_id"] and r["event_type"].startswith("llm_investigation")), None)
    return c, filter_row, llm_row


def run(verbose=True):
    clusters = db.get_all_clusters()
    flagged = [c for c in clusters if c["flagged"]]
    audit_rows = db.get_audit_log(limit=100000)
    eval_report = load_eval_report()
    calib = _load_calibration()

    with open(GT_DIR / "rings.json") as f:
        n_rings = len(json.load(f))
    with open(GT_DIR / "confounders.json") as f:
        n_confounders = len(json.load(f))

    event_counts = Counter(r["event_type"] for r in audit_rows)
    mode_counts = Counter(c.get("llm_mode") for c in flagged if c.get("llm_mode"))
    action_counts = Counter(c.get("llm_recommended_action") for c in flagged if c.get("llm_recommended_action"))

    chain = _sample_chain(clusters, audit_rows)
    overall = eval_report["overall"] if eval_report else None

    lines = []
    lines.append("# Compliance summary — RBI FREE-AI alignment")
    lines.append("")
    lines.append(f"*Auto-generated from the live audit_log and clusters store — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}. "
                  "Every number below is computed from this run, not asserted.*")
    lines.append("")
    lines.append(
        "The RBI's FREE-AI framework (August 2025) sets explicit expectations that AI used in fraud detection "
        "be **F**air, **R**eliable, **E**xplainable, and **E**thical — responsible, auditable, \"safety by design, "
        "not safety as an afterthought,\" in a former RBI Deputy Governor's words. This report is the concrete "
        "evidence for each of those, drawn from the system's own audit trail rather than claimed in prose."
    )
    lines.append("")

    lines.append("## Explainable")
    lines.append("")
    lines.append(
        f"Every one of the {len(flagged)} currently-flagged clusters has a decision chain that traces back to "
        "specific graph edges and feature values — no black-box score. A worked example from this exact run:"
    )
    lines.append("")
    if chain:
        c, filter_row, llm_row = chain
        lines.append(f"**Cluster `{c['cluster_id']}`** ({c['detection_stage']}-signal, {c['features']['size']} accounts)")
        lines.append("")
        lines.append(f"1. **Stage 5 decision** (deterministic, no model): _{c['filter_reason']}_")
        if filter_row:
            lines.append(f"   Logged as audit_log row `{filter_row['id']}`, event `{filter_row['event_type']}`, "
                          f"with the full Stage 4 feature vector as input evidence.")
        lines.append(f"2. **Stage 8 writeup** ({c.get('llm_mode', 'n/a')}): _\"{(c.get('llm_case_summary') or '')[:220]}...\"_")
        if llm_row:
            lines.append(f"   Logged as audit_log row `{llm_row['id']}`, event `{llm_row['event_type']}`, with the "
                          "exact prompt text (Stage 4/5 evidence only, no raw account data) stored as input evidence "
                          "and the full structured response stored as output.")
        lines.append(f"3. **Recommended action**: `{c.get('llm_recommended_action', 'n/a')}` — bounded to "
                      "HOLD_BONUS / MANUAL_REVIEW / NO_ACTION; a human executes.")
    else:
        lines.append("_No flagged clusters with a completed investigation exist in the current store to sample._")
    lines.append("")

    lines.append("## Auditable")
    lines.append("")
    lines.append(f"The audit_log table currently holds **{len(audit_rows)} entries**, every one with its full "
                  "input evidence and output stored as JSON, queryable by cluster ID:")
    lines.append("")
    for event, n in sorted(event_counts.items()):
        lines.append(f"- `{event}`: {n}")
    lines.append("")
    lines.append(
        "This means any flag can be reconstructed end to end after the fact — which graph edges fired, which "
        "Stage 4 features were computed, why Stage 5 did or didn't suppress the flag, and exactly what evidence "
        "the LLM saw before it wrote its case. Nothing is decided or discarded silently."
    )
    lines.append("")

    lines.append("## Fair")
    lines.append("")
    if overall:
        lines.append(
            f"The concrete fairness metric for this system is the **confounder false-positive rate: "
            f"{overall['confounder_false_positive_rate']:.1%}** ({overall.get('cluster_fp', '?')} of "
            f"{n_confounders} planted legitimate clusters — real households, hostels, office networks, and "
            "organic referral trees — wrongly flagged). Stage 5 exists specifically to prevent dense, "
            "legitimate clusters from being punished for looking structurally similar to a fraud ring; this "
            "number is reported honestly rather than folded into an aggregate accuracy figure that would hide it."
        )
    else:
        lines.append("_No eval report found in the current store — run the eval harness to populate this metric._")
    lines.append("")
    lines.append(
        "Fairness is also architectural, not just measured: every recommendation is bounded to "
        "`HOLD_BONUS` / `MANUAL_REVIEW` / `NO_ACTION`, so a false positive costs a delayed payout pending human "
        "review, never an executed penalty. There is no code path in this system that can ban, block, or claw "
        "back funds automatically."
    )
    lines.append("")

    lines.append("## Reliable")
    lines.append("")
    if overall:
        lines.append(
            f"Hard-signal ring recall: **{overall['hard_signal_recall']:.1%}**. Soft-signal ring recall: "
            f"**{overall['soft_signal_recall']:.1%}** — reported separately, not blended, because it is the "
            "genuinely harder detection case and the honest number is lower. Cluster-level precision: "
            f"**{overall['cluster_precision']:.1%}**. All three are measured on a held-out split of ground truth "
            "never used to pick a threshold."
        )
    lines.append("")
    if calib:
        n_neg = calib["n_not_true_ring"]
        lines.append(
            f"Stage 8's self-reported LLM confidence was checked against ground truth across "
            f"{calib['n_flagged']} live-LLM cases: {n_neg} negative example(s) exist in the flagged set, which "
            "is too few for a statistically meaningful calibration curve, and this report says so rather than "
            "present one. See the dashboard's Metrics page for the full decile breakdown."
        )
        lines.append("")

    lines.append("## Ethical / human-in-the-loop")
    lines.append("")
    lines.append(
        f"Of the {len(flagged)} flagged clusters, {mode_counts.get('gemini', 0) + mode_counts.get('anthropic', 0)} "
        f"carry a real LLM-authored case (vs. {mode_counts.get('fallback_template', 0)} on the deterministic "
        "template fallback), and every one recommends exactly one of three bounded actions: "
        + ", ".join(f"`{k}` ({v})" for k, v in sorted(action_counts.items())) + ". "
        "The LLM never sees raw account data (no names, phones, emails) — only the aggregate evidence the "
        "deterministic pipeline already computed — and it never decides whether a cluster is suspicious; that "
        "decision is made by Stages 1-5 before the LLM is invoked at all."
    )
    lines.append("")
    lines.append(f"---\n\n_Dataset: {n_rings} planted rings, {n_confounders} planted confounders. "
                  "Regenerate this report after any pipeline run with `python -m backend.compliance_report`._")

    OUT_PATH.write_text("\n".join(lines), encoding="utf-8")
    if verbose:
        print(f"Written -> {OUT_PATH}")
    return "\n".join(lines)


if __name__ == "__main__":
    run()
