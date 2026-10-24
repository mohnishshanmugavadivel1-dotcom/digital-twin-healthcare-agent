"""FHIR R4 export of a synthetic patient (interoperability prototype).

The structure is also checked against the R4 4.0.1 model classes by scripts/validate_fhir_export.py.
"""

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from glucotwin.api.app import create_app
from glucotwin.contracts import LabResult, Medication
from glucotwin.fhir_export import CGM_CODE, LOINC, RXNORM, SNOMED, patient_bundle


def _resources(bundle, rtype):
    return [e["resource"] for e in bundle["entry"] if e["resource"]["resourceType"] == rtype]


def _full(record):
    lab_t = datetime(2025, 12, 20, 9, 0, tzinfo=UTC)
    return record.model_copy(update={
        "conditions": ["Type 2 diabetes mellitus", "Essential hypertension", "Dyslipidaemia"],
        "medications": [Medication(name="Metformin", drug_class="biguanide", dose="1000 mg BD"),
                        Medication(name="Glimepiride", drug_class="sulfonylurea", dose="2 mg OD"),
                        Medication(name="Insulin glargine", drug_class="basal_insulin", dose="14 U at bedtime")],
        "labs": [LabResult(name="HbA1c", value=7.5, unit="%", measured_at=lab_t),
                 LabResult(name="Fasting plasma glucose", value=140, unit="mg/dL", measured_at=lab_t),
                 LabResult(name="eGFR", value=90, unit="mL/min/1.73m2", measured_at=lab_t)],
    })


def test_bundle_structure_and_verified_codes(record):
    record = _full(record)
    t0 = datetime(2026, 1, 5, 8, 0, tzinfo=UTC)
    b = patient_bundle(record, [(t0, 101.24), (t0 + timedelta(minutes=5), 103.0)])
    assert b["resourceType"] == "Bundle" and b["type"] == "collection"
    urls = [e["fullUrl"] for e in b["entry"]]
    assert len(urls) == len(set(urls)) and all(u.startswith("urn:uuid:") for u in urls)
    (patient,) = _resources(b, "Patient")
    assert patient["identifier"][0]["value"] == record.patient_id and patient["gender"] in {"female", "male"}
    assert "birthDate" not in patient  # the record has an age only; no invented birth date
    # every reference points at the Patient entry in this Bundle, and every resource is tagged synthetic
    for e in b["entry"]:
        res = e["resource"]
        assert res["meta"]["tag"][0]["code"] == "synthetic"
        if "subject" in res:
            assert res["subject"]["reference"] == urls[0]
    cgm = [o for o in _resources(b, "Observation") if o["code"].get("coding", [{}])[0].get("code") == CGM_CODE[0]]
    assert [o["valueQuantity"]["value"] for o in cgm] == [101.2, 103.0]
    assert all(o["valueQuantity"]["system"] == "http://unitsofmeasure.org" and o["valueQuantity"]["code"] == "mg/dL"
               for o in cgm)
    codes = {(c["system"], c["code"]) for r in b["entry"] for key in ("code", "medicationCodeableConcept")
             for c in r["resource"].get(key, {}).get("coding", [])}
    allowed = {(LOINC, "99504-3"), (LOINC, "4548-4"), (LOINC, "1558-6"), (SNOMED, "44054006"),
               (SNOMED, "59621000"), (SNOMED, "370992007"), (RXNORM, "6809"), (RXNORM, "25789"),
               (RXNORM, "593411"), (RXNORM, "274783"), (RXNORM, "35296"), (RXNORM, "83367")}
    assert codes == {(LOINC, "99504-3"), (LOINC, "4548-4"), (LOINC, "1558-6"), (SNOMED, "44054006"),
                     (SNOMED, "59621000"), (SNOMED, "370992007"), (RXNORM, "6809"), (RXNORM, "25789"),
                     (RXNORM, "274783")}
    assert codes <= allowed
    assert len(_resources(b, "Condition")) == 3 and len(_resources(b, "MedicationStatement")) == 3
    # labs without a verified LOINC code are exported as text only, with a UCUM unit where one is known
    (egfr,) = [o for o in _resources(b, "Observation") if "coding" not in o["code"]]
    assert egfr["code"]["text"] == "eGFR" and egfr["valueQuantity"]["code"] == "mL/min/{1.73_m2}"
    assert b["timestamp"] == (t0 + timedelta(minutes=5)).isoformat()


