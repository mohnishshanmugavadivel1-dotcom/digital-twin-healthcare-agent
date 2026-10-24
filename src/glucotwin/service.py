"""Application service: owns the demo cohort, one TwinEngine per patient and replay sessions.

Persistence is deliberately in-memory for v0.1: the cohort is regenerated
deterministically from the seed stored in the model bundle, so a restart
reproduces the exact same demo. (See docs/DECISIONS.md, ADR-003.)
"""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from glucotwin.contracts import (
    EvaluationReport,
    PatientRecord,
    PatientSummary,
    ReplayStatus,
)
from glucotwin.models.bundle import ModelBundle
from glucotwin.synth.generator import Cohort, generate_cohort
from glucotwin.twin.engine import TwinEngine

log = logging.getLogger(__name__)


class NotFound(KeyError):
    pass


@dataclass
class ReplaySession:
    session_id: str
    patient_id: str
    start: pd.Timestamp
    end: pd.Timestamp
    clock: pd.Timestamp
    replayed: int = 0


class TwinService:
    def __init__(self, bundle: ModelBundle, report_path: Path | None = None, cohort: Cohort | None = None,
                 warmup_hours: float = 24.0):
        self.bundle = bundle
        self.report_path = report_path
        # Regenerate exactly the cohort the bundle was trained on, so the patient-level split
        # (and therefore "test patients were never seen in training") holds for the demo.
        self.cohort = cohort if cohort is not None else generate_cohort(**(bundle.cohort_params or {}))
        self.lock = threading.RLock()
        self.engines: dict[str, TwinEngine] = {r.patient_id: TwinEngine(r, bundle) for r in self.cohort.records}
        self.sessions: dict[str, ReplaySession] = {}
        self._obs_by_patient = {pid: g.reset_index(drop=True) for pid, g in self.cohort.observations.groupby("patient_id")}
        for pid in self.demo_patient_ids():
            self._warm(pid, warmup_hours)
        log.info("service ready: %d demo patients, model %s", len(self.demo_patient_ids()), bundle.model_version)

    # ---------------------------------------------------------------- queries
    def demo_patient_ids(self) -> list[str]:
        """Only held-out TEST patients are exposed in the demo (never seen during training)."""
        return [r.patient_id for r in self.cohort.records if r.split == "test"]

    def record(self, pid: str) -> PatientRecord:
        if pid not in self.engines:
            raise NotFound(pid)
        return self.engines[pid].record

    def engine(self, pid: str) -> TwinEngine:
        if pid not in self.engines:
            raise NotFound(pid)
        return self.engines[pid]

    def summaries(self, split: str | None = "test") -> list[PatientSummary]:
        out = []
        for rec in self.cohort.records:
            if split and rec.split != split:
                continue
            eng = self.engines[rec.patient_id]
            obs = self._obs_by_patient[rec.patient_id]
            fc = eng.latest_forecast
            out.append(PatientSummary(
                patient_id=rec.patient_id, display_name=rec.display_name, age_years=rec.age_years, sex=rec.sex,
                hba1c_percent=rec.hba1c_percent, split=rec.split,
                data_start=obs["timestamp"].min().to_pydatetime(), data_end=obs["timestamp"].max().to_pydatetime(),
                latest_risk_probability=fc.excursion.probability if fc and fc.excursion else None,
                latest_glucose_mg_dl=eng.state.last_glucose_mg_dl if eng.state else None,
            ))
        return out

    def evaluation(self) -> EvaluationReport:
        if not self.report_path or not self.report_path.exists():
            raise NotFound("evaluation report")
        return EvaluationReport.model_validate_json(self.report_path.read_text())

    # ----------------------------------------------------------------- replay
    def _warm(self, pid: str, hours: float) -> pd.Timestamp:
        obs = self._obs_by_patient[pid]
        start = obs["timestamp"].min().floor("5min")
        clock = start + pd.Timedelta(hours=hours)
        eng = self.engines[pid]
        eng.reset()
        eng.ingest_frame(obs[obs["timestamp"] <= clock], forecast_mode="last")
        return clock

    def create_replay(self, pid: str, start_offset_hours: float = 24.0, duration_hours: float | None = None) -> ReplayStatus:
        with self.lock:
            if pid not in self.engines:
                raise NotFound(pid)
            # one active session per patient: creating a new one supersedes old ones
            for sid in [s for s, sess in self.sessions.items() if sess.patient_id == pid]:
                del self.sessions[sid]
            obs = self._obs_by_patient[pid]
            clock = self._warm(pid, start_offset_hours)
            end = obs["timestamp"].max()
            if duration_hours is not None:
                end = min(end, clock + pd.Timedelta(hours=duration_hours))
            sess = ReplaySession(session_id=uuid.uuid4().hex[:10], patient_id=pid, start=clock, end=end, clock=clock)
            self.sessions[sess.session_id] = sess
            return self._status(sess)

    def session(self, sid: str) -> ReplaySession:
        if sid not in self.sessions:
            raise NotFound(sid)
        return self.sessions[sid]

    def step_replay(self, sid: str, minutes: int) -> ReplayStatus:
        with self.lock:
            sess = self.session(sid)
            if sess.clock >= sess.end:
                return self._status(sess)
            new_clock = min(sess.clock + pd.Timedelta(minutes=minutes), sess.end)
            obs = self._obs_by_patient[sess.patient_id]
            chunk = obs[(obs["timestamp"] > sess.clock) & (obs["timestamp"] <= new_clock)]
            if not chunk.empty:
                self.engines[sess.patient_id].ingest_frame(chunk, forecast_mode="every")
            sess.replayed += len(chunk)
            sess.clock = new_clock
            return self._status(sess)

    def delete_replay(self, sid: str) -> None:
        with self.lock:
            self.session(sid)
            del self.sessions[sid]

    def replay_status(self, sid: str) -> ReplayStatus:
        return self._status(self.session(sid))

    def _status(self, sess: ReplaySession) -> ReplayStatus:
        eng = self.engines[sess.patient_id]
        return ReplayStatus(
            session_id=sess.session_id, patient_id=sess.patient_id, clock=sess.clock.to_pydatetime(),
            start=sess.start.to_pydatetime(), end=sess.end.to_pydatetime(), finished=sess.clock >= sess.end,
            observations_replayed=sess.replayed, state=eng.state, forecast=eng.latest_forecast,
        )
