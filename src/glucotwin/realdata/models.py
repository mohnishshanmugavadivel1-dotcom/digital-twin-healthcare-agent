"""Baselines, real-data models and metrics. Selection sees only train + validation; test is scored once, last."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from glucotwin.realdata.windows import FEATURES


def persistence(frame: pd.DataFrame) -> np.ndarray:
    """Future glucose = latest available recorded glucose (the anchor reading)."""
    return frame["g0"].to_numpy(dtype=float)


def make_ridge(alpha: float) -> Pipeline:
    # scaler statistics are fitted inside the pipeline, i.e. on whatever rows .fit receives (training patients only)
    return Pipeline([("scale", StandardScaler()), ("ridge", Ridge(alpha=alpha))])


def make_hgb(params: dict, seed: int) -> HistGradientBoostingRegressor:
    return HistGradientBoostingRegressor(random_state=seed, **params)


def fit_delta(model, train: pd.DataFrame, h: int):
    """Models predict the change y(t+h) - g0; the forecast is g0 + prediction."""
    return model.fit(train[FEATURES].to_numpy(float), (train[f"y_{h}"] - train["g0"]).to_numpy(float))


def predict_delta(model, frame: pd.DataFrame) -> np.ndarray:
    return frame["g0"].to_numpy(float) + model.predict(frame[FEATURES].to_numpy(float))


def rmse(err: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(err))))


def mae(err: np.ndarray) -> float:
    return float(np.mean(np.abs(err)))


def select(candidates: list[tuple[str, object]], train: pd.DataFrame, val: pd.DataFrame, h: int) -> dict:
    """Fit each candidate on training patients, score on validation patients; choose the lowest validation RMSE."""
    scores = []
    for name, model in candidates:
        fit_delta(model, train, h)
        scores.append({"candidate": name, "val_rmse": rmse(predict_delta(model, val) - val[f"y_{h}"].to_numpy(float)),
                       "model": model})
    best = min(scores, key=lambda s: s["val_rmse"])
    return {"chosen": best["candidate"], "model": best["model"],
            "validation_rmse_by_candidate": {s["candidate"]: round(s["val_rmse"], 4) for s in scores}}


def per_patient(frame: pd.DataFrame, err: np.ndarray) -> dict[str, dict]:
    out = {}
    for pid, idx in frame.groupby("patient_id").indices.items():
        e = err[idx]
        out[str(pid)] = {"n": int(len(e)), "mae": round(mae(e), 3), "rmse": round(rmse(e), 3)}
    return out


def patient_bootstrap(frame: pd.DataFrame, errors: dict[str, np.ndarray], reference: str, n_boot: int,
                      seed: int) -> dict:
    """Resample TEST PATIENTS with replacement; recompute pooled MAE/RMSE per model and paired differences vs the
    reference model (same resampled patients and windows). Percentile 95% intervals."""
    groups = list(frame.groupby("patient_id").indices.values())
    rng = np.random.default_rng(seed)
    draws = {m: {"mae": [], "rmse": []} for m in errors}
    diffs = {m: {"mae": [], "rmse": []} for m in errors if m != reference}
    for _ in range(n_boot):
        pick = rng.integers(0, len(groups), len(groups))
        idx = np.concatenate([groups[i] for i in pick])
        stat = {m: (mae(e[idx]), rmse(e[idx])) for m, e in errors.items()}
        for m, (a, r) in stat.items():
            draws[m]["mae"].append(a)
            draws[m]["rmse"].append(r)
            if m != reference:
                diffs[m]["mae"].append(a - stat[reference][0])
                diffs[m]["rmse"].append(r - stat[reference][1])

    def ci(x):
        return [round(float(np.percentile(x, 2.5)), 3), round(float(np.percentile(x, 97.5)), 3)]

    return {"n_boot": n_boot, "seed": seed, "unit": "test patient",
            "ci95": {m: {k: ci(v) for k, v in d.items()} for m, d in draws.items()},
            f"difference_vs_{reference}_ci95": {m: {k: ci(v) for k, v in d.items()} for m, d in diffs.items()}}
