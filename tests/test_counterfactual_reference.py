"""B-22: zero-carb same-time reference for what-if meal comparisons.

These tests pin down *construction* invariants and the API contract across several held-out
patients, replay times and meal sizes. They deliberately do NOT assert how glucose "should"
respond to a meal: the served models are learned associations, and the small test cohort's
model is not the production model. Production-model behaviour is audited separately by
scripts/counterfactual_audit.py (reports/counterfactual_audit.json).

Invariants:
* the reference leg is a zero-carb meal at the same time: versus the baseline only
  ``minutes_since_meal`` changes (to 0); versus the scenario only the carb inputs differ;
* reported deltas are exactly scenario minus the named reference leg, per horizon;
* legacy fields keep their original no-meal meaning;
* reliability qualifiers follow the configured thresholds; withheld legs propagate;
* nothing is ever ingested into the twin, and repeated calls are deterministic.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from glucotwin.api.app import create_app
from glucotwin.config import COUNTERFACTUAL_RELIABLE_MIN_GRAMS, COUNTERFACTUAL_RISK_SATURATION
from glucotwin.service import compare_forecasts, counterfactual_notes

OFFSETS_H = (30.0, 47.5, 63.0, 80.0)  # different local clock times within the 4-day test cohort
GRAMS = (5.0, 29.9, 30.0, 75.0, 300.0)
CARB_FEATURES = {"carbs_30", "carbs_60", "carbs_120", "carbs_on_board", "expected_meal_rise"}


def _points(service):
    """(pid, offset) replay points on held-out patients where a what-if is not withheld."""
    out = []
    for pid in service.demo_patient_ids():
        for off in OFFSETS_H:
            service.create_replay(pid, off)
            if service.counterfactual(pid, 60.0).primary is not None:
                out.append((pid, off))
    return out


@pytest.fixture(scope="module")
def points(service):
    pts = _points(service)
    assert len({p for p, _ in pts}) >= 2 and len(pts) >= 4, f"need several patients and times, got {pts}"
    return pts


def _glucose(fc) -> dict[str, float]:
    return {str(p.horizon_min): p.glucose_mg_dl for p in fc.trajectory}


# ------------------------------------------------------------------ feature-vector validity
def test_reference_and_scenario_features_differ_only_where_intended(service, points):
    for pid, off in points:
        service.create_replay(pid, off)
        eng = service.engines[pid]
        for g in GRAMS:
            t0, rows, reason = eng._counterfactual_features(g)
            assert reason is None
            b, r, s = (rows[k].loc[t0] for k in ("baseline", "reference", "scenario"))
            assert list(b.index) == list(r.index) == list(s.index)
            changed_rb = {c for c in b.index if not np.isclose(b[c], r[c], equal_nan=True)}
            changed_sr = {c for c in b.index if not np.isclose(r[c], s[c], equal_nan=True)}
            # zero-carb meal: the meal clock resets, nothing else moves (no impossible combinations)
            assert changed_rb <= {"minutes_since_meal"}, (pid, off, g, changed_rb)
            assert r["minutes_since_meal"] == 0 and s["minutes_since_meal"] == 0
            # the scenario adds exactly g grams of carbohydrate to the carb inputs, nothing else
            assert changed_sr <= CARB_FEATURES, (pid, off, g, changed_sr)
            for c in ("carbs_30", "carbs_60", "carbs_120", "carbs_on_board"):
                assert s[c] == pytest.approx(r[c] + g, abs=1e-6), (c, pid, off, g)
            assert s["expected_meal_rise"] == pytest.approx(r["expected_meal_rise"] + r["carb_sensitivity"] * g, rel=1e-6)
            assert s["carb_sensitivity"] == r["carb_sensitivity"] == b["carb_sensitivity"]


# ------------------------------------------------------------------ reference consistency
def test_reported_deltas_are_scenario_minus_the_named_reference(service, points):
    for pid, off in points:
        service.create_replay(pid, off)
        for g in GRAMS:
            res = service.counterfactual(pid, g)
            b, r, s = _glucose(res.baseline), _glucose(res.reference), _glucose(res.scenario)
            assert res.primary.reference == "zero_carb_meal_now" and res.secondary.reference == "no_meal"
            assert res.primary.delta_glucose_mg_dl == {h: round(s[h] - r[h], 1) for h in s}
            assert res.secondary.delta_glucose_mg_dl == {h: round(s[h] - b[h], 1) for h in s}
            if res.baseline.excursion is None:
                # latest CGM > 180: the event target is undefined, so no risk comparison is reported
                assert res.reference.excursion is None and res.scenario.excursion is None
                assert res.primary.delta_probability is None and res.secondary.delta_probability is None
                assert res.primary.risk_saturated is False
            else:
                p_b, p_r, p_s = (fc.excursion.probability for fc in (res.baseline, res.reference, res.scenario))
                assert res.primary.delta_probability == round(p_s - p_r, 4)
                assert res.secondary.delta_probability == round(p_s - p_b, 4)
                assert res.primary.reference_probability == p_r and res.secondary.reference_probability == p_b
            # legacy fields keep their original no-meal meaning
            assert res.delta_glucose_60mg_dl == res.secondary.delta_glucose_mg_dl["60"]
            assert res.delta_probability == res.secondary.delta_probability
            assert res.meal_grams == g


def test_reference_leg_does_not_depend_on_meal_size_and_baseline_matches_live(service, points):
    pid, off = points[0]
    service.create_replay(pid, off)
    eng = service.engines[pid]
    legs = [eng.counterfactual_forecasts(g) for g in GRAMS]

    def sig(fc):
        d = fc.model_dump()
        d.pop("forecast_id")
        return d

    assert all(sig(x.reference) == sig(legs[0].reference) for x in legs)
    live = sig(eng.latest_forecast)
    assert all(sig(x.baseline) == live for x in legs)


def test_repeated_calls_are_deterministic_and_never_mutate_the_twin(service, points):
    pid, off = points[-1]
    service.create_replay(pid, off)
    eng = service.engines[pid]
    before = (eng.version, eng.history_frame().to_json(), len(eng.forecast_history))
    a = service.counterfactual(pid, 75.0).model_dump(exclude={"baseline", "reference", "scenario"})
    b = service.counterfactual(pid, 75.0).model_dump(exclude={"baseline", "reference", "scenario"})
    assert a == b
    assert (eng.version, eng.history_frame().to_json(), len(eng.forecast_history)) == before


# ------------------------------------------------------------------ qualifiers
def test_small_meal_flag_follows_the_configured_threshold(service, points):
    pid, off = points[0]
    service.create_replay(pid, off)
    below = service.counterfactual(pid, COUNTERFACTUAL_RELIABLE_MIN_GRAMS - 0.1)
    at = service.counterfactual(pid, COUNTERFACTUAL_RELIABLE_MIN_GRAMS)
    assert below.small_meal_unreliable is True and any("unreliable" in n for n in below.notes)
    assert at.small_meal_unreliable is False and not any("unreliable" in n for n in at.notes)


def test_risk_saturation_qualifier_uses_the_reference_leg_risk(service, points):
    pid, off = points[0]
    service.create_replay(pid, off)
    legs = service.engines[pid].counterfactual_forecasts(60.0)

    def with_p(fc, p):
        return fc.model_copy(update={"excursion": fc.excursion.model_copy(update={"probability": p})})

    hot = compare_forecasts(with_p(legs.scenario, 0.99), with_p(legs.reference, COUNTERFACTUAL_RISK_SATURATION + 0.01),
                            "zero_carb_meal_now")
    edge = compare_forecasts(with_p(legs.scenario, 0.99), with_p(legs.reference, COUNTERFACTUAL_RISK_SATURATION),
                             "zero_carb_meal_now")
    assert hot.risk_saturated is True and edge.risk_saturated is False
    assert any("above 95%" in n for n in counterfactual_notes(hot, None, small_meal=False))


def test_withheld_legs_propagate_to_comparisons_and_notes(trained, small_cohort):
    from glucotwin.service import TwinService

    _, bundle, report_path, _ = trained
    svc = TwinService(bundle, report_path=report_path, cohort=small_cohort, warmup_hours=0)
    pid = svc.demo_patient_ids()[0]
    eng = svc.engines[pid]
    base = pd.Timestamp("2026-03-05T12:00:00Z")
    eng.ingest_frame(pd.DataFrame([{"timestamp": base - pd.Timedelta(minutes=m), "kind": "cgm", "value": 110.0}
                                   for m in (300, 200, 50)]))
    legs = eng.counterfactual_forecasts(60.0)
    assert {fc.status for fc in legs} == {"insufficient_data"}
    res = svc.counterfactual(pid, 60.0)
    assert res.primary is None and res.secondary is None
    assert res.delta_glucose_60mg_dl is None and res.delta_probability is None
    assert res.notes and res.notes[0].startswith("Withheld")


# ------------------------------------------------------------------ API contract
@pytest.fixture(scope="module")
def client(service):
    return TestClient(create_app(service))


def test_api_is_backward_compatible_and_exposes_the_reference(client, service, points):
    pid, off = points[0]
    service.create_replay(pid, off)
    r = client.post(f"/api/patients/{pid}/counterfactual", json={"meal_grams": 20})
    assert r.status_code == 201
    body = r.json()
    legacy = {"patient_id", "as_of", "baseline", "scenario", "delta_glucose_60mg_dl", "delta_probability",
              "is_simulated", "disclaimer"}
    assert legacy <= body.keys()
    assert {"reference", "primary", "secondary", "small_meal_unreliable", "notes", "meal_grams"} <= body.keys()
    assert body["primary"]["reference"] == "zero_carb_meal_now" and body["secondary"]["reference"] == "no_meal"
    assert set(body["primary"]["delta_glucose_mg_dl"]) == {"30", "60", "90", "120"}
    assert body["small_meal_unreliable"] is True
    assert "not causal physiological effects" in body["disclaimer"]
    schema = client.get("/openapi.json").json()["components"]["schemas"]
    assert "CounterfactualComparison" in schema


def test_api_rejects_zero_and_out_of_range_grams(client, service):
    """The zero-carb reference is internal: clients still cannot request 0 g (or > 300 g)."""
    pid = service.demo_patient_ids()[0]
    for g in (0, 0.5, 300.5):
        r = client.post(f"/api/patients/{pid}/counterfactual", json={"meal_grams": g})
        assert r.status_code == 422
        assert isinstance(r.json()["detail"], list) and r.json()["detail"][0]["loc"][-1] == "meal_grams"
