"""Research twin curve and walk effect, AGP summary, and FHIR Bundle ingestion (validation only)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from glucotwin.agp import agp_summary
from glucotwin.api.app import create_app
from glucotwin.fhir_export import patient_bundle
from glucotwin.fhir_ingest import LAB_GLUCOSE_WARNING, MMOL_TO_MG_DL, parse_bundle
from glucotwin.service import compare_forecasts
from glucotwin.twin import response_curve as rc
from glucotwin.twin_validity_research import paired_meal_delta, paired_walk_delta, reconstruct

REPO = Path(__file__).resolve().parents[1]
T0 = datetime(2026, 3, 2, 8, 0, tzinfo=UTC)


# ----------------------------------------------------------------------------- research curve and walk effect
def test_served_coefficients_match_the_research_reports():
    d = json.loads((REPO / "reports/research/twin_and_whatif_validation.json").read_text())
    sec = d["D_train_fitted_validation_selected_curve"]
    assert sec["validation"]["selected"] == "median_cal"
    for h in rc.HORIZONS:
        assert rc.CURVE_ALPHA[h] == sec["validation"]["selected_alpha"][str(h)]
        assert rc.CURVE_SHAPE[h] == sec["curve_shape"]["median"][str(h)]
        assert rc.CURVE_TEST_MAE[h] == round(sec["test_all_grams"][str(h)]["curve"]["mae"], 1)
    w = json.loads((REPO / "reports/research/walk_whatif_validation.json").read_text())
    assert w["served_coefficients"]["kind"] == "glucose_scaled"
    assert w["walk"]["total_steps"] == rc.WALK["steps"] and w["walk"]["minutes"] == rc.WALK["minutes"]
    for h in rc.HORIZONS:
        assert rc.WALK_BETA[h] == w["served_coefficients"]["beta_per_mg_dl"][str(h)]
        assert rc.WALK_TEST_MAE[h] == round(w["test"][str(h)]["selected"]["mae"], 1)


def test_twin_curve_arithmetic_and_tested_range_flags():
    e = rc.twin_curve_estimate(40, 1.5, 12, 100.0)
    for h in rc.HORIZONS:
        assert e.delta_glucose_mg_dl[str(h)] == round(rc.CURVE_K[h] * 40 * 1.5, 1)
        assert e.walk_delta_glucose_mg_dl[str(h)] == round(rc.WALK_BETA[h] * 100.0, 1) < 0
        assert e.with_walk_delta_glucose_mg_dl[str(h)] == round(
            e.delta_glucose_mg_dl[str(h)] + e.walk_delta_glucose_mg_dl[str(h)], 1)
    assert e.within_tested_range and not e.outside_tested_reasons
    assert "not the served forecast" in e.caveat and "not advice" in e.caveat
    out = rc.twin_curve_estimate(300, 1.5, 12, 220.0)
    assert not out.within_tested_range and len(out.outside_tested_reasons) == 2
    no_cgm = rc.twin_curve_estimate(40, 1.5, 12, None)
    assert no_cgm.walk_delta_glucose_mg_dl is None and not no_cgm.within_tested_range
    assert rc.twin_curve_estimate(40, None, 0, 100.0) is None


def test_counterfactual_carries_twin_curve_without_changing_the_tree_deltas(service):
    pid = service.demo_patient_ids()[0]
    service.create_replay(pid, 30.0)
    r = service.counterfactual(pid, 40)
    st = service.engine(pid).state
    assert r.twin_curve is not None
    assert r.twin_curve.carb_sensitivity_mg_dl_per_g == st.personal.carb_sensitivity_mg_dl_per_g
    assert r.twin_curve.latest_cgm_mg_dl == st.last_glucose_mg_dl
    # the tree-model comparison is still exactly scenario leg minus zero-carb leg; the curve does not touch it
    assert r.primary == compare_forecasts(r.scenario, r.reference, "zero_carb_meal_now")
    assert service.engine(pid).state == st  # the twin is unchanged


def test_paired_walk_delta_is_zero_without_a_walk_and_lowers_glucose_with_one():
    inp, _ = reconstruct(3, 2, 11)
    pidx, start, grams = np.array([0, 1, 2]), np.array([600, 700, 800]), np.full(3, 40.0)
    zero = paired_walk_delta(inp, pidx, start, grams, walk_steps_per_min=0.0)
    assert np.all(zero == 0.0)
    w = paired_walk_delta(inp, pidx, start, grams)
    assert np.all(w[:, :16] == 0.0)  # nothing changes before the walk starts at +15 min
    assert np.all(w[:, 60] < 0) and np.all(w[:, 120] < 0)


def test_demo_example_ground_truth():
    """README / deck example: SYN-0039, 35 g at 07:55 local (2026-03-08 02:25 UTC), paired-simulator truth."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("bp", REPO / "scripts/build_presentation.py")
    bp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bp)
    inp, plasma = reconstruct(60, 14, 20261017)  # the frozen cohort (bundle.cohort_params)
    start_utc = datetime(2026, 3, 2, 0, 0) - timedelta(minutes=330)
    minute = int((datetime(2026, 3, 8, 2, 25) - start_utc).total_seconds() // 60)
    d = paired_meal_delta(inp, plasma, np.array([38]), np.array([minute]), np.array([35.0]))  # index 38 = SYN-0039
    assert [round(float(d[0, h]), 1) for h in (30, 60, 120)] == [9.1, 40.9, bp.DEMO_TRUTH_120]


# ----------------------------------------------------------------------------- AGP
def test_agp_metrics_gmi_and_sufficiency():
    times = pd.date_range(T0, periods=14 * 288, freq="5min")
    values = np.where(np.arange(times.size) % 10 == 0, 200.0, 100.0)  # 10% above 180
    s = agp_summary("SYN-0001", times, values, times[-1], 330)
    assert s.n_readings == times.size and s.sufficient
    assert s.tir_70_180_pct == 90.0 and s.tar_181_250_pct == 10.0 and s.tbr_54_69_pct == 0.0
    assert s.gmi_pct == round(3.31 + 0.02392 * values.mean(), 1)
    assert len(s.hourly) == 24 and all(h.p5 <= h.p50 <= h.p95 for h in s.hourly)
    short = agp_summary("SYN-0001", times[:288 * 3], values[:288 * 3], times[288 * 3 - 1], 330)
    assert not short.sufficient and short.days_with_data < 14
    # readings after as_of are never used
    later = agp_summary("SYN-0001", times, values, times[100], 330)
    assert later.n_readings == 101


# ----------------------------------------------------------------------------- FHIR ingestion
def _obs(code: str, value, unit: str, ts: str = "2026-03-02T08:00:00+05:30", status: str = "final") -> dict:
    return {"resource": {"resourceType": "Observation", "status": status,
                         "code": {"coding": [{"system": "http://loinc.org", "code": code}]},
                         "effectiveDateTime": ts, "valueQuantity": {"value": value, "unit": unit, "code": unit}}}


def test_round_trip_of_our_own_export(record):
    cgm = [(T0 + timedelta(minutes=5 * i), 100.0 + i) for i in range(12)]
    b = patient_bundle(record, cgm)
    r = parse_bundle(b)
    assert r.patient_id == record.patient_id and r.counts["cgm"] == 12
    assert [o.value for o in r.observations] == [v for _, v in cgm]
    assert all(o.unit == "mg/dL" and o.source == "fhir:99504-3" for o in r.observations)
    assert r.entries == 13 and not r.skipped  # Patient + 12 CGM (this test record has no lab list)
    assert r.ingested is False and not r.warnings


def test_codes_units_conversion_and_skip_reasons():
    b = {"resourceType": "Bundle", "type": "collection", "entry": [
        _obs("14749-6", 7.0, "mmol/L"),                      # lab glucose code, converted + warning
        _obs("8867-4", 72, "/min"),                          # heart rate
        _obs("4548-4", 7.2, "%"),                            # HbA1c -> labs
        _obs("99504-3", 120, "mg/dL", ts="2026-03-02T08:05:00"),  # no time zone
        _obs("99504-3", 900, "mg/dL"),                       # implausible
        _obs("99504-3", 120, "mg/dL", status="entered-in-error"),
        _obs("2339-0", 120, "mg/dL"),                        # unsupported code
        _obs("8867-4", 72, "mmHg"),                          # wrong unit
        {"resource": {"resourceType": "Encounter"}},
    ]}
    r = parse_bundle(b, patient_id="SYN-0042")
    kinds = {o.kind.value: o for o in r.observations}
    assert kinds["cgm"].value == round(7.0 * MMOL_TO_MG_DL, 1) and kinds["cgm"].source == "fhir:14749-6"
    assert kinds["heart_rate"].value == 72 and kinds["heart_rate"].unit == "bpm"
    assert r.labs[0].value == 7.2 and r.warnings == [LAB_GLUCOSE_WARNING]
    reasons = " | ".join(s.reason for s in r.skipped)
    for frag in ("time-zone", "outside", "entered-in-error", "no supported LOINC", "not beats/min", "not an Observation"):
        assert frag in reasons, frag
    assert len(r.skipped) == 6 and r.entries == 9


def test_bad_bundles_are_rejected():
    with pytest.raises(ValueError, match="Bundle"):
        parse_bundle({"resourceType": "Patient"})
    with pytest.raises(ValueError, match="synthetic patient ID"):
        parse_bundle({"resourceType": "Bundle", "entry": [_obs("99504-3", 100, "mg/dL")]})


@pytest.fixture(scope="module")
def client(service):
    return TestClient(create_app(service))


def test_fhir_bundle_and_agp_endpoints(client, service):
    pid = service.demo_patient_ids()[0]
    client.post("/api/replay", json={"patient_id": pid, "start_offset_hours": 30})
    eng = service.engine(pid)
    before = (eng.version, eng.ingested)
    exported = client.get(f"/api/patients/{pid}/fhir", params={"hours": 2}).json()
    r = client.post("/api/fhir/Bundle", json=exported)
    assert r.status_code == 200 and r.json()["counts"]["cgm"] > 0 and r.json()["ingested"] is False
    assert (eng.version, eng.ingested) == before  # validation only
    assert client.post("/api/fhir/Bundle", json={"resourceType": "Patient"}).status_code == 422
    assert client.post("/api/fhir/Bundle", params={"patient_id": "bad"},
                       json={"resourceType": "Bundle", "entry": []}).status_code == 422
    a = client.get(f"/api/patients/{pid}/agp")
    assert a.status_code == 200 and a.json()["n_readings"] > 0 and a.json()["gmi_pct"] is not None
    assert client.get(f"/api/patients/{pid}/agp", params={"days": 30}).status_code == 422
