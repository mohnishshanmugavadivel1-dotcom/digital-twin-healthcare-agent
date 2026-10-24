"""Baseline and candidate models for glucose trajectory and excursion-risk forecasting.

Trajectory models predict the *change* in glucose at each horizon (30/60/90/120 min);
event models output P(excursion onset within 120 min). Simple baselines are always
evaluated next to learned models: a learned model only earns its place if it beats them
on held-out patients.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from glucotwin.config import FORECAST_HORIZONS_MIN, HYPER_THRESHOLD_MG_DL

GLUCOSE_CLIP = (40.0, 400.0)
TREND_TAU_MIN = 30.0


def _clip(x):
    return np.clip(x, *GLUCOSE_CLIP)


# ---------------------------------------------------------------- trajectory
class PersistenceForecaster:
    """Glucose stays where it is. The minimum bar every model must beat."""

    name = "persistence"

    def fit(self, X: pd.DataFrame, Y: pd.DataFrame):
        return self

    def predict(self, X: pd.DataFrame) -> pd.DataFrame:
        g = X["glucose"].to_numpy(dtype=float)
        return pd.DataFrame({h: g for h in FORECAST_HORIZONS_MIN}, index=X.index)


class DampedTrendForecaster:
    """Extrapolates the 30-min slope with exponential damping (tau = 30 min)."""

    name = "damped_trend"

    def fit(self, X, Y):
        return self

    def predict(self, X: pd.DataFrame) -> pd.DataFrame:
        g = X["glucose"].to_numpy(dtype=float)
        slope = np.nan_to_num(X["delta_30"].to_numpy(dtype=float) / 30.0)
        out = {}
        for h in FORECAST_HORIZONS_MIN:
            h_eff = TREND_TAU_MIN * (1 - np.exp(-h / TREND_TAU_MIN))
            out[h] = _clip(g + slope * h_eff)
        return pd.DataFrame(out, index=X.index)


class _DeltaRegressor:
    """One regressor per horizon predicting glucose(t+h) - glucose(t)."""

    name = "base"

    def _make(self):
        raise NotImplementedError

    def fit(self, X: pd.DataFrame, Y: pd.DataFrame):
        self.models_ = {}
        g = X["glucose"].to_numpy(dtype=float)
        for h in FORECAST_HORIZONS_MIN:
            y = Y[f"y_glucose_{h}"].to_numpy(dtype=float) - g
            ok = ~np.isnan(y)
            self.models_[h] = self._make().fit(X[ok], y[ok])
        return self

    def predict(self, X: pd.DataFrame) -> pd.DataFrame:
        g = X["glucose"].to_numpy(dtype=float)
        return pd.DataFrame({h: _clip(g + m.predict(X)) for h, m in self.models_.items()}, index=X.index)


class RidgeForecaster(_DeltaRegressor):
    name = "ridge"

    def _make(self):
        return Pipeline([("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler()),
                         ("model", Ridge(alpha=1.0))])


class GradientBoostingForecaster(_DeltaRegressor):
    name = "hist_gradient_boosting"

    def __init__(self, seed: int = 0):
        self.seed = seed

    def _make(self):
        return HistGradientBoostingRegressor(max_iter=300, learning_rate=0.06, max_leaf_nodes=31,
                                             l2_regularization=1.0, random_state=self.seed)


# ---------------------------------------------------------------- events
class TrendRuleScorer:
    """Rule baseline: score = damped-trend forecast's maximum over 2 h, mapped to (0, 1)."""

    name = "trend_rule"

    def fit(self, X, y):
        return self

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        traj = DampedTrendForecaster().predict(X).to_numpy().max(axis=1)
        return 1 / (1 + np.exp(-(traj - HYPER_THRESHOLD_MG_DL) / 15.0))


class LogisticEventModel:
    """Standardised logistic regression; explainable via per-feature log-odds contributions."""

    name = "logistic_regression"

    def fit(self, X: pd.DataFrame, y: np.ndarray):
        self.feature_names_ = list(X.columns)
        self.imputer_ = SimpleImputer(strategy="median").fit(X)
        Z = self.imputer_.transform(X)
        self.scaler_ = StandardScaler().fit(Z)
        self.model_ = LogisticRegression(C=0.5, max_iter=2000).fit(self.scaler_.transform(Z), y)
        return self

    def _z(self, X: pd.DataFrame) -> np.ndarray:
        return self.scaler_.transform(self.imputer_.transform(X[self.feature_names_]))

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        return self.model_.predict_proba(self._z(X))[:, 1]

    def contributions(self, X: pd.DataFrame) -> np.ndarray:
        """Additive log-odds contribution of each feature relative to the training mean."""
        return self._z(X) * self.model_.coef_[0]


class GradientBoostingEventModel:
    name = "hist_gradient_boosting"

    def __init__(self, seed: int = 0):
        self.seed = seed

    def fit(self, X, y):
        self.model_ = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.06, max_leaf_nodes=31,
                                                     l2_regularization=1.0, random_state=self.seed).fit(X, y)
        return self

    def predict_proba(self, X):
        return self.model_.predict_proba(X)[:, 1]
