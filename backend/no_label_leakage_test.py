"""
Standing safeguard against ground-truth leakage into any detection-time
scoring or feature-computation function.

Built after a real investigation found `backend/external_validation/run.py`
(`evaluate()`) and `elliptic.py` (`_rows()` + `score()`) computing their
flagging score directly from ground-truth labels (`fraud_density`/`density`
= a cluster's fraction of labeled-fraud members) -- confirmed, precisely, to
be used as the actual flag criterion itself (`density > threshold` selects
`flagged`), not consulted afterward for reporting the way FRAUDAR's
block-finder or eval.py do. Real, already-documented, deliberate substitutes
for those specific functions (no Stage 4/5 behavioral equivalent existed for
YelpChi/Amazon/Elliptic at the time), not bugs left to fix silently -- but
finding them took multiple rounds of manual investigation each. This test
exists so the *next* accidental version of that exact bug -- ground truth
read by a function that produces a flag or feature, anywhere in the primary
detection surfaces -- fails a test immediately instead.

Scope, deliberately narrow: the functions that actually PRODUCE a flag,
score, or feature used downstream for a decision, across every detection
surface in this repo except the two known, already-documented, explicitly
EXCLUDED substitutes above:
  - `external_validation.run.evaluate` (YelpChi/Amazon `fraud_density`)
  - `external_validation.elliptic.score` and `elliptic._rows` (the same
    pattern for Elliptic's `density`)
Both stay excluded on purpose, not by oversight -- see
`docs/EXTERNAL_VALIDATION.md` for why those two are a stated, accepted gap.
Their real, label-blind replacements (`behavioral_scoring.py` for
YelpChi/Amazon, `elliptic.label_blind_classifier_check` for Elliptic) ARE in
this test's monitored list below -- that's where a future regression on
*those* fixes would actually be caught. Evaluation/reporting functions
(pipeline/eval.py, fairness_audit.py, cost_threshold_sensitivity.py,
impact_simulator.py, governance.py, compliance_report.py, confidence_calibration.py,
elliptic.structural_coverage_check) are correctly excluded too: they read
ground truth AFTER a flag already exists, to measure or compare it -- that
is not a leak, and is not this test's concern. (`structural_coverage_check`
is clean on its own terms even though the `flagged_groups` it's handed today
happen to come from the leaky `elliptic.score` -- see
`docs/EXTERNAL_VALIDATION.md` for that distinction; this test checks
functions, not which upstream data currently flows into them.)

Mechanism: `inspect.getsource()` on each named function, regex-scanned for a
list of forbidden identifiers a real leak would need to reference (the
ground-truth file paths, the label-derived variables/columns this project
already knows about, and the y_train/y_dev names reserved for a model's
*training target* -- legitimate inside a `_fit_*` function, which is why
those are NOT in this test's function list at all, only the functions that
consume already-fitted models or raw features are).

Run: python -m backend.no_label_leakage_test
"""

import inspect
import json
import re

from .adversarial_recommender.gap_characterizer import characterize
from .adversarial_recommender.recommendation_drafter import draft
from .cod_collusion.features import compute_features as cod_compute_features
from .cod_collusion.filter import evaluate_cluster as cod_evaluate_cluster
from .external_validation import elliptic as elliptic_module
from .external_validation.behavioral_scoring import evaluate_behavioral, heuristic_suspicion_score
from .fraudar_analysis import build_bipartite_graph, detect_top_k_blocks, fast_greedy_decreasing
from .llm_investigate import _fallback_investigation, build_prompt
from .pipeline.confounder_filter import evaluate_cluster as primary_evaluate_cluster
from .pipeline.data_io import PROCESSED_DIR
from .pipeline.features import compute_features as primary_compute_features

FORBIDDEN_PATTERNS = [
    r"\bground_truth\b", r"rings\.json", r"confounders\.json", r"labels\.csv",
    r"\blabel_map\b", r"\bis_fraud\b", r"\bGT_DIR\b", r"\bload_ground_truth\b",
    r"\blabels\[", r"\by_train\b", r"\by_dev\b", r"\bcluster_type\b",
]