def test_bundle_is_deterministic_and_rejects_naive_times(record):
    record = _full(record)
    t0 = datetime(2026, 1, 5, 8, 0, tzinfo=UTC)
    assert patient_bundle(record, [(t0, 100.0)]) == patient_bundle(record, [(t0, 100.0)])
    with pytest.raises(ValueError):
        patient_bundle(record, [(datetime(2026, 1, 5, 8, 0), 100.0)])


@pytest.fixture(scope="module")
def client(service):
    return TestClient(create_app(service))


def test_fhir_endpoint_never_exports_future_replay_data(client, service):
    pid = service.demo_patient_ids()[0]
    st = client.post("/api/replay", json={"patient_id": pid, "start_offset_hours": 12}).json()
    clock = pd.Timestamp(st["clock"])
    r1 = client.get(f"/api/patients/{pid}/fhir", params={"hours": 2})
    assert r1.status_code == 200
    b = r1.json()
    times = [pd.Timestamp(e["resource"]["effectiveDateTime"]) for e in b["entry"]
             if e["resource"]["resourceType"] == "Observation"
             and e["resource"]["code"].get("coding", [{}])[0].get("code") == CGM_CODE[0]]
    assert times and max(times) <= clock and min(times) > max(times) - pd.Timedelta(hours=2)
    assert client.get(f"/api/patients/{pid}/fhir", params={"hours": 2}).json() == b
    assert client.get(f"/api/patients/{pid}/fhir", params={"hours": 48}).status_code == 422
    assert client.get("/api/patients/SYN-9999/fhir").status_code == 404
    client.delete(f"/api/replay/{st['session_id']}")


def _forecast(lows: bool):
    from glucotwin.contracts import ExcursionRisk, Forecast, ForecastPoint

    t0 = datetime(2026, 3, 1, 8, 0, tzinfo=UTC)
    pts = [ForecastPoint(horizon_min=h, timestamp=t0 + timedelta(minutes=h), glucose_mg_dl=110.0,
                         lower_mg_dl=(65.0 if lows and h >= 90 else 95.0), upper_mg_dl=130.0) for h in (30, 60, 90, 120)]
    ex = ExcursionRisk(event_definition="glucose > 180 mg/dL within 120 min", horizon_min=120, probability=0.4237,
                       alert_threshold=0.35, alert=True, risk_band="moderate", top_factors=[])
    return Forecast(forecast_id="f", patient_id="SYN-0001", issued_at=t0, model_version="test", status="ok",
                    current_glucose_mg_dl=110.0, trajectory=pts, excursion=ex)


def test_risk_assessment_probability_and_qualitative_low_watch(record):
    rec = record.model_copy(update={"medications": [Medication(name="Glimepiride", drug_class="sulfonylurea")]})
    b = patient_bundle(rec, [], forecast=_forecast(lows=True))
    (ra,) = _resources(b, "RiskAssessment")
    hyper, low = ra["prediction"]
    assert hyper["probabilityDecimal"] == 0.424 and "180" in hyper["outcome"]["text"]
    # the lower-bound watch never carries a probability
    assert not any(k.startswith("probability") or k == "qualitativeRisk" for k in low)
    assert "NOT a probability" in low["rationale"] and "+90 min" in low["rationale"] and "Glimepiride" in low["rationale"]
    assert ra["subject"]["reference"] == b["entry"][0]["fullUrl"]


def test_risk_assessment_absent_without_forecast_and_no_watch_when_bounds_high(record):
    assert _resources(patient_bundle(record, []), "RiskAssessment") == []
    (ra,) = _resources(patient_bundle(record, [], forecast=_forecast(lows=False)), "RiskAssessment")
    assert len(ra["prediction"]) == 1
