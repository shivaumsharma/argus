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

Provider chain, tried in order, degrading on failure: Claude (BRD's specified
provider, if ANTHROPIC_API_KEY is available) -> Gemini (a free-tier fallback,
if GEMINI_API_KEY/GOOGLE_API_KEY is available) -> a deterministic template
writeup built directly from the same Stage 4 features (clearly labeled
llm_mode="fallback_template"). The pipeline always produces a full result set
regardless of which credentials exist.
"""

import json
import logging
import os
import re
import time
from typing import Literal

from pydantic import BaseModel

logging.getLogger("google_genai.models").setLevel(logging.ERROR)  # silences the repeated AFC-usage notice

from . import db
from .pipeline.data_io import PROCESSED_DIR

MODEL_ANTHROPIC = "claude-opus-5"
# gemini-3.6-flash's free tier turned out to be a 20-requests/DAY quota (very new
# model, presumably still rolling out broader limits) -- exhausted almost
# immediately. gemini-flash-lite-latest carries its own, much larger free-tier
# quota (per Google's docs: ~1000 requests/day, ~30/minute) and is a stable
# rolling alias rather than a specific dated snapshot, so it won't go stale.
MODEL_GEMINI = "gemini-flash-lite-latest"

# Proactively spacing calls avoids hammering the per-minute limit; the reactive
# retry below is the safety net for when spacing alone isn't enough (clock
# jitter, a shared quota, etc). A per-day quota exhausting mid-run is NOT
# retryable within the same run -- that's handled by giving up after
# RATE_LIMIT_MAX_RETRIES and falling back to the template for the rest.
GEMINI_MIN_INTERVAL_SECONDS = 3.0
RATE_LIMIT_MAX_RETRIES = 3
RATE_LIMIT_DEFAULT_DELAY = 15.0

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

You never recommend banning, blocking, suspending accounts, or any irreversible action -- that is permanently out of scope for this role, no matter how strong the evidence looks. A human always executes the final action.

Respond with ONLY the JSON object matching the required schema -- no prose before or after it."""


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


# --------------------------------------------------------------------------
# Provider chain: Claude -> Gemini (free tier) -> deterministic template
# --------------------------------------------------------------------------

def _try_anthropic_client(verbose=True):
    try:
        import anthropic
        return anthropic.Anthropic()
    except Exception as e:
        if verbose:
            print(f"Anthropic unavailable ({type(e).__name__}: {e}).")
        return None


def _get_env(name: str):
    """os.environ first; on Windows, fall back to the User registry directly.

    A `setx` from a terminal opened after this process started writes to the
    registry but never reaches this process's inherited environment block --
    Windows only propagates it to processes launched fresh after the write.
    Reading the registry directly sidesteps needing anyone to restart anything.
    """
    val = os.environ.get(name)
    if val:
        return val
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
                val, _ = winreg.QueryValueEx(key, name)
                return val or None
        except (FileNotFoundError, OSError):
            return None
    return None


def _try_gemini_client(verbose=True):
    key = _get_env("GEMINI_API_KEY") or _get_env("GOOGLE_API_KEY")
    if not key:
        if verbose:
            print("Gemini unavailable (no GEMINI_API_KEY / GOOGLE_API_KEY set).")
        return None
    try:
        from google import genai
        return genai.Client(api_key=key)
    except Exception as e:
        if verbose:
            print(f"Gemini client init failed ({type(e).__name__}: {e}).")
        return None


def _call_anthropic(client, prompt):
    response = client.messages.parse(
        model=MODEL_ANTHROPIC,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
        output_format=CaseInvestigation,
    )
    return response.parsed_output.model_dump()


def _call_gemini(client, prompt):
    from google.genai import types
    response = client.models.generate_content(
        model=MODEL_GEMINI,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_json_schema=CaseInvestigation.model_json_schema(),
        ),
    )
    return CaseInvestigation.model_validate_json(response.text).model_dump()


def _is_rate_limit_error(e: Exception) -> bool:
    return getattr(e, "code", None) == 429


def _parse_retry_delay(e: Exception, default: float = RATE_LIMIT_DEFAULT_DELAY) -> float:
    """Extract the server-suggested retry delay (e.g. "retryDelay": "49s") if present."""
    m = re.search(r"retryDelay['\"]?\s*[:=]\s*['\"]?(\d+(?:\.\d+)?)s", str(e))
    if m:
        return float(m.group(1)) + 1.0  # small buffer
    return default


def _build_provider_chain(verbose=True):
    """Returns an ordered list of (mode_name, client, call_fn) for every provider with usable credentials."""
    chain = []
    anthropic_client = _try_anthropic_client(verbose)
    if anthropic_client is not None:
        chain.append(("anthropic", anthropic_client, _call_anthropic))
    gemini_client = _try_gemini_client(verbose)
    if gemini_client is not None:
        chain.append(("gemini", gemini_client, _call_gemini))
    return chain


def investigate_all(clusters_path=None, verbose=True):
    with open(clusters_path or (PROCESSED_DIR / "clusters.json")) as f:
        all_clusters = json.load(f)
    flagged = [c for c in all_clusters if c["flagged"]]

    provider_chain = _build_provider_chain(verbose)
    provider_idx = 0
    if verbose:
        if provider_chain:
            print(f"LLM provider chain: {' -> '.join(m for m, _, _ in provider_chain)} -> fallback_template")
        else:
            print("No LLM credentials available at all; using template fallback for every cluster.")

    last_call_ts = {}  # mode -> monotonic timestamp of the last call, for proactive rate-limit spacing

    results = []
    for i, cluster in enumerate(flagged):
        prompt = build_prompt(cluster)
        result = None
        mode = "fallback_template"

        while provider_idx < len(provider_chain):
            mode, client, call_fn = provider_chain[provider_idx]

            if mode == "gemini":
                elapsed = time.monotonic() - last_call_ts.get(mode, 0)
                if elapsed < GEMINI_MIN_INTERVAL_SECONDS:
                    time.sleep(GEMINI_MIN_INTERVAL_SECONDS - elapsed)

            retries_left = RATE_LIMIT_MAX_RETRIES
            while True:
                try:
                    last_call_ts[mode] = time.monotonic()
                    result = call_fn(client, prompt)
                    break
                except Exception as e:
                    if _is_rate_limit_error(e) and retries_left > 0:
                        delay = _parse_retry_delay(e)
                        if verbose:
                            print(f"{mode} rate-limited; waiting {delay:.0f}s and retrying ({retries_left} retries left)...")
                        time.sleep(delay)
                        retries_left -= 1
                        continue
                    if verbose:
                        print(f"{mode} call failed ({type(e).__name__}: {e}); "
                              f"{'trying next provider' if provider_idx + 1 < len(provider_chain) else 'falling back to template'} "
                              f"for remaining clusters.")
                    result = None
                    break
            if result is not None:
                break
            provider_idx += 1
            mode = "fallback_template"

        if result is None:
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
        from collections import Counter
        mode_counts = Counter(r["mode"] for r in results)
        print(f"\nInvestigated {len(results)} flagged clusters: "
              + ", ".join(f"{n} via {m}" for m, n in mode_counts.items()))
        print(f"Written -> {PROCESSED_DIR / 'cases.json'}")

    return results


if __name__ == "__main__":
    investigate_all()
