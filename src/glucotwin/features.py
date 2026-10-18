"""Leakage-safe feature engineering shared by offline training and the online twin.

Every feature at time t is computed only from observations with timestamp <= t
(and EHR fields recorded before the monitoring period). The online engine calls
exactly the same ``build_feature_frame`` on its history and takes the last row,
so training/serving skew is impossible by construction; ``tests/test_leakage.py``
additionally verifies that truncating the future never changes past features.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from glucotwin.config import CGM_INTERVAL_MIN, HYPER_THRESHOLD_MG_DL
from glucotwin.contracts import PatientRecord
from glucotwin.labels import to_grid

COB_DURATION_MIN = 180.0  # carbs-on-board linear decay window (assumption, documented)
MEAL_RESPONSE_WINDOW_MIN = 120
MIN_MEAL_CARBS_FOR_LEARNING = 10.0
CARB_SENS_SHRINKAGE_K = 3.0  # pseudo-meals of prior weight

# Human-readable labels for the dashboard's explanation panel.
FEATURE_LABELS: dict[str, str] = {
    "glucose": "Current glucose",
    "delta_15": "Change over last 15 min",
    "delta_30": "Change over last 30 min",
    "delta_60": "Change over last 60 min",
    "accel_15": "Acceleration (15-min)",
    "mean_60": "Mean glucose, last 1 h",
    "std_60": "Variability, last 1 h",
    "max_180": "Max glucose, last 3 h",
    "min_180": "Min glucose, last 3 h",
    "mean_24h": "Mean glucose, last 24 h",
    "tar_24h": "Time above 180, last 24 h",
    "carbs_30": "Carbs logged, last 30 min",
    "carbs_60": "Carbs logged, last 1 h",
    "carbs_120": "Carbs logged, last 2 h",
    "carbs_on_board": "Carbs on board (est.)",
    "minutes_since_meal": "Minutes since last logged meal",
    "expected_meal_rise": "Personal expected meal rise",
    "carb_sensitivity": "Personal carb sensitivity",
    "steps_30": "Steps, last 30 min",
    "steps_60": "Steps, last 1 h",
    "hr_rel_30": "Heart rate vs personal baseline",
    "tod_sin": "Time of day (sin)",
    "tod_cos": "Time of day (cos)",
    "age_years": "Age",
    "bmi": "BMI",
    "hba1c_percent": "HbA1c",
    "fasting_glucose_mg_dl": "Fasting plasma glucose",
    "diabetes_duration_years": "Diabetes duration",
    "egfr": "eGFR",
    "med_sulfonylurea": "On sulfonylurea",
    "med_basal_insulin": "On basal insulin",
    "med_biguanide": "On metformin",
    "med_dpp4_inhibitor": "On DPP-4 inhibitor",
}
FEATURE_NAMES: list[str] = list(FEATURE_LABELS)

# Explanation groups. Individual glucose features are strongly collinear, so per-feature
# logistic-regression terms can flip sign and mislead; contributions are therefore summed
# within clinically meaningful groups. (group id, label, representative feature shown as value)
FEATURE_GROUPS: list[tuple[str, str, str | None, list[str]]] = [
    ("glucose_level", "Recent glucose level", "glucose",
     ["glucose", "mean_60", "std_60", "max_180", "min_180"]),
    ("glucose_trend", "Glucose trend (30 min change)", "delta_30", ["delta_15", "delta_30", "delta_60", "accel_15"]),
    ("meals", "Recent meals / carbs on board", "carbs_on_board",
     ["carbs_30", "carbs_60", "carbs_120", "carbs_on_board", "minutes_since_meal", "expected_meal_rise",
      "carb_sensitivity"]),
    ("activity", "Physical activity and heart rate", "steps_30", ["steps_30", "steps_60", "hr_rel_30"]),
    ("history_24h", "Glucose control, last 24 h", "tar_24h", ["mean_24h", "tar_24h"]),
    ("time_of_day", "Time of day", None, ["tod_sin", "tod_cos"]),
    ("record", "Health record (HbA1c, medication, ...)", "hba1c_percent",
     ["age_years", "bmi", "hba1c_percent", "fasting_glucose_mg_dl", "diabetes_duration_years", "egfr",
      "med_sulfonylurea", "med_basal_insulin", "med_biguanide", "med_dpp4_inhibitor"]),
]
EHR_FEATURES = [
    "age_years", "bmi", "hba1c_percent", "fasting_glucose_mg_dl", "diabetes_duration_years", "egfr",
    "med_sulfonylurea", "med_basal_insulin", "med_biguanide", "med_dpp4_inhibitor",
]


def carb_sensitivity_prior(record: PatientRecord) -> float:
    """EHR-derived prior for glucose rise per gram of carbohydrate (mg/dL per g).

    Heuristic: higher HbA1c and fasting glucose -> larger post-meal rise. Constants were
    set from the synthetic *training* split only (see docs/ML_PLAN.md) and are an
    assumption, not a clinical fact.
    """
    prior = 1.40 + 0.10 * (record.hba1c_percent - 7.0)
    return float(np.clip(prior, 0.4, 3.0))


def ehr_features(record: PatientRecord) -> dict[str, float]:
    classes = {m.drug_class for m in record.medications}
    return {
        "age_years": float(record.age_years),
        "bmi": record.bmi,
        "hba1c_percent": record.hba1c_percent,
        "fasting_glucose_mg_dl": record.fasting_glucose_mg_dl,
        "diabetes_duration_years": record.diabetes_duration_years,
        "egfr": record.egfr_ml_min_1_73m2,
        "med_sulfonylurea": float("sulfonylurea" in classes),
        "med_basal_insulin": float("basal_insulin" in classes),
        "med_biguanide": float("biguanide" in classes),
        "med_dpp4_inhibitor": float("dpp4_inhibitor" in classes),
    }


def split_streams(obs: pd.DataFrame) -> dict[str, pd.Series]:
    """Split a long-format observation frame (timestamp, kind, value) into per-kind series."""
    out = {}
    for kind in ("cgm", "meal", "steps", "heart_rate"):
        sub = obs[obs["kind"] == kind]
        s = pd.Series(sub["value"].to_numpy(dtype=float), index=pd.DatetimeIndex(sub["timestamp"]), name=kind)
        out[kind] = s.sort_index()
    return out


def meal_responses(cgm_grid: pd.Series, meals: pd.Series) -> pd.DataFrame:
    """Observed glucose rise per gram for each logged meal, with the time it becomes knowable.

    rise = max(CGM in (tm, tm+120]) - last CGM at or before tm. A meal is skipped if another
    meal is logged within its response window, carbs < 10 g, or the window is < 50 % observed.
    ``available_at`` = tm + 120 min: the ratio may only be used for predictions at or after it.
    """
    cols = ["meal_time", "carbs", "ratio", "available_at"]
    if meals.empty or cgm_grid.empty:
        return pd.DataFrame(columns=cols)
    rows = []
    mt = meals.index
    window = pd.Timedelta(minutes=MEAL_RESPONSE_WINDOW_MIN)
    for i, (t, carbs) in enumerate(meals.items()):
        if carbs < MIN_MEAL_CARBS_FOR_LEARNING:
            continue
        nxt = mt[i + 1] if i + 1 < len(mt) else None
        if nxt is not None and nxt <= t + window:
            continue
        pre = cgm_grid.loc[:t].dropna()
        post = cgm_grid.loc[t + pd.Timedelta(seconds=1) : t + window]
        if pre.empty or (t - pre.index[-1]) > pd.Timedelta(minutes=20):
            continue
        if post.notna().sum() < 0.5 * MEAL_RESPONSE_WINDOW_MIN / CGM_INTERVAL_MIN:
            continue
        rise = max(float(post.max()) - float(pre.iloc[-1]), 0.0)
        rows.append((t, carbs, rise / carbs, t + window))
    return pd.DataFrame(rows, columns=cols)


def personal_carb_sensitivity(responses: pd.DataFrame, prior: float, at: pd.DatetimeIndex) -> tuple[np.ndarray, np.ndarray]:
    """Shrunk running mean of meal-response ratios available at or before each time in ``at``."""
    if responses.empty:
        return np.full(len(at), prior), np.zeros(len(at), dtype=int)
    r = responses.sort_values("available_at")
    avail = pd.DatetimeIndex(r["available_at"]).as_unit("ns").asi8
    csum = np.concatenate([[0.0], np.cumsum(r["ratio"].to_numpy(dtype=float))])
    k = np.searchsorted(avail, pd.DatetimeIndex(at).as_unit("ns").asi8, side="right")
    est = (prior * CARB_SENS_SHRINKAGE_K + csum[k]) / (CARB_SENS_SHRINKAGE_K + k)
    return est, k


def _rolling_sum(series: pd.Series, at: pd.DatetimeIndex, minutes: int) -> np.ndarray:
    """Sum of event values with timestamp in (t - minutes, t] for each t in ``at``."""
    if series.empty:
        return np.zeros(len(at))
    ts = pd.DatetimeIndex(series.index).as_unit("ns").asi8
    csum = np.concatenate([[0.0], np.cumsum(series.to_numpy(dtype=float))])
    q = pd.DatetimeIndex(at).as_unit("ns").asi8
    hi = np.searchsorted(ts, q, side="right")
    lo = np.searchsorted(ts, q - minutes * 60 * 1_000_000_000, side="right")
    return csum[hi] - csum[lo]


def build_feature_frame(
    obs: pd.DataFrame,
    record: PatientRecord,
    responses: pd.DataFrame | None = None,
    only_last: bool = False,
) -> pd.DataFrame:
    """Compute features at every CGM reading time (or only the last one).

    Parameters
    ----------
    obs: long-format observations of ONE patient (columns timestamp, kind, value), any order.
    record: the patient's synthetic health record.
    responses: precomputed meal responses (online engine passes its running list); if None
        they are computed from ``obs``. Only responses with available_at <= t are used at t.
    only_last: compute just the final row (online serving).
    """
    streams = split_streams(obs)
    grid = to_grid(streams["cgm"])
    if grid.dropna().empty:
        return pd.DataFrame(columns=FEATURE_NAMES)
    g = grid
    gi = g.interpolate(limit=3, limit_area="inside")  # uses only readings <= any row time (rows exist only at readings)
    rows_idx = g.dropna().index
    at = rows_idx[-1:] if only_last else rows_idx

    f = pd.DataFrame(index=at)
    f["glucose"] = g.reindex(at)
    for m in (15, 30, 60):
        f[f"delta_{m}"] = f["glucose"] - gi.shift(m // CGM_INTERVAL_MIN).reindex(at)
    prev15 = gi.shift(3).reindex(at) - gi.shift(6).reindex(at)
    f["accel_15"] = f["delta_15"] - prev15
    cgm_obs = g.dropna()
    roll60 = cgm_obs.rolling("60min")
    roll180 = cgm_obs.rolling("180min")
    roll24 = cgm_obs.rolling("24h")
    f["mean_60"] = roll60.mean().reindex(at)
    f["std_60"] = roll60.std().reindex(at)
    f["max_180"] = roll180.max().reindex(at)
    f["min_180"] = roll180.min().reindex(at)
    f["mean_24h"] = roll24.mean().reindex(at)
    f["tar_24h"] = (cgm_obs > HYPER_THRESHOLD_MG_DL).astype(float).rolling("24h").mean().reindex(at)

    meals = streams["meal"]
    for m in (30, 60, 120):
        f[f"carbs_{m}"] = _rolling_sum(meals, at, m)
    # carbs on board: linear decay over COB_DURATION_MIN
    cob = np.zeros(len(at))
    last_meal_min = np.full(len(at), np.nan)
    if not meals.empty:
        q = pd.DatetimeIndex(at).as_unit("ns").asi8
        mts = pd.DatetimeIndex(meals.index).as_unit("ns").asi8
        mv = meals.to_numpy(dtype=float)
        for t_m, c in zip(mts, mv, strict=True):
            dt = (q - t_m) / 6e10
            active = (dt >= 0) & (dt < COB_DURATION_MIN)
            cob[active] += c * (1 - dt[active] / COB_DURATION_MIN)
        k = np.searchsorted(mts, q, side="right")
        has = k > 0
        last_meal_min[has] = (q[has] - mts[k[has] - 1]) / 6e10
    f["carbs_on_board"] = cob
    f["minutes_since_meal"] = np.minimum(np.nan_to_num(last_meal_min, nan=720.0), 720.0)

    prior = carb_sensitivity_prior(record)
    if responses is None:
        responses = meal_responses(g, meals)
    sens, _ = personal_carb_sensitivity(responses, prior, at)
    f["carb_sensitivity"] = sens
    f["expected_meal_rise"] = sens * cob

    steps = streams["steps"]
    f["steps_30"] = _rolling_sum(steps, at, 30)
    f["steps_60"] = _rolling_sum(steps, at, 60)
    hr = streams["heart_rate"]
    if hr.empty:
        f["hr_rel_30"] = np.nan
    else:
        hr_30 = hr.rolling("30min").mean()
        hr_base = hr.rolling("24h").median()
        rel = (hr_30 - hr_base)
        f["hr_rel_30"] = rel.reindex(at, method="ffill", tolerance=pd.Timedelta(minutes=15)).to_numpy()

    local = pd.DatetimeIndex(at) + pd.Timedelta(minutes=record.utc_offset_minutes)
    minute_of_day = local.hour * 60 + local.minute
    f["tod_sin"] = np.sin(2 * np.pi * minute_of_day / 1440)
    f["tod_cos"] = np.cos(2 * np.pi * minute_of_day / 1440)
    for name, val in ehr_features(record).items():
        f[name] = val
    return f[FEATURE_NAMES]
