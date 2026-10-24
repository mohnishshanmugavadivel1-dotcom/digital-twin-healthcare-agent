import numpy as np
import pandas as pd

from glucotwin.evaluation.metrics import choose_threshold, clarke_zones, event_metrics, trajectory_metrics


def test_clarke_zones_reference_points():
    ref = np.array([100, 60, 250, 50, 300, 100])
    pred = np.array([110, 65, 50, 200, 150, 300])
    assert list(clarke_zones(ref, pred)) == ["A", "A", "E", "E", "D", "C"]


def test_perfect_forecast_metrics():
    y = np.array([100.0, 150.0, 200.0])
    m = trajectory_metrics(y, y, y - 1, y + 1)
    assert m["mae_mg_dl"] == 0 and m["rmse_mg_dl"] == 0 and m["clarke_a_pct"] == 100 and m["interval_coverage"] == 1


def test_choose_threshold_separable():
    y = np.array([0, 0, 0, 1, 1])
    p = np.array([0.1, 0.2, 0.3, 0.8, 0.9])
    t = choose_threshold(y, p)
    assert 0.3 < t <= 0.8


def test_event_metrics_lead_time_and_false_alerts():
    t0 = pd.Timestamp("2026-03-02", tz="UTC")
    ts = [t0 + pd.Timedelta(minutes=5 * i) for i in range(10)]
    frame = pd.DataFrame({
        "patient_id": "SYN-0001", "timestamp": ts,
        "y_event": [0, 0, 0, 0, 0, 0, 1, 1, 1, 1],
        "score": [0.9, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.9, 0.9, 0.9],
    })
    onset = {"SYN-0001": pd.DatetimeIndex([t0 + pd.Timedelta(minutes=50)])}
    m = event_metrics(frame, "score", 0.5, onset, patient_days=1.0)
    assert m["event_sensitivity"] == 1.0
    # first alert inside the 120-min window before onset is at t0 (the false one is also inside it)
    assert m["median_lead_time_min"] == 50.0
    assert m["false_alert_episodes_per_patient_day"] == 1.0
    assert m["sensitivity"] == 0.75
