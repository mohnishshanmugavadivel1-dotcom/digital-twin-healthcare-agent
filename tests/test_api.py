import pandas as pd
import pytest
from fastapi.testclient import TestClient

from glucotwin.api.app import create_app


@pytest.fixture(scope="module")
def client(service):
    return TestClient(create_app(service))


def test_health(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok" and body["data_is_synthetic"] is True


def test_patient_list_only_exposes_test_split(client, service):
    pats = client.get("/api/patients").json()
    test_ids = {r.patient_id for r in service.cohort.records if r.split == "test"}
    assert {p["patient_id"] for p in pats} == test_ids
    assert client.get("/api/patients?split=bogus").status_code == 422


def test_unknown_patient_is_404(client):
    assert client.get("/api/patients/SYN-9999").status_code == 404
    assert client.get("/api/patients/SYN-9999/state").status_code == 404


def test_replay_never_reveals_future(client, service):
    pid = service.demo_patient_ids()[0]
    st = client.post("/api/replay", json={"patient_id": pid, "start_offset_hours": 12}).json()
    sid = st["session_id"]
    for _ in range(3):
        st = client.post(f"/api/replay/{sid}/step", json={"minutes": 30}).json()
    clock = pd.Timestamp(st["clock"])
    obs = client.get(f"/api/patients/{pid}/observations").json()
    assert max(pd.Timestamp(o["timestamp"]) for o in obs) <= clock
    fcs = client.get(f"/api/patients/{pid}/forecasts").json()
    assert max(pd.Timestamp(f["issued_at"]) for f in fcs) <= clock
    assert st["state"]["as_of"] <= st["clock"]
    assert client.delete(f"/api/replay/{sid}").status_code == 204
    assert client.get(f"/api/replay/{sid}").status_code == 404


def test_replay_finishes(client, service):
    pid = service.demo_patient_ids()[0]
    st = client.post("/api/replay", json={"patient_id": pid, "duration_hours": 1}).json()
    st = client.post(f"/api/replay/{st['session_id']}/step", json={"minutes": 120}).json()
    assert st["finished"] is True


def test_ingest_endpoint_validates(client, service):
    pid = service.demo_patient_ids()[-1]
    state = client.get(f"/api/patients/{pid}/state").json()
    t = pd.Timestamp(state["as_of"]) + pd.Timedelta(minutes=5)
    body = {"observations": [
        {"patient_id": pid, "timestamp": t.isoformat(), "kind": "cgm", "value": 150},
        {"patient_id": pid, "timestamp": (t + pd.Timedelta(minutes=5)).isoformat(), "kind": "cgm", "value": 5000},
    ]}
    res = client.post(f"/api/patients/{pid}/observations", json=body).json()
    assert res["accepted"] == 1 and res["rejected"] == 1
    assert res["forecast"]["status"] in ("ok", "insufficient_data")
    bad = {"observations": [{"patient_id": pid, "timestamp": "2026-03-02T10:00:00", "kind": "cgm", "value": 100}]}
    assert client.post(f"/api/patients/{pid}/observations", json=bad).status_code == 422


def test_model_card_and_evaluation(client):
    card = client.get("/api/model").json()
    assert card["event_model"] == "logistic_regression"
    rep = client.get("/api/evaluation").json()
    assert rep["dataset"]["is_synthetic"] is True
    assert {t["model"] for t in rep["trajectory"]} >= {"persistence", "damped_trend"}


def test_replay_limited_to_held_out_patients(client, service):
    train_pid = next(r.patient_id for r in service.cohort.records if r.split == "train")
    r = client.post("/api/replay", json={"patient_id": train_pid})
    assert r.status_code == 404 and "test patient" in r.json()["detail"]


def test_replay_bounds_rejected_not_500(client, service):
    pid = service.demo_patient_ids()[0]
    assert client.post("/api/replay", json={"patient_id": pid, "start_offset_hours": 1e12}).status_code == 422
    assert client.post("/api/replay", json={"patient_id": pid, "duration_hours": 1e15}).status_code == 422


def test_step_past_end_is_safe_and_idempotent(client, service):
    """Stepping beyond the session end must clamp, never rewind, error, or resurrect data."""
    pid = service.demo_patient_ids()[0]
    st = client.post("/api/replay", json={"patient_id": pid, "duration_hours": 1}).json()
    sid = st["session_id"]
    st1 = client.post(f"/api/replay/{sid}/step", json={"minutes": 120}).json()
    assert st1["finished"] is True
    st2 = client.post(f"/api/replay/{sid}/step", json={"minutes": 30}).json()
    assert st2["finished"] is True and st2["clock"] == st1["clock"]
    assert st2["state"]["observations_ingested"] == st1["state"]["observations_ingested"]
    assert client.delete(f"/api/replay/{sid}").status_code == 204
    assert client.delete(f"/api/replay/{sid}").status_code == 404


def test_one_active_replay_per_patient(client, service):
    """A new replay for the same patient supersedes the previous session (no leaked sessions)."""
    pid = service.demo_patient_ids()[0]
    s1 = client.post("/api/replay", json={"patient_id": pid, "duration_hours": 1}).json()["session_id"]
    s2 = client.post("/api/replay", json={"patient_id": pid, "duration_hours": 1}).json()["session_id"]
    assert s1 != s2
    assert client.get(f"/api/replay/{s1}").status_code == 404
    assert client.get(f"/api/replay/{s2}").status_code == 200
    assert client.delete(f"/api/replay/{s2}").status_code == 204
