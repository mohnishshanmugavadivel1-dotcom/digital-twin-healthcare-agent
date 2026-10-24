"""Personalised meal-response curve and cohort-level walk effect (research estimates shown next to the What-If).

Both estimators were fitted on training patients, selected on validation patients and scored once on test
patients of the synthetic cohort against paired simulator ground truth:

* meal curve, protocol addendum v3 (``reports/research/twin_and_whatif_validation.json``,
  ``D_train_fitted_validation_selected_curve``): delta_h = k_h x grams x s(t0), with k_h = alpha_h x c(h)
  (selected candidate ``median_cal``; values copied at 3 decimals, a test keeps them in sync);
* walk effect, protocol addendum v4 (``reports/research/walk_whatif_validation.json``): a 20-min walk of
  2,500 steps starting 15 min after the meal changes glucose by beta_h x latest CGM (selected ``glucose_scaled``).

They are arithmetic on the twin's learned carb sensitivity and latest reading. They never change the served
forecast, the tree-model What-If numbers, or the twin state. Synthetic evidence only; not advice.
"""

from __future__ import annotations

from glucotwin.contracts import TwinCurveEstimate

HORIZONS = (30, 60, 120)
# addendum v3 selected_alpha and curve_shape["median"] (3 decimals)
CURVE_ALPHA = {30: 1.738, 60: 1.217, 120: 1.115}
CURVE_SHAPE = {30: 0.097, 60: 0.588, 120: 0.905}
CURVE_K = {h: CURVE_ALPHA[h] * CURVE_SHAPE[h] for h in HORIZONS}
# addendum v4 served_coefficients (mg/dL change per mg/dL of latest CGM)
WALK_BETA = {30: -0.04524, 60: -0.23682, 120: -0.11954}
WALK = {"minutes": 20, "steps": 2500, "start_after_meal_min": 15}
# conditions under which the estimators were scored on test patients
TESTED_GRAMS = (20.0, 120.0)
TESTED_MAX_CGM = 180.0
# held-out synthetic test MAE (mg/dL) from the two reports, for display
CURVE_TEST_MAE = {30: 1.8, 60: 5.3, 120: 5.9}
WALK_TEST_MAE = {30: 1.0, 60: 6.2, 120: 4.3}

CAVEAT = (
    "Research estimate, not the served forecast. Fitted on synthetic training patients, selected on validation "
    "patients and tested once on held-out synthetic patients against simulator ground truth; the simulator's "
    "near-linear meal response favours it. The walk effect is cohort level (the twin has no personal activity "
    "parameter) and reflects the simulator's built-in exercise model. Not evidence about real patients; not advice."
)


def twin_curve_estimate(meal_grams: float, sensitivity: float | None, meals_used: int,
                        latest_cgm: float | None) -> TwinCurveEstimate | None:
    """Return the personalised curve (and walk effect) for a hypothetical meal, or None without a sensitivity."""
    if sensitivity is None:
        return None
    meal = {str(h): round(CURVE_K[h] * float(meal_grams) * float(sensitivity), 1) for h in HORIZONS}
    walk = with_walk = None
    if latest_cgm is not None:
        walk = {str(h): round(WALK_BETA[h] * float(latest_cgm), 1) for h in HORIZONS}
        with_walk = {k: round(meal[k] + walk[k], 1) for k in meal}
    reasons = []
    if not TESTED_GRAMS[0] <= float(meal_grams) <= TESTED_GRAMS[1]:
        reasons.append(f"meal size outside the tested {TESTED_GRAMS[0]:g}-{TESTED_GRAMS[1]:g} g")
    if latest_cgm is None or latest_cgm > TESTED_MAX_CGM:
        reasons.append(f"latest CGM above {TESTED_MAX_CGM:g} mg/dL or missing (not tested)")
    return TwinCurveEstimate(
        delta_glucose_mg_dl=meal,
        walk_delta_glucose_mg_dl=walk,
        with_walk_delta_glucose_mg_dl=with_walk,
        carb_sensitivity_mg_dl_per_g=round(float(sensitivity), 3),
        meals_used=int(meals_used),
        latest_cgm_mg_dl=None if latest_cgm is None else float(latest_cgm),
        walk={k: float(v) for k, v in WALK.items()},
        within_tested_range=not reasons,
        outside_tested_reasons=reasons,
        test_mae_mg_dl={str(h): v for h, v in CURVE_TEST_MAE.items()},
        walk_test_mae_mg_dl={str(h): v for h, v in WALK_TEST_MAE.items()},
        caveat=CAVEAT,
    )
