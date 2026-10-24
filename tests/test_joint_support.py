"""B-23: joint training-support check for what-if meal scenarios.

Synthetic fixtures only (hand-built frames and the small deterministic test cohort). The tests pin
down construction invariants, not clinical behaviour:

* in-distribution scenarios pass; scenarios whose inputs are each in range but jointly unseen are
  flagged with the right reason;
* perfectly collinear inputs (carbs_60 == carbs_30 everywhere) are handled without any inverse;
* missing / non-finite / invalid inputs give ``unavailable``, never an exception or a false verdict;
* boundaries behave as documented (tolerance), fitting and assessment are deterministic;
* the analytic meal-now transform used by the analysis script equals the engine's scenario row;
* the API field is additive, B-22 comparisons are unchanged, and the check never alters a forecast.
"""

from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from glucotwin.api.app import create_app
from glucotwin.joint_support import (
    COORDS,
    JOINT_FEATURES,
    TOL,
    JointSupportError,
    JointSupportModel,
    apply_meal_now,
    cohort_meal_event_rows,
    fit_joint_support,
    joint_inputs_at,
    load_joint_support,
    meal_event_rows,
)
from glucotwin.joint_support_research import conformal_threshold, mahalanobis, stable_precision

TD = "synthetic-fixture v0, seed 0, 300 train rows"


def _train_frame(n: int = 300, seed: int = 0) -> pd.DataFrame:
    """Meal-now training rows shaped like the real ones: collinear carb windows, little older COB."""
    rng = np.random.default_rng(seed)
    meal = rng.uniform(20, 150, n).round()
    sens = rng.uniform(1.0, 2.0, n)
    older = np.where(rng.random(n) < 0.05, rng.uniform(0, 20, n), rng.uniform(-3, 0, n))
    prior_60_120 = np.where(rng.random(n) < 0.02, rng.uniform(10, 40, n).round(), 0.0)
    cob = meal + older
    return pd.DataFrame({
        "patient_id": [f"P{i % 12:02d}" for i in range(n)], "minutes_since_meal": 0.0,
        "carbs_30": meal, "carbs_60": meal, "carbs_120": meal + prior_60_120, "carbs_on_board": cob,
        "expected_meal_rise": sens * cob, "carb_sensitivity": sens,
    })


@pytest.fixture(scope="module")
def model() -> JointSupportModel:
    return fit_joint_support(_train_frame(), TD)


def _row(meal=60.0, prior_30_60=0.0, prior_60_120=0.0, older=0.0, sens=1.5) -> dict[str, float]:
    cob = meal + older
    return {"carbs_30": meal, "carbs_60": meal + prior_30_60, "carbs_120": meal + prior_30_60 + prior_60_120,
            "carbs_on_board": cob, "expected_meal_rise": sens * cob}


# ------------------------------------------------------------------ verdicts
def test_in_distribution_scenario_is_within_support(model):
    a = model.assess(_row())
    assert a["status"] == "within_training_support" and a["reasons"] == [] and a["message"] is None
    assert set(a["coordinates"]) == set(COORDS)


@pytest.mark.parametrize("kwargs, reason", [
    ({"prior_30_60": 40.0}, "prior_carbs_30_60_above"),  # a meal 30-60 min earlier: never in training
    ({"older": 45.0}, "older_carbs_on_board_above"),     # stacked on a recent meal
    ({"prior_60_120": 80.0}, "prior_carbs_60_120_above"),
])
def test_individually_normal_but_jointly_unusual_is_flagged(model, kwargs, reason):
    train = _train_frame()
    row = _row(**kwargs)
    # every raw input on its own lies inside the training marginal range ...
    for k in JOINT_FEATURES:
        assert train[k].min() <= row[k] <= train[k].max(), (k, row[k])
    # ... but the combination has no training analogue
    a = model.assess(row)
    assert a["status"] == "no_training_analogue" and reason in a["reasons"], a
    assert a["message"].startswith("No comparable training example")


def test_meal_size_and_sensitivity_in_range_but_product_above_max_is_flagged(model):
    train = _train_frame()
    row = _row(meal=145.0, sens=1.99)
    assert train.carbs_30.min() <= row["carbs_30"] <= train.carbs_30.max()
    assert train.carb_sensitivity.min() <= 1.99 <= train.carb_sensitivity.max()
    a = model.assess(row)
    # expected_meal_rise is itself one of the five inputs, so this case is a joint (product) exceedance of
    # in-range meal size and sensitivity, not "every raw input in range"
    assert row["expected_meal_rise"] > train.expected_meal_rise.max()
    assert a["status"] == "no_training_analogue" and a["reasons"] == ["expected_meal_rise_above"]


