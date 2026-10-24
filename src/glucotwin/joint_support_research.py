"""B-23 research-only statistics (NOT used for serving).

Evaluated in ``scripts/b23_joint_support_analysis.py`` and rejected as a warning rule (see the module
docstring of ``glucotwin.joint_support`` and ``reports/research/b23_joint_support.json``). Kept in a
separate module so the serving check in ``glucotwin.joint_support`` contains only what it uses.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from glucotwin.joint_support import coords_frame


def stat_coords(df: pd.DataFrame) -> np.ndarray:
    """(n, 2) array: log meal size and log carb sensitivity."""
    c = coords_frame(df)
    return np.column_stack([np.log(c["meal_carbs"].to_numpy()), np.log(c["carb_sensitivity"].to_numpy())])


def stable_precision(z: np.ndarray) -> tuple[np.ndarray, np.ndarray, float, float]:
    """Ledoit-Wolf mean/precision with an eigenvalue floor; returns (mean, precision, shrinkage, condition)."""
    from sklearn.covariance import LedoitWolf

    lw = LedoitWolf().fit(z)
    w, v = np.linalg.eigh(lw.covariance_)
    w = np.maximum(w, max(float(w.max()) * 1e-9, 1e-12))
    return lw.location_, (v / w) @ v.T, float(lw.shrinkage_), float(w.max() / w.min())


def mahalanobis(z: np.ndarray, mean: np.ndarray, precision: np.ndarray) -> np.ndarray:
    d = np.atleast_2d(z) - mean
    return np.sqrt(np.einsum("ij,jk,ik->i", d, precision, d))


def conformal_threshold(scores: np.ndarray, alpha: float) -> float:
    """Split-conformal quantile: the ceil((n+1)(1-alpha))-th smallest score (inf if n is too small)."""
    s = np.sort(np.asarray(scores, float))
    n = s.size
    if n == 0 or not 0 < alpha < 1:
        raise ValueError("need scores and 0 < alpha < 1")
    k = math.ceil((n + 1) * (1 - alpha))
    return float("inf") if k > n else float(s[k - 1])


