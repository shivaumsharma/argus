"""Shared, dataset-agnostic helpers for the transaction-risk benchmarks
(ULB, IEEE-CIS). Factored out of ulb.py rather than duplicated in ieee_cis.py --
same discipline this project already applies to Stage 2/3 clustering: one
function, imported unchanged, not two copies that can drift apart.
"""

import numpy as np
from sklearn.metrics import (accuracy_score, average_precision_score, f1_score,
                             precision_recall_curve, precision_score, recall_score,
                             roc_auc_score)


def threshold_at_best_validation_f1(labels: np.ndarray, probabilities: np.ndarray) -> float:
    """Choose one operating point without looking at holdout labels."""
    precision, recall, thresholds = precision_recall_curve(labels, probabilities)
    f1 = 2 * precision[:-1] * recall[:-1] / np.maximum(precision[:-1] + recall[:-1], 1e-12)
    return float(thresholds[int(np.nanargmax(f1))])


def metrics_at_threshold(labels: np.ndarray, probabilities: np.ndarray, threshold: float) -> dict:
    predicted = (probabilities >= threshold).astype(int)
    precision = precision_score(labels, predicted, zero_division=0)
    recall = recall_score(labels, predicted, zero_division=0)
    return {
        "rows": int(len(labels)),
        "fraud_rows": int(labels.sum()),
        "fraud_rate": round(float(labels.mean()), 6),
        "pr_auc": round(float(average_precision_score(labels, probabilities)), 6),
        "roc_auc": round(float(roc_auc_score(labels, probabilities)), 6),
        "threshold": round(float(threshold), 6),
        "precision": round(float(precision), 6),
        "recall": round(float(recall), 6),
        "f1": round(float(f1_score(labels, predicted, zero_division=0)), 6),
        # Retained only for completeness. At this class imbalance it is not a
        # useful model-selection measure; the report says so explicitly.
        "accuracy": round(float(accuracy_score(labels, predicted)), 6),
        "alerts": int(predicted.sum()),
        "true_positive_alerts": int(((predicted == 1) & (labels == 1)).sum()),
        "false_positive_alerts": int(((predicted == 1) & (labels == 0)).sum()),
    }


def top_k_metrics(labels: np.ndarray, probabilities: np.ndarray, k: int) -> dict:
    """Measure a review-capacity policy without using labels to choose the rows.

    The analyst chooses ``k`` in advance (for example, 500 reviews per batch);
    the model supplies the k highest-risk rows. This differs from the F1
    threshold, which chooses an operating point from validation labels.
    """
    k = min(k, len(labels))
    ranked = np.argsort(-probabilities, kind="stable")
    predicted = np.zeros(len(labels), dtype=int)
    predicted[ranked[:k]] = 1
    precision = precision_score(labels, predicted, zero_division=0)
    recall = recall_score(labels, predicted, zero_division=0)
    return {
        "review_capacity": int(k),
        "minimum_score_in_queue": round(float(probabilities[ranked[k - 1]]), 6),
        "true_positive_alerts": int(((predicted == 1) & (labels == 1)).sum()),
        "false_positive_alerts": int(((predicted == 1) & (labels == 0)).sum()),
        "precision": round(float(precision), 6),
        "recall": round(float(recall), 6),
        "f1": round(float(f1_score(labels, predicted, zero_division=0)), 6),
    }