def test_meal_size_outside_training_range_is_flagged_both_sides(model):
    assert "meal_carbs_above" in model.assess(_row(meal=260.0))["reasons"]
    assert "meal_carbs_below" in model.assess(_row(meal=5.0))["reasons"]


def test_patient_level_sensitivity_alone_is_reported_not_flagged(model):
    a = model.assess(_row(meal=30.0, sens=0.5))  # far below training sensitivities, but EMR stays in range
    assert a["status"] == "within_training_support"
    assert a["coordinates"]["carb_sensitivity"] == pytest.approx(0.5)


# ------------------------------------------------------------------ collinear / near-singular
def test_perfectly_collinear_inputs_need_no_inverse_and_stay_finite():
    train = _train_frame()
    assert np.allclose(train.carbs_60, train.carbs_30)  # exactly singular 5-D covariance
    assert np.linalg.matrix_rank(np.cov(train[list(JOINT_FEATURES)].to_numpy().T)) < 5
    m = fit_joint_support(train, TD)
    assert all(math.isfinite(v) for v in (*m.lo.values(), *m.hi.values()))
    assert m.assess(_row())["status"] == "within_training_support"


def test_stable_precision_survives_near_singular_coordinates():
    rng = np.random.default_rng(1)
    x = rng.normal(size=500)
    z = np.column_stack([x, x + 1e-9 * rng.normal(size=500)])  # rank-deficient to machine precision
    mean, prec, shrink, cond = stable_precision(z)
    d = mahalanobis(z[:10], mean, prec)
    assert np.isfinite(prec).all() and np.isfinite(d).all() and 0 <= shrink <= 1 and math.isfinite(cond)


def test_conformal_threshold_quantile_and_small_sample():
    s = np.arange(1, 101, dtype=float)
    assert conformal_threshold(s, 0.05) == 96.0  # ceil(101 * 0.95) = 96th smallest
    assert conformal_threshold(np.arange(12.0), 0.01) == math.inf  # 12 calibration points cannot support 1%
    with pytest.raises(ValueError):
        conformal_threshold(np.array([]), 0.1)


# ------------------------------------------------------------------ invalid inputs
@pytest.mark.parametrize("mutate", [
    lambda r: r.pop("carbs_on_board"),
    lambda r: r.update(carbs_30=float("nan")),
    lambda r: r.update(expected_meal_rise=float("inf")),
    lambda r: r.update(carbs_60=None),
    lambda r: r.update(carbs_120="lots"),
    lambda r: r.update(carbs_on_board=-1.0),
    lambda r: r.update(carbs_30=0.0, carbs_60=0.0, carbs_120=0.0),
    lambda r: r.update(carbs_60=10.0),  # carbs_60 < carbs_30: windows not nested
    lambda r: r.update(carbs_30="60"),  # numeric string: float() would accept it; the check must not
    lambda r: r.update(carbs_on_board=True),  # bool: float(True) == 1.0; must not be treated as 1 g
])
def test_missing_nonfinite_or_invalid_inputs_are_unavailable(model, mutate):
    row = _row()
    mutate(row)
    a = model.assess(row)
    assert a["status"] == "unavailable" and a["reason"] and a["reasons"] == []


def test_fit_rejects_empty_or_nonfinite_training_rows():
    with pytest.raises(ValueError):
        fit_joint_support(_train_frame().iloc[:0], TD)
    bad = _train_frame()
    bad.loc[0, "carbs_30"] = np.nan
    with pytest.raises(ValueError):
        fit_joint_support(bad, TD)


# ------------------------------------------------------------------ boundaries and determinism
def test_boundary_uses_the_documented_tolerance(model):
    hi = model.hi["older_carbs_on_board"]
    tol = TOL["older_carbs_on_board"]
    assert model.assess(_row(older=hi))["status"] == "within_training_support"
    assert model.assess(_row(older=hi + 0.9 * tol))["status"] == "within_training_support"
    assert model.assess(_row(older=hi + 1.1 * tol))["status"] == "no_training_analogue"
    # prior meal 30-60 min earlier: training max is exactly 0 g
    assert model.hi["prior_carbs_30_60"] == 0.0
    assert model.assess(_row(prior_30_60=0.4))["status"] == "within_training_support"
    assert model.assess(_row(prior_30_60=0.6))["status"] == "no_training_analogue"


