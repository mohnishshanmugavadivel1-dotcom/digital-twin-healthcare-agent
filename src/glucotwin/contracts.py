"""Shared data contracts for GlucoTwin (schema v0.1.0).

This module is the single source of truth for every structure that crosses a
module boundary (generator -> engine -> model -> API -> dashboard). The
frontend mirrors these in ``frontend/src/api/types.ts``; keep them in sync.

Conventions
-----------
* All timestamps are timezone-aware and serialised as ISO-8601 in UTC.
  Local clock time (used for meal routines and hour-of-day features) is derived
  with ``PatientRecord.utc_offset_minutes``.
* Glucose is always mg/dL. Carbohydrates are grams. Steps are counts per
  5-minute bin. Heart rate is beats per minute.
* Every synthetic identifier starts with ``SYN-`` so it can never be confused
  with a real patient identifier.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from glucotwin.config import DISCLAIMER

SCHEMA_VERSION = "0.1.0"

PatientId = str  # pattern: ^SYN-\d{4}$


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=False)


def _require_tz(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware (ISO-8601 with offset)")
    return value


# ---------------------------------------------------------------------------
# Static / historical record (synthetic EHR)
# ---------------------------------------------------------------------------
class Sex(StrEnum):
    female = "female"
    male = "male"


DrugClass = Literal["biguanide", "sulfonylurea", "dpp4_inhibitor", "basal_insulin", "statin", "ace_inhibitor"]


class Medication(_Model):
    name: str
    drug_class: DrugClass
    dose: str | None = None


class LabResult(_Model):
    name: str
    value: float
    unit: str
    measured_at: datetime

    _tz = field_validator("measured_at")(_require_tz)


class PatientRecord(_Model):
    """Historical, slowly-changing record. Observable by a clinician."""

    patient_id: PatientId = Field(pattern=r"^SYN-\d{4}$")
    is_synthetic: Literal[True] = True
    display_name: str
    age_years: int = Field(ge=18, le=100)
    sex: Sex
    height_cm: float = Field(gt=100, lt=230)
    weight_kg: float = Field(gt=30, lt=250)
    bmi: float = Field(gt=10, lt=70)
    diabetes_type: Literal["T2D"] = "T2D"
    diabetes_duration_years: float = Field(ge=0, le=60)
    hba1c_percent: float = Field(ge=4, le=16)
    fasting_glucose_mg_dl: float = Field(ge=50, le=400)
    egfr_ml_min_1_73m2: float = Field(ge=5, le=150)
    conditions: list[str] = Field(default_factory=list)
    medications: list[Medication] = Field(default_factory=list)
    labs: list[LabResult] = Field(default_factory=list)
    utc_offset_minutes: int = 330  # Asia/Kolkata
    split: Literal["train", "validation", "test"] | None = None


class PatientSummary(_Model):
    patient_id: PatientId
    display_name: str
    age_years: int
    sex: Sex
    hba1c_percent: float
    split: Literal["train", "validation", "test"] | None
    data_start: datetime | None
    data_end: datetime | None
    latest_risk_probability: float | None = None
    latest_glucose_mg_dl: float | None = None


# ---------------------------------------------------------------------------
# Dynamic observations (CGM + wearable + logs)
# ---------------------------------------------------------------------------
class ObservationKind(StrEnum):
    cgm = "cgm"
    meal = "meal"  # value = logged carbohydrate grams
    steps = "steps"  # value = steps in the 5-minute bin ending at timestamp
    heart_rate = "heart_rate"  # value = mean bpm in the 5-minute bin


OBSERVATION_UNITS: dict[ObservationKind, str] = {
    ObservationKind.cgm: "mg/dL",
    ObservationKind.meal: "g",
    ObservationKind.steps: "count/5min",
    ObservationKind.heart_rate: "bpm",
}


class Observation(_Model):
    patient_id: PatientId = Field(pattern=r"^SYN-\d{4}$")
    timestamp: datetime
    kind: ObservationKind
    value: float
    unit: str | None = None
    source: str = "synthetic"

    _tz = field_validator("timestamp")(_require_tz)


class ObservationBatch(_Model):
    observations: list[Observation] = Field(min_length=1, max_length=5000)


class IngestResult(_Model):
    accepted: int
    duplicates: int
    rejected: int
    errors: list[str] = Field(default_factory=list)
    state: TwinState | None = None
    forecast: Forecast | None = None


# ---------------------------------------------------------------------------
# Digital twin state
# ---------------------------------------------------------------------------
TrendArrow = Literal["rising_fast", "rising", "stable", "falling", "falling_fast", "unknown"]


class GlycaemicSummary(_Model):
    window_hours: int
    n_readings: int
    mean_mg_dl: float | None
    cv_percent: float | None
    time_in_range_pct: float | None  # 70-180
    time_above_range_pct: float | None  # >180
    time_below_range_pct: float | None  # <70


class PersonalParameters(_Model):
    """Parameters the twin learns about this specific patient as data arrive."""

    carb_sensitivity_mg_dl_per_g: float  # shrunk towards the EHR-derived prior
    carb_sensitivity_prior: float
    meals_used: int


class DataQuality(_Model):
    cgm_completeness_3h: float  # fraction of expected readings present
    minutes_since_last_cgm: float | None
    stale: bool
    gaps_over_30min_24h: int


class TwinState(_Model):
    patient_id: PatientId
    as_of: datetime
    version: int  # increments on every state update
    observations_ingested: int
    last_glucose_mg_dl: float | None
    glucose_trend_mg_dl_per_min: float | None
    trend_arrow: TrendArrow
    carbs_on_board_g: float
    minutes_since_last_meal: float | None
    steps_last_60min: float
    mean_heart_rate_30min: float | None
    summary_24h: GlycaemicSummary
    personal: PersonalParameters
    data_quality: DataQuality


# ---------------------------------------------------------------------------
# Forecasts
# ---------------------------------------------------------------------------
class ForecastPoint(_Model):
    horizon_min: int
    timestamp: datetime
    glucose_mg_dl: float
    lower_mg_dl: float
    upper_mg_dl: float


class RiskFactor(_Model):
    """A group of related features (see features.FEATURE_GROUPS) and its summed contribution."""

    feature: str
    label: str
    value: float | None
    contribution: float  # additive contribution to log-odds (positive = raises risk)


class ExcursionRisk(_Model):
    event_definition: str
    horizon_min: int
    probability: float = Field(ge=0, le=1)
    alert_threshold: float = Field(ge=0, le=1)
    alert: bool
    risk_band: Literal["low", "moderate", "high"]
    top_factors: list[RiskFactor]


class Forecast(_Model):
    forecast_id: str
    patient_id: PatientId
    issued_at: datetime
    model_version: str
    status: Literal["ok", "insufficient_data"]
    reason: str | None = None
    current_glucose_mg_dl: float | None = None
    trajectory: list[ForecastPoint] = Field(default_factory=list)
    excursion: ExcursionRisk | None = None
    interval_level: float = 0.8
    disclaimer: str = DISCLAIMER


class ForecastSummary(_Model):
    """Compact forecast record for timelines (risk history, forecast-vs-actual overlays)."""

    issued_at: datetime
    status: Literal["ok", "insufficient_data"]
    current_glucose_mg_dl: float | None
    probability: float | None
    alert: bool
    predicted: dict[str, float]  # horizon minutes (as string) -> predicted glucose


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------
class ReplayCreate(_Model):
    patient_id: PatientId
    start_offset_hours: float = Field(default=24.0, ge=0, description="Warm-up history pre-loaded before replay")
    duration_hours: float | None = Field(default=None, gt=0)


class ReplayStep(_Model):
    minutes: int = Field(default=5, ge=5, le=24 * 60)


class ReplayStatus(_Model):
    session_id: str
    patient_id: PatientId
    clock: datetime  # replay "now"; nothing after this has been revealed to the twin
    start: datetime
    end: datetime
    finished: bool
    observations_replayed: int
    state: TwinState | None
    forecast: Forecast | None


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------
class TrajectoryMetrics(_Model):
    model: str
    horizon_min: int
    n: int
    mae_mg_dl: float
    rmse_mg_dl: float
    mard_percent: float
    clarke_a_pct: float
    clarke_ab_pct: float
    interval_coverage: float | None = None


class EventMetrics(_Model):
    model: str
    n: int
    prevalence: float
    auroc: float | None
    auprc: float | None
    brier: float | None
    threshold: float | None
    sensitivity: float | None
    specificity: float | None
    ppv: float | None
    event_sensitivity: float | None  # fraction of excursion onsets preceded by >=1 alert
    median_lead_time_min: float | None
    false_alert_episodes_per_patient_day: float | None


class DatasetCard(_Model):
    name: str
    version: str
    seed: int
    is_synthetic: bool
    n_patients: int
    days_per_patient: int
    split_patients: dict[str, int]
    split_samples: dict[str, int]


class EvaluationReport(_Model):
    schema_version: str = SCHEMA_VERSION
    generated_at: datetime
    model_version: str
    dataset: DatasetCard
    target_definition: str
    split_protocol: str
    trajectory: list[TrajectoryMetrics]
    event: list[EventMetrics]
    served_models: dict[str, str]
    notes: list[str]


class HealthStatus(_Model):
    status: Literal["ok"]
    schema_version: str
    model_version: str
    patients_available: int
    data_is_synthetic: bool


class ModelCard(_Model):
    model_version: str
    trained_at: datetime
    feature_names: list[str]
    event_model: str
    trajectory_model: str
    alert_threshold: float
    interval_level: float
    target_definition: str
    training_data: str
    intended_use: str
    limitations: list[str]


IngestResult.model_rebuild()
