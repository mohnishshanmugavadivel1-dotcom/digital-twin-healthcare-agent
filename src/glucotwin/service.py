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

from glucotwin.config import COUNTERFACTUAL_RELIABLE_MIN_GRAMS, COUNTERFACTUAL_RISK_SATURATION
from glucotwin.contracts import (
    CounterfactualComparison,
    CounterfactualResult,
    EvaluationReport,
    Forecast,
    JointSupportCheck,
    PatientRecord,
    PatientSummary,
    ReplayStatus,
    TwinCurveEstimate,
)
from glucotwin.joint_support import CAVEAT, JOINT_FEATURES, load_joint_support
from glucotwin.models.bundle import ModelBundle
from glucotwin.synth.generator import Cohort, generate_cohort
from glucotwin.twin.engine import TwinEngine
from glucotwin.twin.response_curve import twin_curve_estimate

log = logging.getLogger(__name__)


class NotFound(KeyError):
    pass


COMPARISON_LABELS = {
    "zero_carb_meal_now": "vs a zero-carb meal at the same time (isolates the carb content)",
    "no_meal": "vs no meal (also includes the model's learned meal-timing expectation)",
}


def compare_forecasts(scenario: Forecast, reference: Forecast, kind: str) -> CounterfactualComparison | None:
    """Scenario minus reference per horizon; None when either leg was withheld."""
    if scenario.status != "ok" or reference.status != "ok":
        return None
    ref = {p.horizon_min: p.glucose_mg_dl for p in reference.trajectory}
    deltas = {str(p.horizon_min): round(p.glucose_mg_dl - ref[p.horizon_min], 1)
              for p in scenario.trajectory if p.horizon_min in ref}
    p_ref = reference.excursion.probability if reference.excursion else None
    dp = (round(scenario.excursion.probability - p_ref, 4)
          if scenario.excursion is not None and p_ref is not None else None)
    return CounterfactualComparison(
        reference=kind, label=COMPARISON_LABELS[kind], delta_glucose_mg_dl=deltas, delta_probability=dp,
        reference_probability=p_ref, risk_saturated=p_ref is not None and p_ref > COUNTERFACTUAL_RISK_SATURATION,
    )


