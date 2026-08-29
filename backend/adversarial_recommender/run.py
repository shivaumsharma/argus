"""
Orchestrates one round: generate an attack, characterize any gap it exposes,
draft a bounded recommendation if a single-parameter fix exists, simulate
its impact (both sides, always), and queue it for human review. Never
applies anything itself.

Run: python -m backend.adversarial_recommender.run [--force]
"""

import argparse

from .. import db
from . import attack_generator, cadence, gap_characterizer, impact_simulator, recommendation_drafter
from .attack_generator import ORGANIC_KNOBS
from ..pipeline.confounder_filter import TUNABLE_PARAMETERS


def _prior_targets(round_number: int) -> dict:
    """What should round N target? The most recent PRIOR round's drafted
    recommendation, if one exists (adapt to the last proposed fix). If the
    most recent prior round found no single-parameter gap, probe all three
    organic knobs at their current production thresholds instead -- a
    harder, more efficient adversary than round 1's comfortably-organic one."""
    if round_number <= 1:
        return {}
    recs = [r for r in db.get_all_recommendations() if r["round_number"] == round_number - 1]
    if recs:
        r = recs[0]
        return {r["gap_parameter"]: float(r["current_value"])}
    return {p: TUNABLE_PARAMETERS[p][0] for p in ORGANIC_KNOBS}


def run_round(force: bool = False, verbose: bool = True) -> dict:
    allowed, reason = cadence.can_run(force=force)
    if not allowed:
        if verbose:
            print(f"Round blocked by cadence gate: {reason}")
        return {"ran": False, "reason": reason}

    round_number = cadence.next_round_number()
    if verbose:
        print(f"=== Round {round_number} ({reason}) ===")

    if round_number == 1:
        attack = attack_generator.generate_round1()
    else:
        targets = _prior_targets(round_number)
        attack = attack_generator.generate_variant(round_number, seed=round_number * 1013, targets=targets)

    if verbose:
        print(f"Attack: {attack['attack_id']} -- {attack['description']}")

    characterization = gap_characterizer.characterize(attack, verbose=verbose)
    result = {"ran": True, "round_number": round_number, "attack_id": attack["attack_id"],
              "characterization_reason": characterization["reason"], "recommendation_id": None}

    if not characterization["evaded"]:
        if verbose:
            print("Attack was caught by the current pipeline -- no gap to characterize this round.")
    elif characterization["gap"] is None:
        if verbose:
            print("Attack evaded detection but no single-parameter fix exists -- nothing bounded to "
                  "recommend this round (see gap_characterizer.py's docstring).")
    else:
        draft = recommendation_drafter.draft(characterization["gap"], attack["attack_id"])
        if draft is None:
            if verbose:
                print("Gap found but the proposed fix would fall outside the parameter's safe range -- "
                      "no recommendation drafted.")
        else:
            sim = impact_simulator.simulate(draft["gap_parameter"], draft["proposed_value"],
                                            attack_features=characterization["features"])
            if verbose:
                print(f"Simulated impact (full 80-ring/40-confounder set): {impact_simulator.format_summary(sim)}")
                if sim["attack_caught_after_fix"]:
                    print(f"  This fix WOULD flag the attack that motivated it.")
                else:
                    print(f"  WARNING: this fix does NOT actually flag the attack that motivated it -- it "
                          f"only removes the attack from Stage 5's 'actively cleared as organic' bucket; "
                          f"suspicion_score still falls short of the flag threshold, so the attack lands in "
                          f"the conservative default-no-flag middle ground instead. A real, bounded, fully "
                          f"simulated recommendation that still doesn't close the gap it was drafted for -- "
                          f"shown plainly, not hidden, exactly what Stage 4 is for.")
            rec_id = db.insert_recommendation({
                "round_number": round_number, "attack_id": attack["attack_id"],
                "attack_description": attack["description"], "attack_members": attack["members"],
                "gap_parameter": draft["gap_parameter"], "current_value": draft["current_value"],
                "proposed_value": draft["proposed_value"], "rationale": draft["rationale"],
                "sim_rings_caught_before": sim["rings_caught_before"],
                "sim_rings_caught_after": sim["rings_caught_after"],
                "sim_confounder_fp_before": sim["confounder_fp_before"],
                "sim_confounder_fp_after": sim["confounder_fp_after"],
                "sim_report": sim,
            })
            result["recommendation_id"] = rec_id
            if verbose:
                print(f"Recommendation #{rec_id} queued for review.")

    cadence.record_round(round_number)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="bypass the cadence gate for a manual trigger")
    args = parser.parse_args()
    run_round(force=args.force)