# Second, narrower check for the trained-classifier builders (behavioral_scoring.py,
# elliptic.label_blind_classifier_check): these legitimately reference labels/label_map
# throughout -- as the supervised TARGET (y_train/y_dev) and for post-hoc reporting
# (frauds/illicit counts) -- so the blanket FORBIDDEN_PATTERNS scan above would always
# false-positive on them, the same reason `_fit_logistic_regression`/`_fit_xgboost`
# were never in the list above either. What actually matters for these functions is
# narrower and checkable: does the FEATURE matrix itself (any `X`/`X_train`/`X_dev`/
# `X_full` assignment) ever get built from something label-derived, as opposed to
# straight from the raw `features`/`features[mask]` array? Checked per-assignment-line,
# not per-function, so legitimate label/y usage elsewhere in the same function doesn't
# trigger a false alarm.
FEATURE_VAR_PATTERN = re.compile(r"^\s*X\w*\s*(,\s*\w+\s*)?=\s*(.+)$")
LABEL_ISH = re.compile(r"label|ground_truth|is_fraud|density")

FEATURE_CONSTRUCTION_CHECKS = [
    ("external_validation.behavioral_scoring.evaluate_behavioral (feature construction)", evaluate_behavioral),
    ("external_validation.elliptic.label_blind_classifier_check (feature construction)",
     elliptic_module.label_blind_classifier_check),
]

CHECKED_FUNCTIONS = [
    ("pipeline.features.compute_features (Stage 4, primary pipeline)", primary_compute_features),
    ("pipeline.confounder_filter.evaluate_cluster (Stage 5, primary pipeline)", primary_evaluate_cluster),
    ("cod_collusion.features.compute_features (COD Stage 4)", cod_compute_features),
    ("cod_collusion.filter.evaluate_cluster (COD Stage 5)", cod_evaluate_cluster),
    ("adversarial_recommender.gap_characterizer.characterize", characterize),
    ("adversarial_recommender.recommendation_drafter.draft", draft),
    ("llm_investigate.build_prompt", build_prompt),
    ("llm_investigate._fallback_investigation", _fallback_investigation),
    ("fraudar_analysis.build_bipartite_graph", build_bipartite_graph),
    ("fraudar_analysis.fast_greedy_decreasing", fast_greedy_decreasing),
    ("fraudar_analysis.detect_top_k_blocks", detect_top_k_blocks),
    ("external_validation.behavioral_scoring.heuristic_suspicion_score", heuristic_suspicion_score),
]


def _check_feature_construction(fn):
    """Line-level, not function-level: find every `X`/`X_train`/`X_dev`/`X_full`
    assignment in `fn`'s source and check whether that SPECIFIC line's right
    -hand side looks label-derived. Deliberately ignores every other line in
    the function (including ones that legitimately build `y`/`y_train` from
    labels) -- this is the narrow question "did the feature matrix itself get
    contaminated," not "does this function mention labels anywhere."""
    source = inspect.getsource(fn)
    bad_lines = []
    for line in source.splitlines():
        m = FEATURE_VAR_PATTERN.match(line)
        if m and LABEL_ISH.search(m.group(2)):
            bad_lines.append(line.strip())
    return bad_lines


def run(verbose=True):
    results = []
    violations = []
    for name, fn in CHECKED_FUNCTIONS:
        source = inspect.getsource(fn)
        hits = sorted({m.group(0) for pat in FORBIDDEN_PATTERNS for m in re.finditer(pat, source)})
        clean = len(hits) == 0
        results.append({"function": name, "clean": clean, "matched_patterns": hits})
        if not clean:
            violations.append({"function": name, "matched_patterns": hits})
        if verbose:
            print(f"  [{'CLEAN' if clean else 'LEAK DETECTED'}] {name}" + (f" -- matched: {hits}" if hits else ""))

    for name, fn in FEATURE_CONSTRUCTION_CHECKS:
        bad_lines = _check_feature_construction(fn)
        clean = len(bad_lines) == 0
        results.append({"function": name, "clean": clean, "matched_patterns": bad_lines})
        if not clean:
            violations.append({"function": name, "matched_patterns": bad_lines})
        if verbose:
            print(f"  [{'CLEAN' if clean else 'LEAK DETECTED'}] {name}" + (f" -- matched: {bad_lines}" if bad_lines else ""))

    n_total = len(CHECKED_FUNCTIONS) + len(FEATURE_CONSTRUCTION_CHECKS)
    report = {"n_checked": n_total, "n_clean": sum(1 for r in results if r["clean"]),
              "n_violations": len(violations), "violations": violations, "results": results}
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    with open(PROCESSED_DIR / "no_label_leakage_test.json", "w") as f:
        json.dump(report, f, indent=2)

    if violations:
        names = ", ".join(v["function"] for v in violations)
        raise AssertionError(f"Ground-truth leakage detected in: {names} -- see "
                              f"data/processed/no_label_leakage_test.json")
    if verbose:
        print(f"\nPASS: all {n_total} detection-time scoring/feature functions and feature-construction "
              f"sites are free of ground-truth references.")
    return report


if __name__ == "__main__":
    run()
