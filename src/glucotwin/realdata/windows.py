"""Forecast windows from a cleaned, segmented CGM series (real timestamps; no resampling, no interpolation).

An anchor is a recorded reading at time t. Its inputs are the recorded readings nearest to t - L (L in ``lags_min``)
and its targets the recorded readings nearest to t + h (h in ``horizons_min``), each accepted only if it lies within
``tolerance_min`` of the nominal time AND in the same gap-free segment. Inputs use only readings at or before t.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

FEATURES = ["g0", "delta_15", "delta_30", "delta_60", "accel_15", "mean_60", "std_60", "tod_sin", "tod_cos"]


def _match(t: np.ndarray, want: np.ndarray, tol: float) -> np.ndarray:
    """Index of the reading nearest each wanted time within tol (minutes), else -1. ``t`` sorted ascending."""
    idx = np.searchsorted(t, want)
    best = np.full(len(want), -1)
    best_d = np.full(len(want), np.inf)
    for cand in (idx - 1, idx):
        ok = (cand >= 0) & (cand < len(t))
        d = np.full(len(want), np.inf)
        d[ok] = np.abs(t[cand[ok]] - want[ok])
        better = ok & (d < best_d) & (d <= tol)
        best[better], best_d[better] = cand[better], d[better]
    return best


def build_windows(series: pd.DataFrame, lags_min: list[int], horizons_min: list[int], tol: float) -> pd.DataFrame:
    rows = []
    for (pid, sid, seg), s in series.groupby(["patient_id", "session_id", "segment"], sort=True):
        s = s.sort_values("timestamp")
        ts = s["timestamp"].to_numpy().astype("datetime64[ns]")
        t = ts.astype(np.int64) / 6e10
        g = s["glucose"].to_numpy(dtype=float)
        w = pd.DataFrame({"patient_id": pid, "session_id": sid, "segment": seg, "anchor_time": ts, "g0": g})
        for lag in lags_min:
            j = _match(t, t - lag, tol)
            j[j >= np.arange(len(t))] = -1  # inputs strictly before the anchor (lag > tol guarantees it anyway)
            w[f"g_m{lag}"] = np.where(j >= 0, g[np.maximum(j, 0)], np.nan)
        for h in horizons_min:
            j = _match(t, t + h, tol)
            j[j <= np.arange(len(t))] = -1
            w[f"y_{h}"] = np.where(j >= 0, g[np.maximum(j, 0)], np.nan)
            w[f"offset_{h}"] = np.where(j >= 0, t[np.maximum(j, 0)] - t - h, np.nan)
        rows.append(w)
    if not rows:
        return pd.DataFrame()
    return pd.concat(rows, ignore_index=True)


def add_features(w: pd.DataFrame) -> pd.DataFrame:
    """CGM-only features (requires g_m15, g_m30, g_m45, g_m60). Rows lacking any lag get NaN features."""
    f = w.copy()
    f["delta_15"] = f["g0"] - f["g_m15"]
    f["delta_30"] = f["g0"] - f["g_m30"]
    f["delta_60"] = f["g0"] - f["g_m60"]
    f["accel_15"] = (f["g0"] - f["g_m15"]) - (f["g_m15"] - f["g_m30"])
    last5 = f[["g0", "g_m15", "g_m30", "g_m45", "g_m60"]]
    f["mean_60"] = last5.mean(axis=1, skipna=False)
    f["std_60"] = last5.std(axis=1, skipna=False, ddof=1)
    at = pd.DatetimeIndex(f["anchor_time"])  # wall-clock local time as recorded
    minute = at.hour * 60 + at.minute
    f["tod_sin"] = np.sin(2 * np.pi * minute / 1440)
    f["tod_cos"] = np.cos(2 * np.pi * minute / 1440)
    f["has_inputs"] = f[FEATURES].notna().all(axis=1)
    return f
