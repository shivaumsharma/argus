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
# Tried lowering this to 2 -- cost_threshold_sensitivity.py's full-set sweep (dev+holdout combined)
# showed 0/40 confounder FPs instead of 1/40 at identical ring recall. Reverted after checking dev
# and holdout separately: dev-split evidence alone is 0 FP at BOTH threshold=2 and threshold=3 --
# no dev signal favors 2 at all. The one FP that "improves" lives entirely in the holdout split
# (holdout FP: 1/12 at threshold=3, 0/12 at threshold=2). Adopting 2 would mean picking a
# production threshold specifically because it happens to erase a holdout failure -- exactly the
# "tuned against the holdout" violation this project's own eval discipline forbids everywhere else.
# Left as a genuine, disclosed finding (see docs/COST_THRESHOLD_SENSITIVITY.md) -- a real dev-split
# tuning pass, done properly and before ever computing holdout numbers, could legitimately choose
# 2 in the future; this isn't that.
SOFT_CLEAR_ORGANIC_THRESHOLD = 2     # soft-only cluster clears if organic_score >= this
SOFT_FLAG_SUSPICION_THRESHOLD = 3    # soft-only cluster flags if suspicion_score >= this


def evaluate_cluster(features: dict, soft_flag_suspicion_threshold: int = SOFT_FLAG_SUSPICION_THRESHOLD,
                      device_clear_organic_threshold: int = DEVICE_CLEAR_ORGANIC_THRESHOLD,
                      soft_clear_organic_threshold: int = SOFT_CLEAR_ORGANIC_THRESHOLD,
                      spread_out_days: float = SPREAD_OUT_DAYS, diverse_order_cv: float = DIVERSE_ORDER_CV,
                      engaged_sessions: float = ENGAGED_SESSIONS, templated_order_cv: float = TEMPLATED_ORDER_CV,
                      burst_days: float = BURST_DAYS, fast_claim_hours: float = FAST_CLAIM_HOURS,
                      dormant_frac: float = DORMANT_FRAC) -> dict:
    """Every threshold this stage uses is exposed as an optional override, defaulting to the
    production constants above, so any tool that needs to ask "what if this one threshold were
    different" -- cost_threshold_sensitivity.py, scale-test replays, and now
    backend/adversarial_recommender/'s impact simulator -- calls this exact function with one
    parameter changed, rather than reimplementing the decision logic. Never changes behavior when
    called with no overrides (verified byte-identical against the frozen dataset's stored output
    every time a new parameter was added here)."""
    f = features
    cv = f["order_value_cv"]
    dormant = f["claim_then_dormant_frac"]
    claim_v = f["bonus_claim_velocity_hours"]

    is_spread_out = f["signup_span_days"] >= spread_out_days
    is_diverse_orders = cv is not None and cv >= diverse_order_cv
    has_engagement = f["post_signup_engagement"] >= engaged_sessions
    organic_score = int(is_spread_out) + int(is_diverse_orders) + int(has_engagement)

    is_burst = f["signup_span_days"] <= burst_days
    is_templated = cv is not None and cv < templated_order_cv
    is_dormant = dormant is not None and dormant >= dormant_frac
    is_fast_claim = claim_v is not None and claim_v <= fast_claim_hours
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
    if organic_score >= soft_clear_organic_threshold:
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


# Name -> (current production constant, min, max, step) for every threshold this stage exposes.
# Single source of truth for backend/adversarial_recommender/recommendation_drafter.py -- a
# recommendation can only ever propose changing one of these to a value in its stated range.
TUNABLE_PARAMETERS = {
    "spread_out_days": (SPREAD_OUT_DAYS, 7, 45, 1),
    "diverse_order_cv": (DIVERSE_ORDER_CV, 0.10, 0.50, 0.01),
    "engaged_sessions": (ENGAGED_SESSIONS, 0.5, 4.0, 0.1),
    "templated_order_cv": (TEMPLATED_ORDER_CV, 0.05, 0.30, 0.01),
    "burst_days": (BURST_DAYS, 2, 14, 1),
    "fast_claim_hours": (FAST_CLAIM_HOURS, 4, 48, 1),
    "dormant_frac": (DORMANT_FRAC, 0.1, 0.8, 0.05),
    "device_clear_organic_threshold": (DEVICE_CLEAR_ORGANIC_THRESHOLD, 1, 3, 1),
    "soft_clear_organic_threshold": (SOFT_CLEAR_ORGANIC_THRESHOLD, 1, 3, 1),
    "soft_flag_suspicion_threshold": (SOFT_FLAG_SUSPICION_THRESHOLD, 1, 4, 1),
}


def _verdict(flag, organic_score, suspicion_score, reason):
    return {
        "flagged": flag,
        "organic_score": organic_score,
        "suspicion_score": suspicion_score,
        "reason": reason,
    }
