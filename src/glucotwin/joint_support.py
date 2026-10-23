"""B-23: joint training-support check for what-if meal scenarios.

A what-if meal of g grams changes five learned inputs together: ``carbs_30``, ``carbs_60``,
``carbs_120``, ``carbs_on_board`` (each + g) and ``expected_meal_rise`` (= ``carb_sensitivity``
x ``carbs_on_board``, an exact identity in ``features.py``). Every scenario is a meal-now situation,
so the reference population is **every logged training meal, with the five inputs evaluated at the
moment it was logged** (``meal_event_rows``; same formulas as ``features.py``, verified equal on every
CGM row in tests). Version 2 used feature rows < 5 min after a meal instead; that silently dropped
meals followed by a CGM dropout (25 of 1647 training meals, including the largest expected meal rises),
found during an internal pre-commit review.

Evidence for the design is in ``reports/research/b23_joint_support.json``:

* on training meals ``carbs_60 == carbs_30`` in 100% of rows and ``carbs_120 ==
  carbs_30`` in 99.3%, so a 5-D covariance is exactly singular and a ridge-regularized
  Mahalanobis verdict depends on the arbitrary ridge constant (rejected);
* in the remaining coordinates, meal size and carb sensitivity are nearly uncorrelated
  (r = -0.04), and a calibrated 2-D Mahalanobis/kNN threshold does NOT hold its nominal
  false-warning rate on new patients, because sensitivity is a patient trait and only 12
  validation patients are available for calibration (evaluated, not used for warnings).

What is shipped is therefore exact and threshold-free. The five inputs are re-expressed in
decorrelated coordinates, and a scenario is flagged when any coordinate lies outside the range
observed at training meals ("no training analogue"):

* ``meal_carbs`` = carbs_30 (marginal; flagged outside [min, max]);
* ``expected_meal_rise`` (joint meal-size x carb-sensitivity product; above max);
* ``prior_carbs_30_60`` = carbs_60 - carbs_30 (joint; above max, which is 0 g);
* ``prior_carbs_60_120`` = carbs_120 - carbs_60 (joint; above max);
* ``older_carbs_on_board`` = carbs_on_board - carbs_30 (joint; above max).

``carb_sensitivity`` (= expected_meal_rise / carbs_on_board) is reported but is not a reason: it
is a fixed patient trait that a hypothetical meal does not change, so it is a patient-level
question that affects the no-meal forecast equally, not a property of the scenario.

This is a training-support diagnostic, not a guaranteed out-of-distribution detector and not
evidence of prediction error. Inside the envelope, data can still be sparse. The check never
alters or suppresses a forecast.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from glucotwin.features import (
    COB_DURATION_MIN,
    _rolling_sum,
    carb_sensitivity_prior,
    meal_responses,
    personal_carb_sensitivity,
    split_streams,
)
from glucotwin.labels import to_grid

JOINT_FEATURES: tuple[str, ...] = ("carbs_30", "carbs_60", "carbs_120", "carbs_on_board", "expected_meal_rise")
COORDS: tuple[str, ...] = ("meal_carbs", "carb_sensitivity", "expected_meal_rise",
                           "prior_carbs_30_60", "prior_carbs_60_120", "older_carbs_on_board")
REASON_COORDS: tuple[str, ...] = ("meal_carbs", "expected_meal_rise", "prior_carbs_30_60", "prior_carbs_60_120",
                                  "older_carbs_on_board")
LOWER_BOUNDED: tuple[str, ...] = ("meal_carbs",)  # also flagged below the training min
TOL = {"meal_carbs": 0.5, "carb_sensitivity": 1e-3, "expected_meal_rise": 0.5,
       "prior_carbs_30_60": 0.5, "prior_carbs_60_120": 0.5, "older_carbs_on_board": 0.5}
SPARSE_SHARE = 0.01  # coordinate values seen in < 1% of training meals are reported as sparse
FORMAT = "b23-joint-support/3"
CAVEAT = ("Training-support check: it flags meal inputs with no comparable example in the training data. "
          "It is not evidence that the forecast is wrong, and inputs inside the training range do not make a "
          "forecast accurate.")
STATUSES = ("within_training_support", "no_training_analogue", "unavailable")

# Each phrase is a statement about the training meals as logged (the reference population); a test checks
# the claims against every training meal of the default cohort.
_REASON_TEXT = {
    # meal_carbs = carbs logged in the last 30 min, so a meal right after another logged meal counts both
    "meal_carbs_above": "more carbs in the last 30 min (this meal plus any meal logged in the previous 30 min) "
                        "than any training meal",
    "meal_carbs_below": "fewer carbs than any training meal",
    "expected_meal_rise_above": "this meal size combined with this patient's carb sensitivity gives a larger "
                                "expected meal rise than any training meal had when it was logged",
    "prior_carbs_30_60_above": "another meal was logged 30-60 min earlier (no training meal had one)",
    "prior_carbs_60_120_above": "more carbs were logged 1-2 h earlier than for any training meal",
    "older_carbs_on_board_above": "more carbs are still on board from earlier meals than for any training meal "
                                  "when it was logged",
}


class JointSupportError(ValueError):
    """Raised for a model file that is malformed or in an unsupported format."""


def joint_inputs_at(meals: pd.Series, responses: pd.DataFrame, prior: float, at: pd.DatetimeIndex) -> pd.DataFrame:
    """The five joint inputs (plus carb_sensitivity) at arbitrary times, with the formulas of ``features.py``.

    ``features.build_feature_frame`` only evaluates at CGM reading times; this evaluates the meal-derived
    inputs at any time (e.g. the instant a meal is logged). Equality with ``build_feature_frame`` on every
    CGM row is asserted in tests/test_joint_support.py, so the two cannot drift silently.
    """
    at = pd.DatetimeIndex(at)
    out = pd.DataFrame(index=at)
    for m in (30, 60, 120):
        out[f"carbs_{m}"] = _rolling_sum(meals, at, m)
    cob = np.zeros(len(at))
    if not meals.empty:
        q = at.as_unit("ns").asi8
        for t_m, c in zip(pd.DatetimeIndex(meals.index).as_unit("ns").asi8, meals.to_numpy(dtype=float), strict=True):
            dt = (q - t_m) / 6e10
            active = (dt >= 0) & (dt < COB_DURATION_MIN)
            cob[active] += c * (1 - dt[active] / COB_DURATION_MIN)
    out["carbs_on_board"] = cob
    sens, _ = personal_carb_sensitivity(responses, prior, at)
    out["carb_sensitivity"] = sens
    out["expected_meal_rise"] = sens * cob
    return out


def meal_event_rows(obs: pd.DataFrame, record) -> pd.DataFrame:
    """Reference rows for ONE patient: the joint inputs at the instant each meal was logged (meal included).

    Independent of whether a CGM reading follows the meal. The carb-sensitivity estimate uses only meal
    responses already available at that instant (``available_at`` <= t), exactly as in ``features.py``.
    """
    streams = split_streams(obs)
    meals = streams["meal"]
    if meals.empty:
        return pd.DataFrame(columns=[*JOINT_FEATURES, "carb_sensitivity", "patient_id", "timestamp"])
    responses = meal_responses(to_grid(streams["cgm"]), meals)
    at = pd.DatetimeIndex(meals.index.unique())
    rows = joint_inputs_at(meals, responses, carb_sensitivity_prior(record), at)
    rows.index.name = "timestamp"
    return rows.reset_index().assign(patient_id=record.patient_id)


def cohort_meal_event_rows(cohort, split: str) -> pd.DataFrame:
    """``meal_event_rows`` for every patient of one split of a generated cohort."""
    parts = [meal_event_rows(cohort.patient_observations(r.patient_id), r) for r in cohort.records if r.split == split]
    return pd.concat(parts, ignore_index=True)


def coords_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Decorrelated coordinates for rows with carbs_on_board > 0 (vectorised)."""
    return pd.DataFrame({
        "meal_carbs": df["carbs_30"].astype(float),
        "carb_sensitivity": df["expected_meal_rise"].astype(float) / df["carbs_on_board"].astype(float),
        "expected_meal_rise": df["expected_meal_rise"].astype(float),
        "prior_carbs_30_60": (df["carbs_60"] - df["carbs_30"]).astype(float),
        "prior_carbs_60_120": (df["carbs_120"] - df["carbs_60"]).astype(float),
        "older_carbs_on_board": (df["carbs_on_board"] - df["carbs_30"]).astype(float),
    }, index=df.index)


