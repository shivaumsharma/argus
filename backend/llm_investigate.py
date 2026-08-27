"""
Day 5 -- LLM investigation/narrative layer (BRD Section 8).

Only clusters that already survived Stage 5 reach this module. Each one gets
ONLY the structured evidence Stage 4 already computed -- which edges fired,
the feature scores, the deterministic filter's reason -- never raw account
data (no user_ids, phones, emails). The LLM does not decide whether the
cluster is suspicious; that was already decided upstream. Its job is to write
a plain-English case, rate its own confidence, and pick ONE bounded action.
Every field it can return is capped to HOLD_BONUS / MANUAL_REVIEW / NO_ACTION
-- there is no code path here that can ban, block, or move money.

If no Anthropic credentials are available, falls back to a deterministic
template writeup (clearly labeled llm_mode="fallback_template") built
directly from the same Stage 4 features, so the pipeline still runs end to
end without an API key.
"""

import json
from typing import Literal

from pydantic import BaseModel

from . import db
from .pipeline.data_io import PROCESSED_DIR

MODEL = "claude-opus-5"

SYSTEM_PROMPT = """You are a fraud-risk case writer for a promo/referral bonus abuse detector at an Indian payments company.

A deterministic graph-clustering pipeline has already identified this cluster of accounts as suspicious and computed behavioral features about it. You do NOT see raw customer data -- no names, phone numbers, emails, or account IDs. You only see the aggregate structural and behavioral evidence below.

Your job:
1. Write a short, plain-English case_summary (2-4 sentences) a human trust-and-safety analyst can read in ten seconds and understand exactly why this cluster looks like coordinated abuse (or, if the evidence is genuinely weak, say so).
2. Give a self-reported confidence between 0 and 1.
3. Pick exactly ONE recommended_action:
   - HOLD_BONUS: hold or reverse pending referral/signup bonuses for this cluster pending human review. Use when the evidence is strong (shared payment instrument or device, tight timing, templated spending, dormancy after claim).
   - MANUAL_REVIEW: evidence is suspicious but not conclusive enough to touch money yet; a human analyst should look closer.
   - NO_ACTION: on reflection, despite passing the deterministic filter, the evidence here is too weak to act on.
4. List key_evidence as 2-5 short strings, each citing a SPECIFIC data point from what you were given (e.g. "13 accounts share one device_fingerprint_id", "signup burst spans only 3 days", "order-value CV of 0.008 -- near-identical order amounts").

You never recommend banning, blocking, suspending accounts, or any irreversible action -- that is permanently out of scope for this role, no matter how strong the evidence looks. A human always executes the final action."""


class CaseInvestigation(BaseModel):
    case_summary: str
    confidence: float
    recommended_action: Literal["HOLD_BONUS", "MANUAL_REVIEW", "NO_ACTION"]
    key_evidence: list[str]


def build_prompt(cluster: dict) -> str:
    f = cluster["features"]

    def pct(x):
        return f"{x * 100:.0f}%" if x is not None else "n/a"

    lines = [
        f"Cluster {cluster['cluster_id']} -- surfaced by the {cluster['detection_stage']}-signal detection stage.",
        f"Size: {f['size']} accounts. Edge density among members: {f['edge_density']} (1.0 = fully interconnected).",
        f"Shared attributes observed among members: {', '.join(f['signals_present']) or 'none'}.",
        f"Shared device_fingerprint_id: {f['shared_device']} ({pct(f['shared_device_frac'])} of members on the single most common device).",
        f"Shared payment instrument_hash: {f['shared_instrument']} ({pct(f['shared_instrument_frac'])} of members on the single most common instrument).",
        f"Signup timing: span of {f['signup_span_days']} days across the cluster; average gap between consecutive signups is {f['avg_gap_hours']} hours.",
        f"Referral bonus claims: {pct(f['claim_frac'])} of members claimed a bonus"
        + (f", averaging {f['bonus_claim_velocity_hours']} hours after signup." if f["bonus_claim_velocity_hours"] is not None else "."),
        "Claim-then-dormant fraction (claimed a bonus, then went silent for 3+ days): "
        + (pct(f["claim_then_dormant_frac"]) if f["claim_then_dormant_frac"] is not None else "n/a, no claims in this cluster."),
        f"Orders placed: {f['n_orders']} total. Order-value coefficient of variation: "
        + (f"{f['order_value_cv']} (lower means order amounts are near-identical / templated)." if f["order_value_cv"] is not None else "n/a."),
        f"Post-signup engagement: on average {f['post_signup_engagement']} sessions per member happen more than 7 days after signup (higher suggests organic ongoing use).",
        f'Deterministic Stage 5 confounder filter already flagged this cluster. Its stated reason: "{cluster["filter_reason"]}"',
        f"(Internal filter scores for your context only -- organic_score={cluster['organic_score']}/3, suspicion_score={cluster['suspicion_score']}/4.)",
    ]
    return "\n".join(lines)