def counterfactual_notes(primary: CounterfactualComparison | None, secondary: CounterfactualComparison | None,
                         small_meal: bool) -> list[str]:
    """Plain-language qualifiers shown next to a what-if result."""
    if primary is None:
        return ["Withheld: not enough recent CGM data for a reliable what-if at this moment."]
    notes = []
    if small_meal:
        notes.append(f"Meals under {COUNTERFACTUAL_RELIABLE_MIN_GRAMS:g} g are unreliable in this model: few training "
                     "meals are that small and the audited small-meal differences are unstable.")
    if primary.risk_saturated:
        notes.append("Starting risk is already above 95%, so the risk change is not informative.")
    if secondary is not None:
        # reference-vs-baseline: what logging *any* meal now does on its own in these models
        parts = []
        g_s, g_p = secondary.delta_glucose_mg_dl.get("60"), primary.delta_glucose_mg_dl.get("60")
        if g_s is not None and g_p is not None and abs(g_s - g_p) >= 2.0:
            parts.append(f"the +60-min forecast by {g_s - g_p:+.1f} mg/dL")
        if (secondary.delta_probability is not None and primary.delta_probability is not None
                and abs(secondary.delta_probability - primary.delta_probability) >= 0.05):
            parts.append(f"the risk by {100 * (secondary.delta_probability - primary.delta_probability):+.0f} points")
        if parts:
            notes.append("Logging any meal now (even zero-carb) shifts " + " and ".join(parts) + " on its own: a learned "
                         "meal-timing association, not physiology. That is why the no-meal comparison differs.")
    return notes


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
                 warmup_hours: float = 24.0, joint_support_path: Path | None = None):
        self.bundle = bundle
        self.report_path = report_path
        # B-23 joint training-support envelope (optional; a missing or mismatched file only disables the check)
        self.joint_support, self.joint_support_reason = load_joint_support(joint_support_path, bundle.training_data)
        if self.joint_support is None and joint_support_path is not None:
            log.warning("joint-support check disabled: %s", self.joint_support_reason)
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
        clock = (start + pd.Timedelta(hours=hours)).round("5min")  # stay on the CGM grid for fractional offsets
        eng = self.engines[pid]
        eng.reset()
        eng.ingest_frame(obs[obs["timestamp"] <= clock], forecast_mode="last")
        return clock

    def create_replay(self, pid: str, start_offset_hours: float = 24.0, duration_hours: float | None = None) -> ReplayStatus:
        with self.lock:
            if pid not in self.engines:
                raise NotFound(pid)
            if pid not in self.demo_patient_ids():
                # replaying a train/validation patient would show in-sample predictions as if held out
                raise NotFound(f"{pid} is not a held-out test patient; replay is limited to the test split")
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

    def counterfactual(self, pid: str, meal_grams: float) -> CounterfactualResult:
        """What-if meal simulation on a held-out demo patient. Never mutates the twin."""
        with self.lock:
            if pid not in self.engines:
                raise NotFound(pid)
            if pid not in self.demo_patient_ids():
                # a what-if on train/validation patients would present in-sample model behaviour as held out
                raise NotFound(f"{pid} is not a held-out test patient; what-if is limited to the test split")
            eng = self.engines[pid]
            legs = eng.counterfactual_forecasts(meal_grams)
            baseline, reference, scenario = legs
            secondary = compare_forecasts(scenario, baseline, "no_meal")
            primary = compare_forecasts(scenario, reference, "zero_carb_meal_now")
            small = float(meal_grams) < COUNTERFACTUAL_RELIABLE_MIN_GRAMS
            notes = counterfactual_notes(primary, secondary, small)
            joint = self._joint_support(eng, meal_grams) if primary is not None else None
            if joint is not None and joint.status == "no_training_analogue" and joint.message:
                notes.append(joint.message + " This concerns training support, not a known error in the forecast.")
            return CounterfactualResult(
                patient_id=pid, as_of=eng.as_of.to_pydatetime(), meal_grams=float(meal_grams),
                baseline=baseline, reference=reference, scenario=scenario,
                # legacy fields keep their original (no-meal) meaning
                delta_glucose_60mg_dl=secondary.delta_glucose_mg_dl.get("60") if secondary else None,
                delta_probability=secondary.delta_probability if secondary else None,
                primary=primary, secondary=secondary, small_meal_unreliable=small, notes=notes,
                joint_support=joint,
                twin_curve=self._twin_curve(eng, meal_grams),
            )

    @staticmethod
    def _twin_curve(eng: TwinEngine, meal_grams: float) -> TwinCurveEstimate | None:
        """Research estimate from the twin's own state (learned sensitivity, latest CGM); never alters it."""
        st = eng.state
        if st is None:
            return None
        return twin_curve_estimate(meal_grams, st.personal.carb_sensitivity_mg_dl_per_g, st.personal.meals_used,
                                   st.last_glucose_mg_dl)

    def _joint_support(self, eng: TwinEngine, meal_grams: float) -> JointSupportCheck:
        """Assess the scenario leg's meal inputs exactly as the models see them (never the reference leg:
        a zero-carb meal is outside meal-now support by construction)."""
        if self.joint_support is None:
            return JointSupportCheck(status="unavailable", reason=self.joint_support_reason, caveat=CAVEAT)
        t0, rows, reason = eng._counterfactual_features(meal_grams)
        feats = rows.get("scenario")
        if reason is not None or feats is None or t0 not in feats.index:
            return JointSupportCheck(status="unavailable", reason=reason or "scenario features unavailable",
                                     caveat=CAVEAT)
        return JointSupportCheck(**self.joint_support.assess(feats.loc[t0, list(JOINT_FEATURES)].to_dict()))

    def _status(self, sess: ReplaySession) -> ReplayStatus:
        eng = self.engines[sess.patient_id]
        return ReplayStatus(
            session_id=sess.session_id, patient_id=sess.patient_id, clock=sess.clock.to_pydatetime(),
            start=sess.start.to_pydatetime(), end=sess.end.to_pydatetime(), finished=sess.clock >= sess.end,
            observations_replayed=sess.replayed, state=eng.state, forecast=eng.latest_forecast,
        )
