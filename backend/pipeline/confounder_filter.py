"""
Stage 5 -- confounder filter. Explicit rules that actively look for signals of
a LEGITIMATE cluster (activity spread over months, diverse order values,
organic post-signup engagement) and suppress the flag when they dominate.

This stage's entire job is to not flag confounders. Every decision returns a
plain-English reason so it is auditable, matching the RBI FREE-AI
explainability expectation the BRD calls out.
"""

# Thresholds tuned against the dev split of planted rings/confounders (see eval.py).
SPREAD_OUT_DAYS = 21
DIVERSE_ORDER_CV = 0.28
ENGAGED_SESSIONS = 1.5
TEMPLATED_ORDER_CV = 0.15
BURST_DAYS = 7
FAST_CLAIM_HOURS = 12
DORMANT_FRAC = 0.4

# The two decision-boundary constants a threshold-sensitivity sweep varies (see
# backend/cost_threshold_sensitivity.py). Kept as named defaults, not hardcoded
# inline, so that script calls this exact production function with an
# overridden threshold rather than reimplementing the decision logic.
DEVICE_CLEAR_ORGANIC_THRESHOLD = 3   # shared-device cluster clears if organic_score >= this
SOFT_CLEAR_ORGANIC_THRESHOLD = 2     # soft-only cluster clears if organic_score >= this
SOFT_FLAG_SUSPICION_THRESHOLD = 3    # soft-only cluster flags if suspicion_score >= this


def evaluate_cluster(features: dict, soft_flag_suspicion_threshold: int = SOFT_FLAG_SUSPICION_THRESHOLD,
                      device_clear_organic_threshold: int = DEVICE_CLEAR_ORGANIC_THRESHOLD) -> dict:
    f = features
    cv = f["order_value_cv"]
    dormant = f["claim_then_dormant_frac"]
    claim_v = f["bonus_claim_velocity_hours"]

    is_spread_out = f["signup_span_days"] >= SPREAD_OUT_DAYS
    is_diverse_orders = cv is not None and cv >= DIVERSE_ORDER_CV
    has_engagement = f["post_signup_engagement"] >= ENGAGED_SESSIONS
    organic_score = int(is_spread_out) + int(is_diverse_orders) + int(has_engagement)

    is_burst = f["signup_span_days"] <= BURST_DAYS
    is_templated = cv is not None and cv < TEMPLATED_ORDER_CV
    is_dormant = dormant is not None and dormant >= DORMANT_FRAC
    is_fast_claim = claim_v is not None and claim_v <= FAST_CLAIM_HOURS
    suspicion_score = int(is_burst) + int(is_templated) + int(is_dormant) + int(is_fast_claim)

    if f["shared_instrument"]:
        return _verdict(True, organic_score, suspicion_score,
                         "Distinct accounts share a payment instrument -- near-certain farming signal; "
                         "legitimate reason for this is rare, so organic behavior does not override it.")

    if f["shared_device"]:
        if organic_score >= device_clear_organic_threshold:
            return _verdict(False, organic_score, suspicion_score,
                             "Shared device, but activity is spread out, order values are diverse, and members "
                             "stay engaged for months after signup -- consistent with a shared household device.")
        return _verdict(True, organic_score, suspicion_score,
                         "Shared device with a burst signup, templated orders, or claim-then-dormant behavior -- "
                         "does not look like organic shared-device use.")

    # soft-signal only: IP overlap and/or referral edges, no device or instrument sharing
    if organic_score >= SOFT_CLEAR_ORGANIC_THRESHOLD:
        return _verdict(False, organic_score, suspicion_score,
                         "No shared device or instrument; spread-out timing, diverse orders, and ongoing "
                         "engagement dominate -- looks like an organic cluster (office network, hostel wifi, "
                         "or influencer referral tree).")
    if suspicion_score >= soft_flag_suspicion_threshold:
        return _verdict(True, organic_score, suspicion_score,
                         "No shared device or instrument, but signup burst, templated order values, fast bonus "
                         "claims, and dormancy after claim line up -- classic soft-signal farming pattern.")

    return _verdict(False, organic_score, suspicion_score,
                     "Soft-signal cluster with no clear suspicious pattern and insufficient organic evidence -- "
                     "left unflagged by default (evidence too weak either way).")


def _verdict(flag, organic_score, suspicion_score, reason):
    return {
        "flagged": flag,
        "organic_score": organic_score,
        "suspicion_score": suspicion_score,
        "reason": reason,
    }