def test_fit_and_assess_are_deterministic_and_round_trip(model, tmp_path):
    again = fit_joint_support(_train_frame(), TD)
    assert again.to_dict() == model.to_dict()
    assert model.assess(_row(older=45.0)) == model.assess(_row(older=45.0))
    assert JointSupportModel.from_dict(json.loads(json.dumps(model.to_dict()))) == model
    p = tmp_path / "js.json"
    p.write_text(json.dumps({"model": model.to_dict()}))
    assert load_joint_support(p, TD)[0] == model
    assert load_joint_support(p, "other training data")[0] is None  # fitted on different data: refused
    assert load_joint_support(tmp_path / "missing.json", TD)[0] is None
    p.write_text("{not json")
    assert load_joint_support(p, TD)[0] is None
    with pytest.raises(JointSupportError):
        JointSupportModel.from_dict({"format": "something-else"})


def test_numpy_scalars_are_accepted(model):
    row = {k: np.float64(v) for k, v in _row().items()}
    assert model.assess(row)["status"] == "within_training_support"


# ------------------------------------------------------------------ reference population (format 3)
def test_joint_inputs_at_equals_feature_frame_on_every_cgm_row(small_cohort):
    """joint_inputs_at re-evaluates the meal-derived inputs; it must equal features.py wherever both exist."""
    from glucotwin.features import build_feature_frame, carb_sensitivity_prior, meal_responses, split_streams
    from glucotwin.labels import to_grid

    checked = 0
    for rec in small_cohort.records[:4]:
        obs = small_cohort.patient_observations(rec.patient_id)
        f = build_feature_frame(obs, rec)
        st = split_streams(obs)
        got = joint_inputs_at(st["meal"], meal_responses(to_grid(st["cgm"]), st["meal"]),
                              carb_sensitivity_prior(rec), f.index)
        for k in (*JOINT_FEATURES, "carb_sensitivity"):
            np.testing.assert_allclose(got[k].to_numpy(), f[k].to_numpy(float), rtol=0, atol=1e-9, err_msg=k)
        checked += len(f)
    assert checked > 1000


def test_meal_event_rows_cover_every_logged_meal_even_after_a_cgm_dropout(small_cohort):
    rec = small_cohort.records[0]
    obs = small_cohort.patient_observations(rec.patient_id)
    meals = obs[obs.kind == "meal"]
    # remove every CGM reading in the 30 min after the first meal: v2 (rows < 5 min after a meal) lost such meals
    t0 = meals.timestamp.min()
    gap = (obs.kind == "cgm") & (obs.timestamp >= t0) & (obs.timestamp < t0 + pd.Timedelta(minutes=30))
    rows = meal_event_rows(obs[~gap], rec)
    assert len(rows) == meals.timestamp.nunique()
    first = rows.loc[rows.timestamp == t0].iloc[0]
    assert first.carbs_30 >= float(meals.loc[meals.timestamp == t0, "value"].sum())  # the meal itself is included
    assert first.expected_meal_rise == pytest.approx(first.carb_sensitivity * first.carbs_on_board)


def test_reason_claims_hold_against_every_training_meal_of_the_default_cohort():
    """'than any training meal' must be literally true for the committed envelope: every logged training meal
    of the default cohort is inside the envelope it was fitted on, and the envelope has one row per meal."""
    from pathlib import Path

    from glucotwin.synth.generator import generate_cohort

    path = Path(__file__).resolve().parents[1] / "reports" / "research" / "b23_joint_support.json"
    d = json.loads(path.read_text())
    m = JointSupportModel.from_dict(d["model"])
    cohort = generate_cohort(**d["bundle"]["cohort_params"])
    rows = cohort_meal_event_rows(cohort, "train")
    train_ids = {r.patient_id for r in cohort.records if r.split == "train"}
    n_meals = cohort.observations[(cohort.observations.kind == "meal")
                                  & cohort.observations.patient_id.isin(train_ids)].groupby("patient_id").timestamp.nunique().sum()
    assert len(rows) == m.n_train_rows == n_meals
    for _, r in rows.iterrows():
        a = m.assess(r[list(JOINT_FEATURES)].astype(float).to_dict())
        assert a["status"] == "within_training_support", (r.patient_id, r.timestamp, a["reasons"])


# ------------------------------------------------------------------ engine / service / API
def _point(service):
    for pid in service.demo_patient_ids():
        for off in (30.0, 47.5, 63.0, 80.0):
            service.create_replay(pid, off)
            if service.counterfactual(pid, 60.0).primary is not None:
                return pid, off
    pytest.skip("no replay point with enough CGM data")