def apply_meal_now(baseline: pd.DataFrame, grams: float) -> pd.DataFrame:
    """Analytic meal-now scenario inputs from baseline feature rows (a meal of ``grams`` logged at the row time).

    Mirrors what the engine computes for the scenario leg (verified in tests/test_joint_support.py): every
    carb window and carbs-on-board gain ``grams``; expected_meal_rise = carb_sensitivity x new carbs-on-board.
    Used by the analysis script to sweep many moments without rebuilding features.
    """
    out = pd.DataFrame(index=baseline.index)
    for c in ("carbs_30", "carbs_60", "carbs_120", "carbs_on_board"):
        out[c] = baseline[c].astype(float) + float(grams)
    out["expected_meal_rise"] = baseline["carb_sensitivity"].astype(float) * out["carbs_on_board"]
    return out


def _validate(row: Mapping[str, float]) -> tuple[dict[str, float] | None, str | None]:
    vals: dict[str, float] = {}
    for k in JOINT_FEATURES:
        if k not in row or row[k] is None:
            return None, f"missing input {k}"
        raw = row[k]
        # strict: numbers only (no strings such as "60", no booleans, which float() would silently accept)
        if isinstance(raw, (bool, np.bool_)) or not isinstance(raw, (int, float, np.integer, np.floating)):
            return None, f"non-numeric input {k}"
        v = float(raw)
        if not math.isfinite(v):
            return None, f"non-finite input {k}"
        if v < 0:
            return None, f"negative input {k}"
        vals[k] = v
    if vals["carbs_30"] <= 0 or vals["carbs_on_board"] <= 0 or vals["expected_meal_rise"] <= 0:
        return None, "no meal in the last 30 min (joint support is defined for meal-now scenarios only)"
    if vals["carbs_60"] < vals["carbs_30"] or vals["carbs_120"] < vals["carbs_60"]:
        return None, "inconsistent inputs (carb windows must be nested: carbs_30 <= carbs_60 <= carbs_120)"
    return vals, None


