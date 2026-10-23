"""Descriptive uncertainty of the personal carb-sensitivity estimate (glucotwin.twin.personal_uncertainty)."""

import math

import pandas as pd

from glucotwin.features import CARB_SENS_SHRINKAGE_K, personal_carb_sensitivity
from glucotwin.twin.personal_uncertainty import carb_sensitivity_uncertainty

T0 = pd.Timestamp("2026-01-01T08:00:00Z")


def _responses(ratios: list[float]) -> pd.DataFrame:
    times = [T0 + pd.Timedelta(hours=6 * i) for i in range(len(ratios))]
    return pd.DataFrame(
        {
            "meal_time": times,
            "carbs": 40.0,
            "ratio": ratios,
            "available_at": [t + pd.Timedelta(minutes=120) for t in times],
        }
    )


def test_no_meals_is_prior_only() -> None:
    u = carb_sensitivity_uncertainty(_responses([]).iloc[0:0], T0)
    assert u == (0.0, None, None)


def test_single_meal_has_weight_but_no_sd() -> None:
    u = carb_sensitivity_uncertainty(_responses([1.2]), T0 + pd.Timedelta(hours=3))
    assert math.isclose(u.observed_weight, 1 / (CARB_SENS_SHRINKAGE_K + 1))
    assert u.response_sd is None and u.sampling_se is None


def test_values_match_closed_form_and_ignore_future_meals() -> None:
    resp = _responses([1.0, 2.0, 3.0, 9.0])
    now = T0 + pd.Timedelta(hours=12, minutes=120)  # first three available, fourth not yet
    u = carb_sensitivity_uncertainty(resp, now)
    _, k = personal_carb_sensitivity(resp, 1.5, pd.DatetimeIndex([now]))
    assert int(k[0]) == 3  # same knowable set as the served estimate
    assert math.isclose(u.observed_weight, 3 / (CARB_SENS_SHRINKAGE_K + 3))
    assert math.isclose(u.response_sd, 1.0)
    assert math.isclose(u.sampling_se, 1.0 * math.sqrt(3) / (CARB_SENS_SHRINKAGE_K + 3))


def test_state_exposes_fields_without_changing_estimate(service) -> None:
    pid = service.demo_patient_ids()[0]
    state = service.create_replay(pid, 72.0).state
    p = state.personal
    assert p.observed_weight is not None and 0.0 <= p.observed_weight < 1.0
    assert math.isclose(
        p.observed_weight, round(p.meals_used / (CARB_SENS_SHRINKAGE_K + p.meals_used), 3), abs_tol=1e-3
    )
    if p.meals_used >= 2:
        assert p.sampling_se_mg_dl_per_g is not None and p.sampling_se_mg_dl_per_g < p.response_sd_mg_dl_per_g