def test_analytic_meal_now_transform_equals_engine_scenario_row(service):
    checked = 0
    for pid in service.demo_patient_ids()[:2]:
        for off in (30.0, 63.0):
            service.create_replay(pid, off)
            eng = service.engine(pid)
            for g in (20.0, 75.0):
                t0, rows, reason = eng._counterfactual_features(g)
                if reason is not None:
                    continue
                base, scen = rows["baseline"].loc[[t0]], rows["scenario"].loc[t0]
                analytic = apply_meal_now(base, g).iloc[0]
                for k in JOINT_FEATURES:
                    assert analytic[k] == pytest.approx(float(scen[k]), abs=1e-6), (pid, off, g, k)
                assert float(scen["minutes_since_meal"]) == 0.0
                checked += 1
    assert checked >= 2


@pytest.fixture()
def small_model(trained, small_cohort):
    """Envelope fitted on the small cohort's training patients, matching the small bundle."""
    _, bundle, _, _ = trained
    return fit_joint_support(cohort_meal_event_rows(small_cohort, "train"), bundle.training_data)


def test_service_adds_joint_support_without_changing_any_forecast(service, small_model, monkeypatch):
    pid, off = _point(service)
    service.create_replay(pid, off)
    monkeypatch.setattr(service, "joint_support", None)
    monkeypatch.setattr(service, "joint_support_reason", "joint-support model not configured")
    without = service.counterfactual(pid, 60.0)
    assert without.joint_support is not None and without.joint_support.status == "unavailable"
    monkeypatch.setattr(service, "joint_support", small_model)
    with_js = service.counterfactual(pid, 60.0)
    assert with_js.joint_support.status in ("within_training_support", "no_training_analogue")
    # B-22 comparisons and legacy fields are byte-identical with and without the check
    for f in ("primary", "secondary", "delta_glucose_60mg_dl", "delta_probability", "small_meal_unreliable"):
        a, b = getattr(without, f), getattr(with_js, f)
        assert (a.model_dump() if hasattr(a, "model_dump") else a) == (b.model_dump() if hasattr(b, "model_dump") else b), f
    for leg in ("baseline", "reference", "scenario"):
        fa, fb = getattr(without, leg), getattr(with_js, leg)
        assert fa.model_dump(exclude={"forecast_id"}) == fb.model_dump(exclude={"forecast_id"}), leg
    # B-22 notes come first and unchanged; a joint note is appended only when flagged
    assert with_js.notes[:len(without.notes)] == without.notes
    extra = with_js.notes[len(without.notes):]
    assert (with_js.joint_support.status == "no_training_analogue") == bool(extra)


def test_service_flags_a_meal_larger_than_any_training_meal(service, small_model, monkeypatch):
    pid, off = _point(service)
    service.create_replay(pid, off)
    monkeypatch.setattr(service, "joint_support", small_model)
    r = service.counterfactual(pid, 300.0)
    assert r.joint_support.status == "no_training_analogue" and "meal_carbs_above" in r.joint_support.reasons
    assert any("training support, not a known error" in n for n in r.notes)


def test_api_field_is_additive_and_optional(service, small_model, monkeypatch):
    pid, off = _point(service)
    service.create_replay(pid, off)
    monkeypatch.setattr(service, "joint_support", small_model)
    client = TestClient(create_app(service))
    body = client.post(f"/api/patients/{pid}/counterfactual", json={"meal_grams": 60}).json()
    legacy = {"patient_id", "as_of", "meal_grams", "baseline", "reference", "scenario", "delta_glucose_60mg_dl",
              "delta_probability", "primary", "secondary", "small_meal_unreliable", "notes", "is_simulated",
              "disclaimer"}
    assert legacy <= body.keys() and "joint_support" in body
    assert body["joint_support"]["status"] in ("within_training_support", "no_training_analogue")
    schema = client.get("/openapi.json").json()["components"]["schemas"]
    assert "joint_support" not in schema["CounterfactualResult"].get("required", [])
    assert "JointSupportCheck" in schema


def test_committed_research_model_matches_the_default_training_data():
    """The shipped envelope was fitted on the default cohort (no request-time fitting)."""
    from pathlib import Path

    from glucotwin.evaluation.pipeline import DATASET_NAME, DATASET_VERSION
    from glucotwin.synth.generator import DEFAULT_SEED

    path = Path(__file__).resolve().parents[1] / "reports" / "research" / "b23_joint_support.json"
    d = json.loads(path.read_text())
    m = JointSupportModel.from_dict(d["model"])
    assert m.training_data.startswith(f"{DATASET_NAME} v{DATASET_VERSION}, seed {DEFAULT_SEED}, ")
    assert m.hi["prior_carbs_30_60"] == 0.0 and m.n_train_rows == d["fresh_meal_rows"]["train"]["n_rows"]
    assert m.n_train_rows == d["logged_meal_events"]["train"]  # format 3: one reference row per logged meal