@dataclass(frozen=True)
class JointSupportModel:
    training_data: str
    lo: dict[str, float]
    hi: dict[str, float]
    sparse_above: dict[str, float]  # 99th percentile over training meals (values above it are sparse)
    n_train_rows: int
    n_train_patients: int
    format: str = FORMAT

    def flags(self, c: pd.DataFrame) -> pd.DataFrame:
        """Boolean reason columns for a coordinates frame (vectorised; used by the analysis script)."""
        out = {}
        for k in REASON_COORDS:
            out[f"{k}_above"] = c[k] > self.hi[k] + TOL[k]
            if k in LOWER_BOUNDED:
                out[f"{k}_below"] = c[k] < self.lo[k] - TOL[k]
        return pd.DataFrame(out, index=c.index)

    def assess(self, row: Mapping[str, float]) -> dict:
        """Joint-support verdict for one meal-now feature row (mapping with the five numeric inputs)."""
        vals, why = _validate(row)
        if vals is None:
            return {"status": "unavailable", "reason": why, "reasons": [], "sparse": [], "message": None,
                    "coordinates": {}, "training_range": {}, "caveat": CAVEAT}
        c = coords_frame(pd.DataFrame([vals]))
        f = self.flags(c).iloc[0]
        reasons = [k for k in f.index if bool(f[k])]
        cv = {k: float(c[k].iloc[0]) for k in COORDS}
        sparse = [k for k in REASON_COORDS if cv[k] > self.sparse_above[k] + TOL[k] and f"{k}_above" not in reasons]
        return {
            "status": "no_training_analogue" if reasons else "within_training_support",
            "reason": None,
            "reasons": reasons,
            "sparse": sparse,
            "message": ("No comparable training example: " + "; ".join(_REASON_TEXT[r] for r in reasons) + ".")
            if reasons else None,
            "coordinates": {k: round(v, 3) for k, v in cv.items()},
            "training_range": {k: [round(self.lo[k], 3), round(self.hi[k], 3)] for k in COORDS},
            "caveat": CAVEAT,
        }

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Mapping) -> JointSupportModel:
        if not isinstance(d, Mapping) or d.get("format") != FORMAT:
            raise JointSupportError("unsupported joint-support format")
        try:
            return cls(training_data=str(d["training_data"]),
                       lo={k: float(d["lo"][k]) for k in COORDS}, hi={k: float(d["hi"][k]) for k in COORDS},
                       sparse_above={k: float(d["sparse_above"][k]) for k in COORDS},
                       n_train_rows=int(d["n_train_rows"]), n_train_patients=int(d["n_train_patients"]))
        except (KeyError, TypeError, ValueError) as e:
            raise JointSupportError(f"malformed joint-support model: {e}") from None


def fit_joint_support(train_fresh: pd.DataFrame, training_data: str) -> JointSupportModel:
    """Observed envelope of the TRAINING meal rows (``cohort_meal_event_rows(cohort, "train")``; no
    validation or test data involved)."""
    if train_fresh.empty:
        raise ValueError("no training meal rows")
    if not np.isfinite(train_fresh[list(JOINT_FEATURES)].to_numpy(float)).all():
        raise ValueError("non-finite training inputs")
    c = coords_frame(train_fresh)
    return JointSupportModel(
        training_data=training_data,
        lo={k: float(c[k].min()) for k in COORDS}, hi={k: float(c[k].max()) for k in COORDS},
        sparse_above={k: float(np.percentile(c[k], 100 * (1 - SPARSE_SHARE))) for k in COORDS},
        n_train_rows=len(c),
        n_train_patients=int(train_fresh["patient_id"].nunique()) if "patient_id" in train_fresh else 0,
    )


def load_joint_support(path: Path | None, training_data: str) -> tuple[JointSupportModel | None, str | None]:
    """Load the fitted envelope; refuse it (with a safe reason) if missing, unreadable or fitted on other data."""
    if path is None:
        return None, "joint-support model not configured"
    if not path.exists():
        return None, "joint-support model file not found"
    try:
        model = JointSupportModel.from_dict(json.loads(path.read_text())["model"])
    except (OSError, ValueError, KeyError, TypeError):
        return None, "joint-support model file is unreadable"
    if model.training_data != training_data:
        return None, "joint-support model was fitted on different training data than the served model"
    return model, None
