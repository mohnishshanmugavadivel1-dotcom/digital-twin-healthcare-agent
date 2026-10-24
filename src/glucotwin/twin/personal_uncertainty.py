"""How much the personal carb-sensitivity estimate rests on the patient's own meals.

Descriptive only: these numbers are shown next to the estimate and never feed a forecast.

The served estimate (glucotwin.features.personal_carb_sensitivity) is a shrunk running mean
    s = (k * s0 + sum(r_i)) / (k + n),   k = CARB_SENS_SHRINKAGE_K,
over the n meal-response ratios r_i that are knowable at `now` (available_at <= now).

* observed_weight = n / (k + n): share of the estimate that comes from observed meals (0 = prior only).
* response_sd     = sample SD of the r_i (n >= 2): how variable this patient's meal responses are.
* sampling_se     = response_sd * sqrt(n) / (k + n): standard error of s from meal-to-meal
  variation, treating the prior s0 as fixed. It is a frequentist sampling error, NOT a Bayesian
  posterior SD, and ignores error in the prior and in each observed ratio.
"""

from __future__ import annotations

from typing import NamedTuple

import numpy as np
import pandas as pd

from glucotwin.features import CARB_SENS_SHRINKAGE_K


class CarbSensitivityUncertainty(NamedTuple):
    observed_weight: float
    response_sd: float | None
    sampling_se: float | None


def carb_sensitivity_uncertainty(responses: pd.DataFrame, now: pd.Timestamp) -> CarbSensitivityUncertainty:
    """Uncertainty summary for the estimate at ``now``; uses only ratios with available_at <= now."""
    k = float(CARB_SENS_SHRINKAGE_K)
    if responses.empty:
        return CarbSensitivityUncertainty(0.0, None, None)
    known = pd.DatetimeIndex(responses["available_at"]) <= now
    r = responses.loc[known, "ratio"].to_numpy(dtype=float)
    n = r.size
    if n < 2:
        return CarbSensitivityUncertainty(n / (k + n), None, None)
    sd = float(np.std(r, ddof=1))
    return CarbSensitivityUncertainty(n / (k + n), sd, sd * np.sqrt(n) / (k + n))
