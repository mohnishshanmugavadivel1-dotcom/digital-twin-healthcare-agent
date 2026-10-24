"""Evaluation metrics for trajectory forecasts and excursion alerts."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

from glucotwin.config import EVENT_HORIZON_MIN


def clarke_zones(ref: np.ndarray, pred: np.ndarray) -> np.ndarray:
    """Clarke error grid zone (A-E) per point, using the standard published boundaries (mg/dL)."""
    ref = np.asarray(ref, dtype=float)
    pred = np.asarray(pred, dtype=float)
    zones = np.full(ref.shape, "B", dtype="<U1")
    a = ((ref <= 70) & (pred <= 70)) | ((pred <= 1.2 * ref) & (pred >= 0.8 * ref))
    e = ((ref >= 180) & (pred <= 70)) | ((ref <= 70) & (pred >= 180))
    c = (((ref >= 70) & (ref <= 290)) & (pred >= ref + 110)) | (
        ((ref >= 130) & (ref <= 180)) & (pred <= (7 / 5) * ref - 182)
    )
    d = ((ref >= 240) & ((pred >= 70) & (pred <= 180))) | ((ref <= 175 / 3) & (pred <= 180) & (pred >= 70)) | (
        ((ref >= 175 / 3) & (ref <= 70)) & (pred >= (6 / 5) * ref)
    )
    # precedence: A, E, C, D, else B
    zones[d] = "D"
    zones[c] = "C"
    zones[e] = "E"
    zones[a] = "A"
    return zones


def trajectory_metrics(ref: np.ndarray, pred: np.ndarray, lower=None, upper=None) -> dict:
    ref = np.asarray(ref, dtype=float)
    pred = np.asarray(pred, dtype=float)
    err = pred - ref
    zones = clarke_zones(ref, pred)
    out = {
        "n": int(ref.size),
        "mae_mg_dl": float(np.mean(np.abs(err))),
        "rmse_mg_dl": float(np.sqrt(np.mean(err**2))),
        "mard_percent": float(100 * np.mean(np.abs(err) / ref)),
        "clarke_a_pct": float(100 * np.mean(zones == "A")),
        "clarke_ab_pct": float(100 * np.mean((zones == "A") | (zones == "B"))),
        "interval_coverage": None,
    }
    if lower is not None and upper is not None:
        out["interval_coverage"] = float(np.mean((ref >= lower) & (ref <= upper)))
    return out


def choose_threshold(y: np.ndarray, p: np.ndarray) -> float:
    """Threshold maximising F1 on the given (validation) data."""
    best_t, best_f1 = 0.5, -1.0
    for t in np.linspace(0.05, 0.95, 91):
        pred = p >= t
        tp = np.sum(pred & (y == 1))
        fp = np.sum(pred & (y == 0))
        fn = np.sum(~pred & (y == 1))
        f1 = 2 * tp / max(2 * tp + fp + fn, 1)
        if f1 > best_f1:
            best_t, best_f1 = round(float(t), 2), f1
    return best_t


def event_metrics(
    frame: pd.DataFrame,
    score_col: str,
    threshold: float | None,
    onsets: dict[str, pd.DatetimeIndex],
    patient_days: float,
    is_probability: bool = True,
) -> dict:
    """Point-level and event-level metrics.

    frame: rows with columns patient_id, timestamp, y_event (0/1, NaN rows dropped), score_col.
    onsets: excursion onset times per patient (from the observed CGM).
    """
    df = frame.dropna(subset=["y_event"])
    y = df["y_event"].to_numpy().astype(int)
    s = df[score_col].to_numpy(dtype=float)
    two_classes = len(np.unique(y)) == 2
    out = {
        "n": int(len(df)),
        "prevalence": float(y.mean()) if len(y) else 0.0,
        "auroc": float(roc_auc_score(y, s)) if two_classes else None,
        "auprc": float(average_precision_score(y, s)) if two_classes else None,
        "brier": float(brier_score_loss(y, np.clip(s, 0, 1))) if (two_classes and is_probability) else None,
        "threshold": threshold,
        "sensitivity": None, "specificity": None, "ppv": None,
        "event_sensitivity": None, "median_lead_time_min": None, "false_alert_episodes_per_patient_day": None,
    }
    if threshold is None:
        return out
    alert = s >= threshold
    tp = np.sum(alert & (y == 1))
    fp = np.sum(alert & (y == 0))
    fn = np.sum(~alert & (y == 1))
    tn = np.sum(~alert & (y == 0))
    out["sensitivity"] = float(tp / max(tp + fn, 1))
    out["specificity"] = float(tn / max(tn + fp, 1))
    out["ppv"] = float(tp / max(tp + fp, 1))

    detected, leads, false_eps = 0, [], 0
    total_onsets = 0
    horizon = pd.Timedelta(minutes=EVENT_HORIZON_MIN)
    for pid, sub in df.assign(alert=alert).groupby("patient_id"):
        sub = sub.sort_values("timestamp")
        alert_times = pd.DatetimeIndex(sub.loc[sub["alert"], "timestamp"])
        for onset in onsets.get(pid, pd.DatetimeIndex([])):
            in_window = alert_times[(alert_times >= onset - horizon) & (alert_times < onset)]
            # only count onsets that had at least one eligible prediction point before them
            eligible = sub[(sub["timestamp"] >= onset - horizon) & (sub["timestamp"] < onset)]
            if eligible.empty:
                continue
            total_onsets += 1
            if len(in_window):
                detected += 1
                leads.append((onset - in_window.min()).total_seconds() / 60)
        # false alert episodes: consecutive alert rows (<= 10 min apart) none of which is a true positive
        al = sub[sub["alert"]]
        if al.empty:
            continue
        new_ep = al["timestamp"].diff().gt(pd.Timedelta(minutes=10)).cumsum()
        for _, ep in al.groupby(new_ep):
            if (ep["y_event"] == 0).all():
                false_eps += 1
    out["event_sensitivity"] = float(detected / total_onsets) if total_onsets else None
    out["median_lead_time_min"] = float(np.median(leads)) if leads else None
    out["false_alert_episodes_per_patient_day"] = float(false_eps / patient_days) if patient_days else None
    return out
