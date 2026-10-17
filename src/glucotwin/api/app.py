"""FastAPI application (contract v0.1). All routes are under /api; the built dashboard,
if present at frontend/dist, is served from /."""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from glucotwin.contracts import (
    SCHEMA_VERSION,
    EvaluationReport,
    Forecast,
    ForecastSummary,
    HealthStatus,
    IngestResult,
    ModelCard,
    Observation,
    ObservationBatch,
    ObservationKind,
    PatientRecord,
    PatientSummary,
    ReplayCreate,
    ReplayStatus,
    ReplayStep,
    TwinState,
)
from glucotwin.models.bundle import ModelBundle
from glucotwin.service import NotFound, TwinService

log = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_or_train_bundle(artifacts: Path, reports: Path) -> ModelBundle:
    path = artifacts / "model_bundle.pkl"
    if path.exists():
        return ModelBundle.load(path)
    log.warning("no model bundle at %s; training one now (deterministic, ~1 min)", path)
    from glucotwin.evaluation.pipeline import run_pipeline

    _, bundle = run_pipeline(report_path=reports / "evaluation_report.json", bundle_path=path)
    return bundle


def build_router(svc: TwinService) -> APIRouter:
    r = APIRouter(prefix="/api")

    @r.get("/health", response_model=HealthStatus)
    def health():
        return HealthStatus(status="ok", schema_version=SCHEMA_VERSION, model_version=svc.bundle.model_version,
                            patients_available=len(svc.demo_patient_ids()), data_is_synthetic=True)

    @r.get("/patients", response_model=list[PatientSummary])
    def list_patients(split: str | None = Query("test", pattern="^(train|validation|test)$")):
        return svc.summaries(split)

    @r.get("/patients/{pid}", response_model=PatientRecord)
    def get_patient(pid: str):
        return svc.record(pid)

    @r.get("/patients/{pid}/observations", response_model=list[Observation])
    def get_observations(pid: str, kind: ObservationKind | None = None, since: datetime | None = None,
                         limit: int = Query(2000, ge=1, le=20000)):
        """Observations the twin has received so far (never future data in a replay)."""
        eng = svc.engine(pid)
        with svc.lock:
            hist = eng.history_frame(pd.Timestamp(since) if since else None)
        if kind is not None:
            hist = hist[hist["kind"] == kind.value]
        hist = hist.tail(limit)
        return [Observation(patient_id=pid, timestamp=t.to_pydatetime(), kind=ObservationKind(k), value=v)
                for t, k, v in zip(hist["timestamp"], hist["kind"], hist["value"], strict=True)]

    @r.post("/patients/{pid}/observations", response_model=IngestResult)
    def post_observations(pid: str, batch: ObservationBatch):
        eng = svc.engine(pid)
        with svc.lock:
            return eng.ingest(batch.observations, forecast_mode="every")

    @r.get("/patients/{pid}/state", response_model=TwinState)
    def get_state(pid: str):
        eng = svc.engine(pid)
        if eng.state is None:
            raise HTTPException(404, "twin has no observations yet")
        return eng.state

    @r.get("/patients/{pid}/forecast", response_model=Forecast)
    def get_forecast(pid: str):
        eng = svc.engine(pid)
        if eng.latest_forecast is None:
            raise HTTPException(404, "no forecast issued yet")
        return eng.latest_forecast

    @r.get("/patients/{pid}/forecasts", response_model=list[ForecastSummary])
    def get_forecasts(pid: str, since: datetime | None = None, limit: int = Query(1000, ge=1, le=5000)):
        eng = svc.engine(pid)
        hist = eng.forecast_history
        if since is not None:
            hist = [f for f in hist if f.issued_at > since]
        return hist[-limit:]

    @r.post("/replay", response_model=ReplayStatus, status_code=201)
    def create_replay(body: ReplayCreate):
        return svc.create_replay(body.patient_id, body.start_offset_hours, body.duration_hours)

    @r.get("/replay/{sid}", response_model=ReplayStatus)
    def get_replay(sid: str):
        return svc.replay_status(sid)

    @r.post("/replay/{sid}/step", response_model=ReplayStatus)
    def step_replay(sid: str, body: ReplayStep):
        return svc.step_replay(sid, body.minutes)

    @r.delete("/replay/{sid}", status_code=204)
    def delete_replay(sid: str):
        svc.delete_replay(sid)

    @r.get("/model", response_model=ModelCard)
    def model_card():
        return svc.bundle.card()

    @r.get("/evaluation", response_model=EvaluationReport)
    def evaluation():
        return svc.evaluation()

    return r


def create_app(service: TwinService | None = None) -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if service is None:
        artifacts = Path(os.environ.get("GLUCOTWIN_ARTIFACTS", REPO_ROOT / "artifacts"))
        reports = Path(os.environ.get("GLUCOTWIN_REPORTS", REPO_ROOT / "reports"))
        bundle = _load_or_train_bundle(artifacts, reports)
        service = TwinService(bundle, report_path=reports / "evaluation_report.json")
    app = FastAPI(title="GlucoTwin API", version=SCHEMA_VERSION,
                  description="Research prototype on synthetic data. Not a medical device.")
    app.state.service = service

    @app.exception_handler(NotFound)
    async def _not_found(_: Request, exc: NotFound):
        return JSONResponse(status_code=404, content={"detail": f"not found: {exc.args[0] if exc.args else ''}"})

    app.include_router(build_router(service))
    dist = REPO_ROOT / "frontend" / "dist"
    if dist.exists():
        app.mount("/", StaticFiles(directory=dist, html=True), name="dashboard")
    return app
