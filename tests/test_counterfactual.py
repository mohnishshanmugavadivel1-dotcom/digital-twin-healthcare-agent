"""U1 counterfactual what-if: twin purity, baseline parity, meal responsiveness, API surface.

Invariants under test:
* the hypothetical meal is NEVER ingested — engine state, version, streams, latest
  forecast and forecast history are byte-identical after a simulation;
* the baseline leg equals the forecast the live twin would serve right now;
* the served models react to the hypothetical meal (scenario vs baseline), and
  more carbohydrates never lower the simulated 60-minute glucose;
* the endpoint is test-split-only, validates grams bounds, and labels output as
  a simulated scenario.
"""

from __future__ import annotations

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from glucotwin.api.app import create_app
from glucotwin.twin.engine import TwinEngine


def _snapshot(eng: TwinEngine) -> dict:
    """Everything a what-if simulation must leave untouched."""
    return {
        "version": eng.version,
        "ingested": eng.ingested,
        "state": eng.state.model_dump_json() if eng.state else None,
        "latest_forecast": eng.latest_forecast.model_dump_json() if eng.latest_forecast else None,
        "streams": {k: (list(map(str, s.times)), list(s.values)) for k, s in eng._streams.items()},
        "history": eng.history_frame().to_json(index=False),
        "n_forecasts": len(eng.forecast_history),
        "last_summary": eng.forecast_history[-1].model_dump_json() if eng.forecast_history else None,
    }


def _demo_engine(service) -> TwinEngine:
    return service.engines[service.demo_patient_ids()[0]]


def _traj(fc, horizon: int):
    return [p for p in fc.trajectory if p.horizon_min == horizon][0]


# ------------------------------------------------------------------ purity (Agent A)
def test_counterfactual_never_mutates_the_twin(service):
    eng = _demo_engine(service)
    before = _snapshot(eng)
    eng.counterfactual_forecast(80.0)
    assert _snapshot(eng) == before


def test_hypothetical_meal_is_not_in_the_history(service):
    eng = _demo_engine(service)
    hist_before = eng.history_frame()
    eng.counterfactual_forecast(120.0)
    hist_after = eng.history_frame()
    pd.testing.assert_frame_equal(hist_before, hist_after)


# ------------------------------------------------------------------ baseline parity (Agent A)
def test_baseline_matches_the_live_served_forecast(service):
    eng = _demo_engine(service)
    baseline, _ = eng.counterfactual_forecast(60.0)
    live = eng.latest_forecast
    assert live is not None, "warm demo engine should have served a forecast"
    assert baseline.status == "ok" and live.status == "ok"
    a = baseline.model_dump()
    b = live.model_dump()
    a.pop("forecast_id"), b.pop("forecast_id")  # fresh id per forecast by design
    assert a == b


# ------------------------------------------------------------------ responsiveness (Agent A)
def test_scenario_meal_raises_the_60min_forecast(service):
    eng = _demo_engine(service)
    baseline, scenario = eng.counterfactual_forecast(120.0)
    assert baseline.status == "ok" and scenario.status == "ok"
    assert _traj(scenario, 60).glucose_mg_dl > _traj(baseline, 60).glucose_mg_dl
    assert baseline.excursion is not None and scenario.excursion is not None
    assert scenario.excursion.probability >= baseline.excursion.probability


def test_more_carbs_never_lower_the_simulated_glucose(service):
    eng = _demo_engine(service)
    _, small = eng.counterfactual_forecast(20.0)
    _, big = eng.counterfactual_forecast(200.0)
    assert _traj(big, 60).glucose_mg_dl >= _traj(small, 60).glucose_mg_dl


def test_engine_rejects_out_of_range_grams(service):
    eng = _demo_engine(service)
    with pytest.raises(ValueError):
        eng.counterfactual_forecast(0.0)
    with pytest.raises(ValueError):
        eng.counterfactual_forecast(301.0)


def test_counterfactual_on_cold_engine_raises_value_error(trained, small_cohort):
    from glucotwin.service import TwinService

    _, bundle, report_path, _ = trained
    svc = TwinService(bundle, report_path=report_path, cohort=small_cohort, warmup_hours=0)
    pid = svc.demo_patient_ids()[0]
    svc.engines[pid].reset()  # cold twin: no observations at all
    with pytest.raises(ValueError):
        svc.engines[pid].counterfactual_forecast(60.0)


# ------------------------------------------------------------------ API (Agent B)
@pytest.fixture(scope="module")
def client(service):
    return TestClient(create_app(service))


def test_counterfactual_endpoint_returns_labelled_simulation(client, service):
    pid = service.demo_patient_ids()[0]
    r = client.post(f"/api/patients/{pid}/counterfactual", json={"meal_grams": 60})
    assert r.status_code == 201
    body = r.json()
    assert body["is_simulated"] is True
    assert "never added to the patient record" in body["disclaimer"]
    assert "Not medical advice" in body["disclaimer"]
    assert body["baseline"]["status"] == "ok" and body["scenario"]["status"] == "ok"
    s60 = [p for p in body["scenario"]["trajectory"] if p["horizon_min"] == 60][0]
    b60 = [p for p in body["baseline"]["trajectory"] if p["horizon_min"] == 60][0]
    assert s60["glucose_mg_dl"] >= b60["glucose_mg_dl"]
    assert body["delta_glucose_60mg_dl"] == round(s60["glucose_mg_dl"] - b60["glucose_mg_dl"], 1)
    if body["delta_probability"] is not None:
        assert body["delta_probability"] >= 0.0


def test_counterfactual_endpoint_validation_and_split_guard(client, service):
    pid = service.demo_patient_ids()[0]
    assert client.post(f"/api/patients/{pid}/counterfactual", json={"meal_grams": 0}).status_code == 422
    assert client.post(f"/api/patients/{pid}/counterfactual", json={"meal_grams": -5}).status_code == 422
    assert client.post(f"/api/patients/{pid}/counterfactual", json={"meal_grams": 500}).status_code == 422
    assert client.post("/api/patients/SYN-9999/counterfactual", json={"meal_grams": 60}).status_code == 404
    train_pid = next(r.patient_id for r in service.cohort.records if r.split != "test")
    r = client.post(f"/api/patients/{train_pid}/counterfactual", json={"meal_grams": 60})
    assert r.status_code == 404
    assert "test split" in r.json()["detail"]
