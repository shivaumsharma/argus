"""
Stage 4 -- Impact Simulation. Non-negotiable: never skipped, never simplified
to report only one side. Every recommendation this module scores gets BOTH
numbers together -- how many more attacks it would catch, and what it does
to the false-positive rate against all 40 planted confounders -- or it isn't
returned at all. A recommendation missing either number is a bug, not an
edge case; see run.py, which refuses to queue anything this module didn't
fully score.

Reuses the exact replay pattern already proven in
backend/cost_threshold_sensitivity.py: call the real, unmodified
evaluate_cluster() against the already-computed Stage 4 features sitting in
the DB, with one parameter overridden. No pipeline rerun, no data
regeneration for this part -- pure re-analysis of numbers already produced,
against the full 80-ring/40-confounder set (this is decision-support
simulation, not the frozen holdout claim, so using the full set here is
correct, not a violation of the holdout discipline -- see governance.py for
where a genuinely fresh, never-tuned-against seed is used before anything
is treated as validated).
"""

from .. import db
from ..pipeline.confounder_filter import evaluate_cluster
from ..pipeline.eval import best_match
from ..reporting import load_ground_truth


def simulate(gap_parameter: str, proposed_value, attack_features: dict = None) -> dict:
    rings, confounders = load_ground_truth()
    all_clusters = db.get_all_clusters()

    def flagged_with(override_value):
        overrides = {gap_parameter: override_value} if override_value is not None else {}
        return [c for c in all_clusters if evaluate_cluster(c["features"], **overrides)["flagged"]]

    flagged_before = flagged_with(None)
    flagged_after = flagged_with(proposed_value)

    rings_before = sum(1 for r in rings.values() if best_match(set(r["members"]), flagged_before))
    rings_after = sum(1 for r in rings.values() if best_match(set(r["members"]), flagged_after))
    conf_before = sum(1 for c in confounders.values() if best_match(set(c["members"]), flagged_before))
    conf_after = sum(1 for c in confounders.values() if best_match(set(c["members"]), flagged_after))

    attack_caught_after = None
    if attack_features is not None:
        attack_caught_after = evaluate_cluster(attack_features, **{gap_parameter: proposed_value})["flagged"]

    report = {
        "gap_parameter": gap_parameter, "proposed_value": proposed_value,
        "rings_total": len(rings), "confounders_total": len(confounders),
        "rings_caught_before": rings_before, "rings_caught_after": rings_after,
        "rings_delta": rings_after - rings_before,
        "confounder_fp_before": conf_before, "confounder_fp_after": conf_after,
        "confounder_fp_delta": conf_after - conf_before,
        "attack_caught_after_fix": attack_caught_after,
    }
    return report


def format_summary(report: dict) -> str:
    return (
        f"{report['gap_parameter']} -> {report['proposed_value']}: "
        f"rings caught {report['rings_caught_before']}->{report['rings_caught_after']}/{report['rings_total']} "
        f"({report['rings_delta']:+d}), confounder FPs {report['confounder_fp_before']}->"
        f"{report['confounder_fp_after']}/{report['confounders_total']} ({report['confounder_fp_delta']:+d})"
    )
