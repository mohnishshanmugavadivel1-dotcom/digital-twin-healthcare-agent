import numpy as np
import pandas as pd

from glucotwin.labels import event_labels, excursion_onsets, to_grid, trajectory_targets

T0 = pd.Timestamp("2026-03-02 00:00", tz="UTC")


def grid(values):
    idx = pd.date_range(T0, periods=len(values), freq="5min")
    return pd.Series([np.nan if v is None else v for v in values], index=idx, dtype=float)


def test_onset_requires_three_consecutive_readings():
    g = grid([150, 190, 190, 150, 190, 190, 190, 190])
    assert list(excursion_onsets(g)) == [T0 + pd.Timedelta(minutes=20)]


def test_missing_reading_breaks_run():
    g = grid([150, 190, 190, None, 190, 150])
    assert len(excursion_onsets(g)) == 0


def test_threshold_is_strict():
    g = grid([180, 180, 180, 180])
    assert len(excursion_onsets(g)) == 0


def test_event_window_boundaries():
    # onset at index 25 (125 min). Horizon 120 min = 24 steps.
    vals = [120] * 25 + [200, 200, 200] + [120] * 30
    lab = event_labels(grid(vals))
    assert lab.iloc[1] == 1.0  # onset at +120 min -> inside (t, t+120]
    assert lab.iloc[0] == 0.0  # onset at +125 min -> outside
    assert np.isnan(lab.iloc[25])  # reading above threshold -> not eligible
    assert lab.iloc[24] == 1.0  # onset 5 min ahead


def test_unknown_when_future_unobserved():
    vals = [120] * 10 + [None] * 30
    lab = event_labels(grid(vals))
    assert np.isnan(lab.iloc[9])  # no future data: label unknown, not 0


def test_end_of_record_is_unknown_not_negative():
    vals = [120] * 30
    lab = event_labels(grid(vals))
    assert np.isnan(lab.iloc[-1])


def test_trajectory_targets_look_forward():
    g = grid(list(range(100, 160)))
    y = trajectory_targets(g)
    assert y["y_glucose_30"].iloc[0] == 106
    assert y["y_glucose_120"].iloc[0] == 124
    assert np.isnan(y["y_glucose_30"].iloc[-1])


def test_to_grid_snaps_and_dedupes():
    s = pd.Series([100.0, 101.0, 110.0], index=pd.DatetimeIndex([T0, T0 + pd.Timedelta(seconds=40),
                                                                   T0 + pd.Timedelta(minutes=15)]))
    g = to_grid(s)
    assert len(g) == 4 and g.iloc[0] == 101.0 and np.isnan(g.iloc[1])
