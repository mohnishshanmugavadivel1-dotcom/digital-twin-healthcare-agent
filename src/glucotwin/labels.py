"""Target definitions (frozen in contract v0.1, see config.py).

All functions operate on a CGM series reindexed to the regular 5-minute grid
(missing readings = NaN). Labels look strictly into the future (t, t+H];
features (features.py) look strictly into the past [.., t]. Tests in
``tests/test_labels.py`` and ``tests/test_leakage.py`` enforce this.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from glucotwin.config import (
    CGM_INTERVAL_MIN,
    EVENT_HORIZON_MIN,
    EXCURSION_MIN_READINGS,
    FORECAST_HORIZONS_MIN,
    HYPER_THRESHOLD_MG_DL,
    LABEL_MIN_FUTURE_COVERAGE,
)

EVENT_DEFINITION = (
    f"Onset of a hyperglycaemic excursion (>= {EXCURSION_MIN_READINGS} consecutive CGM readings "
    f"> {HYPER_THRESHOLD_MG_DL:.0f} mg/dL, i.e. >= 15 min) within the next {EVENT_HORIZON_MIN} min, "
    f"predicted at times when the latest reading is <= {HYPER_THRESHOLD_MG_DL:.0f} mg/dL."
)


def to_grid(cgm: pd.Series) -> pd.Series:
    """Snap a timestamp-indexed CGM series onto a regular 5-min grid (NaN for missing)."""
    if cgm.empty:
        return cgm.astype(float)
    s = cgm.copy()
    s.index = s.index.round(f"{CGM_INTERVAL_MIN}min")
    s = s[~s.index.duplicated(keep="last")].sort_index()
    grid = pd.date_range(s.index[0], s.index[-1], freq=f"{CGM_INTERVAL_MIN}min")
    return s.reindex(grid).astype(float)


def excursion_onsets(grid: pd.Series) -> pd.DatetimeIndex:
    """Timestamps of the first reading of every run of >= N consecutive readings above threshold.

    A missing reading breaks a run (conservative: unobserved excursions are not invented).
    """
    above = (grid > HYPER_THRESHOLD_MG_DL).to_numpy()
    onsets = []
    run = 0
    for i, flag in enumerate(above):
        run = run + 1 if flag else 0
        if run == EXCURSION_MIN_READINGS:
            onsets.append(grid.index[i - EXCURSION_MIN_READINGS + 1])
    return pd.DatetimeIndex(onsets)


def event_labels(grid: pd.Series, at: pd.DatetimeIndex | None = None) -> pd.Series:
    """1 if an excursion onset falls in (t, t + horizon]; 0 if not; NaN if not eligible / unknown.

    Eligible: a reading exists at t and it is <= threshold. Unknown: no onset found and
    future-window coverage below LABEL_MIN_FUTURE_COVERAGE (includes end of record).
    """
    at = grid.index if at is None else at
    steps = EVENT_HORIZON_MIN // CGM_INTERVAL_MIN
    onset_flag = pd.Series(0.0, index=grid.index)
    onset_flag.loc[onset_flag.index.intersection(excursion_onsets(grid))] = 1.0
    vals = onset_flag.to_numpy()
    present = (~grid.isna()).to_numpy().astype(float)
    n = len(grid)
    # forward-looking sums over (i, i+steps]
    csum_on = np.concatenate([[0.0], np.cumsum(vals)])
    csum_pr = np.concatenate([[0.0], np.cumsum(present)])
    idx = np.arange(n)
    hi = np.minimum(idx + steps, n - 1)
    future_onsets = csum_on[hi + 1] - csum_on[idx + 1]
    future_cov = (csum_pr[hi + 1] - csum_pr[idx + 1]) / steps
    lab = np.where(future_onsets > 0, 1.0, np.where(future_cov >= LABEL_MIN_FUTURE_COVERAGE, 0.0, np.nan))
    g = grid.to_numpy()
    eligible = ~np.isnan(g) & (g <= HYPER_THRESHOLD_MG_DL)
    lab = np.where(eligible, lab, np.nan)
    out = pd.Series(lab, index=grid.index, name="y_event")
    return out.reindex(at)


def trajectory_targets(grid: pd.Series, at: pd.DatetimeIndex | None = None) -> pd.DataFrame:
    """Observed CGM value at t + h for every forecast horizon h (NaN when missing)."""
    at = grid.index if at is None else at
    cols = {}
    for h in FORECAST_HORIZONS_MIN:
        shifted = grid.shift(-(h // CGM_INTERVAL_MIN))
        cols[f"y_glucose_{h}"] = shifted
    return pd.DataFrame(cols).reindex(at)
