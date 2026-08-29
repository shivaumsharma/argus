"""
Stage 3 -- Recommendation Drafter.

Turns one characterized gap into exactly one specific, bounded, reviewable
change: "move <parameter> from <current> to <proposed>." Never a vague
"improve detection" suggestion -- every recommendation names one constant
in backend/pipeline/confounder_filter.py's TUNABLE_PARAMETERS and one new
value, clamped to that parameter's defined (min, max, step) range so a
draft can never propose something outside the space Stage 4 knows how to
simulate or a human could sanely review.
"""

from ..pipeline.confounder_filter import TUNABLE_PARAMETERS


def draft(gap: dict, attack_id: str) -> dict | None:
    """gap: the 'gap' dict from gap_characterizer.characterize() (None if no
    single-parameter fix exists -- draft() returns None in that case too,
    since there is nothing bounded and single-change to propose)."""
    if gap is None:
        return None

    param = gap["gap_parameter"]
    current, lo, hi, step = TUNABLE_PARAMETERS[param]

    # Move just past the attack's actual value, on the side that would flip this
    # specific check from "organic" to "not," clamped to the defined safe range.
    raw_proposed = gap["value"] + step
    proposed = min(max(round(raw_proposed / step) * step, lo), hi)
    if round(proposed, 6) == round(current, 6):
        # already at the edge of the allowed range -- no further tightening possible
        return None

    rationale = (
        f"Attack {attack_id} evaded detection with {param.replace('_', ' ')} = {gap['value']:.3f}, "
        f"clearing the current threshold of {current} by a margin of only {gap['margin']:.3f} -- the "
        f"loosest of its passing organic checks. Raising {param} to {proposed:.3f} would put this "
        f"specific attack's value back on the suspicious side of the line while staying within the "
        f"parameter's defined safe range ({lo}-{hi})."
    )
    return {
        "gap_parameter": param, "current_value": current, "proposed_value": proposed,
        "rationale": rationale,
    }
