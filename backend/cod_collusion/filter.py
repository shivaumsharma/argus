"""Stage 5 for the COD loss type -- same "actively look for evidence of legitimacy"
discipline as the referral-abuse filter, different thresholds for a different
behavior: a shared address alone (a real hostel, a real family) is common and
legitimate; what's not legitimate is a shared address or phone block paired
with an abnormally high COD refusal rate."""

# Real-world COD return/refusal rate is 20-40% (India's average COD Return-to-Origin
# rate: GoKwik 2026 data, 20-25% average rising to 28-35%/30-50% for less-optimized
# operations; Razorpay's own published Cash-on-Delivery guide -- both verified via web
# search, not assumed), matching backend/cod_collusion/generate_data.py's
# ORGANIC_COD_REFUSAL_RATE. NORMAL_REFUSAL_RATE sits comfortably above that real ceiling
# so a genuinely organic multi-tenant address still clears even at the top of its real
# range, while staying well below the collusion ring's 70-100% floor.
NORMAL_REFUSAL_RATE = 0.45
SUSPICIOUS_REFUSAL_RATE = 0.60
SUSPICIOUS_COD_FRACTION = 0.75


def evaluate_cluster(features: dict) -> dict:
    f = features
    refusal = f["refusal_rate"]
    cod_frac = f["cod_fraction"]

    if refusal is None:
        return _verdict(False, "No COD orders in this cluster to evaluate a refusal rate from.")

    if f["shared_address"]:
        if refusal <= NORMAL_REFUSAL_RATE:
            return _verdict(False, f"Shared delivery address, but refusal rate ({refusal:.0%}) is within the "
                                    "normal range for organic customers -- looks like a real multi-tenant address.")
        if refusal >= SUSPICIOUS_REFUSAL_RATE:
            return _verdict(True, f"Shared delivery address with a {refusal:.0%} COD refusal rate -- "
                                   "far above what organic customers refuse; consistent with a reshipping/collusion drop point.")
        return _verdict(refusal >= NORMAL_REFUSAL_RATE and cod_frac >= SUSPICIOUS_COD_FRACTION,
                         f"Shared address, borderline refusal rate ({refusal:.0%}); "
                         f"{'also nearly all-COD ordering tips this to suspicious' if cod_frac >= SUSPICIOUS_COD_FRACTION else 'mixed payment methods keep this ambiguous, left unflagged by default'}.")

    # soft-signal only (phone-prefix block, no shared address)
    if refusal >= SUSPICIOUS_REFUSAL_RATE and cod_frac >= SUSPICIOUS_COD_FRACTION:
        return _verdict(True, f"No shared address, but a shared phone-number block with {refusal:.0%} refusal "
                               f"rate and {cod_frac:.0%} COD-only ordering -- classic burner-SIM collusion pattern.")
    return _verdict(False, "Soft-signal cluster (phone block only) without a high enough refusal rate or "
                            "COD concentration to clear the bar -- left unflagged by default.")


def _verdict(flag, reason):
    return {"flagged": flag, "reason": reason}
