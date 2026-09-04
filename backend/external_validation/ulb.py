"""Label-blind transaction-risk benchmark for the ULB credit-card dataset.

This is deliberately separate from the project's entity-graph pipeline.  ULB
has no account, card, device, merchant, or other linkage key, so treating its
rows as a graph would invent evidence the dataset does not contain.  Instead
this module measures a conventional transaction scorer with a time-ordered
train/validation/holdout split.

Run (after downloading Kaggle's mlg-ulb/creditcardfraud dataset):
    python -m backend.external_validation.ulb
"""

import json
from pathlib import Path

import pandas as pd
from xgboost import XGBClassifier

from ..pipeline.data_io import PROCESSED_DIR
from .transaction_risk_common import metrics_at_threshold, threshold_at_best_validation_f1, top_k_metrics

ROOT = Path(__file__).resolve().parents[2]
DATA_PATH = ROOT / "data" / "external" / "ulb" / "creditcard.csv"
RANDOM_STATE = 42


def _split_time_ordered(frame: pd.DataFrame):
    """Keep the future wholly out of model fitting and threshold selection."""
    frame = frame.sort_values("Time", kind="stable").reset_index(drop=True)
    train_end = int(len(frame) * 0.70)
    validation_end = int(len(frame) * 0.85)
    return frame.iloc[:train_end], frame.iloc[train_end:validation_end], frame.iloc[validation_end:]


def run(verbose: bool = True) -> dict:
    if not DATA_PATH.exists():
        raise FileNotFoundError(
            f"Missing {DATA_PATH}. Download Kaggle dataset mlg-ulb/creditcardfraud first."
        )

    frame = pd.read_csv(DATA_PATH)
    expected = {"Time", "Amount", "Class", *[f"V{i}" for i in range(1, 29)]}
    missing = expected - set(frame.columns)
    if missing:
        raise ValueError(f"ULB schema is missing expected columns: {sorted(missing)}")
    if frame["Class"].nunique() != 2:
        raise ValueError("Class must contain both legitimate (0) and fraud (1) labels.")

    train, validation, holdout = _split_time_ordered(frame)
    features = [c for c in frame.columns if c != "Class"]
    y_train = train["Class"].to_numpy(dtype=int)
    y_validation = validation["Class"].to_numpy(dtype=int)
    y_holdout = holdout["Class"].to_numpy(dtype=int)

    # Class weighting is fitted from training labels only.  Unlike an accuracy
    # baseline, this makes rare confirmed fraud costly enough to learn.
    negatives = int((y_train == 0).sum())
    positives = int((y_train == 1).sum())
    model = XGBClassifier(
        n_estimators=350,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        min_child_weight=2,
        reg_lambda=1.0,
        scale_pos_weight=negatives / positives,
        objective="binary:logistic",
        eval_metric="aucpr",
        n_jobs=-1,
        random_state=RANDOM_STATE,
    )
    model.fit(train[features], y_train)

    validation_probabilities = model.predict_proba(validation[features])[:, 1]
    threshold = threshold_at_best_validation_f1(y_validation, validation_probabilities)
    holdout_probabilities = model.predict_proba(holdout[features])[:, 1]

    holdout_metrics = metrics_at_threshold(y_holdout, holdout_probabilities, threshold)
    capacity_scenarios = [43, 50, 100, 250, 500]
    report = {
        "dataset": "ULB Credit Card Fraud Detection",
        "source": "Kaggle mlg-ulb/creditcardfraud",
        "scope": "Transaction-risk scoring only; no graph or clustering claim.",
        "split": {
            "strategy": "chronological by Time; earliest 70% train, next 15% threshold selection, final 15% holdout",
            "train_rows": int(len(train)),
            "validation_rows": int(len(validation)),
            "holdout_rows": int(len(holdout)),
        },
        "model": {
            "name": "class-weighted XGBoost",
            "features": features,
            "training_fraud_rows": positives,
            "training_scale_pos_weight": round(negatives / positives, 4),
        },
        "validation": metrics_at_threshold(y_validation, validation_probabilities, threshold),
        "holdout": holdout_metrics,
        "holdout_review_capacity_scenarios": [
            top_k_metrics(y_holdout, holdout_probabilities, capacity)
            for capacity in capacity_scenarios
        ],
        "interpretation": {
            "primary_measure": "PR-AUC, because 99.8% accuracy can be achieved by predicting every transaction as legitimate.",
            "threshold_selection": "Best F1 on validation only; holdout labels were not used to select it.",
            "review_capacity_policy": "Top-k queues are evaluated at predeclared analyst capacities; ranking uses probabilities only, never holdout labels.",
            "limitation": "PCA features are anonymized and ULB has no entity/linkage fields, so this cannot validate graph clustering or ring detection.",
        },
    }
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    output = PROCESSED_DIR / "ulb_validation.json"
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")

    if verbose:
        h = report["holdout"]
        print("=== ULB transaction-risk validation ===")
        print(f"Holdout: {h['rows']:,} transactions, {h['fraud_rows']} confirmed frauds")
        print(f"PR-AUC: {h['pr_auc']:.3f} | ROC-AUC: {h['roc_auc']:.3f}")
        print(f"Threshold: {h['threshold']:.3f} | precision: {h['precision']:.1%} | recall: {h['recall']:.1%} | F1: {h['f1']:.3f}")
        print(f"Accuracy: {h['accuracy']:.2%} (context only; not a useful rare-fraud measure)")
        print(f"Alerts: {h['alerts']:,}; true positives: {h['true_positive_alerts']:,}; false positives: {h['false_positive_alerts']:,}")
        print("Review-capacity scenarios (same holdout, ranked by score):")
        for scenario in report["holdout_review_capacity_scenarios"]:
            print(f"  top {scenario['review_capacity']:,}: {scenario['true_positive_alerts']} true positives, "
                  f"{scenario['false_positive_alerts']} false positives, precision={scenario['precision']:.1%}, "
                  f"recall={scenario['recall']:.1%}")
        print(f"Written -> {output}")
    return report


if __name__ == "__main__":
    run()