def _fallback_investigation(cluster: dict) -> dict:
    """Deterministic template writeup used when no LLM credentials are available."""
    f = cluster["features"]
    evidence = []
    if f["shared_instrument"]:
        evidence.append(f"{f['shared_instrument_frac'] * 100:.0f}% of members share one payment instrument")
    if f["shared_device"]:
        evidence.append(f"{f['shared_device_frac'] * 100:.0f}% of members share one device")
    if "ip_subnet_overlap" in f["signals_present"]:
        evidence.append("cluster shares an IP subnet")
    if f["signup_span_days"] <= 7:
        evidence.append(f"signup burst spans only {f['signup_span_days']} days")
    if f["order_value_cv"] is not None and f["order_value_cv"] < 0.15:
        evidence.append(f"order-value CV of {f['order_value_cv']} (near-identical amounts)")
    if f["claim_then_dormant_frac"] and f["claim_then_dormant_frac"] >= 0.4:
        evidence.append(f"{f['claim_then_dormant_frac'] * 100:.0f}% claim-then-dormant")
    if not evidence:
        evidence.append(cluster["filter_reason"])

    if f["shared_instrument"] or (f["shared_device"] and cluster["suspicion_score"] >= 2):
        action, confidence = "HOLD_BONUS", 0.85
    elif cluster["suspicion_score"] >= 3:
        action, confidence = "HOLD_BONUS", 0.72
    elif cluster["suspicion_score"] >= 2:
        action, confidence = "MANUAL_REVIEW", 0.55
    else:
        action, confidence = "MANUAL_REVIEW", 0.4

    summary = (
        f"[template fallback -- no LLM available] Cluster {cluster['cluster_id']} ({f['size']} accounts, "
        f"{cluster['detection_stage']}-signal detection) was flagged by the deterministic filter: "
        f"{cluster['filter_reason']}"
    )
    return {"case_summary": summary, "confidence": confidence, "recommended_action": action, "key_evidence": evidence}


def investigate_all(clusters_path=None, verbose=True):
    with open(clusters_path or (PROCESSED_DIR / "clusters.json")) as f:
        all_clusters = json.load(f)
    flagged = [c for c in all_clusters if c["flagged"]]

    use_llm = True
    client = None
    try:
        import anthropic
        client = anthropic.Anthropic()
    except Exception as e:
        use_llm = False
        if verbose:
            print(f"anthropic SDK unavailable ({e}); using template fallback for all cases.")

    results = []
    for i, cluster in enumerate(flagged):
        prompt = build_prompt(cluster)
        mode = "llm" if use_llm else "fallback_template"

        if use_llm:
            try:
                response = client.messages.parse(
                    model=MODEL,
                    max_tokens=1024,
                    system=SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": prompt}],
                    output_format=CaseInvestigation,
                )
                result = response.parsed_output.model_dump()
            except Exception as e:
                use_llm = False
                mode = "fallback_template"
                if verbose:
                    print(f"LLM call failed ({type(e).__name__}: {e}); switching to template fallback for remaining clusters.")
                result = _fallback_investigation(cluster)
        else:
            result = _fallback_investigation(cluster)

        result["confidence"] = max(0.0, min(1.0, float(result["confidence"])))
        db.write_llm_result(cluster["cluster_id"], prompt, result, mode)
        results.append({"cluster_id": cluster["cluster_id"], "mode": mode, **result})
        if verbose:
            print(f"[{i+1}/{len(flagged)}] {cluster['cluster_id']} ({mode}) -> {result['recommended_action']} "
                  f"(confidence {result['confidence']:.2f})")

    with open(PROCESSED_DIR / "cases.json", "w") as f:
        json.dump(results, f, indent=2)

    if verbose:
        n_llm = sum(1 for r in results if r["mode"] == "llm")
        print(f"\nInvestigated {len(results)} flagged clusters ({n_llm} via live LLM, {len(results) - n_llm} via template fallback).")
        print(f"Written -> {PROCESSED_DIR / 'cases.json'}")

    return results


if __name__ == "__main__":
    investigate_all()
