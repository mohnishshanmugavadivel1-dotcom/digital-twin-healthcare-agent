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

SCHEMA_VERSION = "0.2.0"  # 0.2.0: genetic_markers/family history on PatientRecord; replay bounds

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


class GeneticMarker(_Model):
    """Synthetic genotype entry. In v0.2 it is display-only: no physiological effect, not a model input."""

    gene: str
    variant: str
    genotype: str
    risk_alleles: int = Field(ge=0, le=2)
    note: str = "synthetic; display-only (no simulated effect, not used by the model)"


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
    family_history_t2d: bool | None = None
    genetic_markers: list[GeneticMarker] = Field(default_factory=list)
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


class AgpHour(_Model):
    hour: int = Field(ge=0, le=23, description="Hour of the patient's local day")
    n: int
    p5: float
    p25: float
    p50: float
    p75: float
    p95: float


class AgpSummary(_Model):
    """Ambulatory glucose profile of the CGM a twin has received (glucotwin.agp). Descriptive only."""

    patient_id: PatientId
    as_of: datetime
    window_days: int
    days_with_data: float
    n_readings: int
    coverage_pct: float
    sufficient: bool = Field(description=">= 14 days and >= 70% of possible readings (international consensus)")
    mean_mg_dl: float | None
    gmi_pct: float | None = Field(description="Glucose management indicator: 3.31 + 0.02392 x mean mg/dL")
    cv_pct: float | None
    tir_70_180_pct: float | None
    tar_181_250_pct: float | None
    tar_over_250_pct: float | None
    tbr_54_69_pct: float | None
    tbr_under_54_pct: float | None
    hourly: list[AgpHour] = Field(default_factory=list)
    utc_offset_minutes: int
    note: str = ("Synthetic CGM. Descriptive summary following the 2019 international consensus metrics; "
                 "GMI is an estimate from mean glucose, not a laboratory HbA1c. Not a diagnosis.")


class FhirIngestSkip(_Model):
    index: int
    resource_type: str | None = None
    reason: str


class FhirIngestLab(_Model):
    loinc: str
    name: str
    value: float
    unit: str
    effective: datetime


class FhirIngestResult(_Model):
    """POST /api/fhir/Bundle: what GlucoTwin would ingest from a FHIR R4 Bundle (validation only).

    Nothing is written to any twin; send ``observations`` to POST /api/patients/{id}/observations to ingest.
    A structural parse of the fields GlucoTwin uses; not a full FHIR validation or a compliance claim.
    """

    patient_id: PatientId
    entries: int
    observations: list[Observation] = Field(default_factory=list)
    labs: list[FhirIngestLab] = Field(default_factory=list)
    skipped: list[FhirIngestSkip] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
    ingested: Literal[False] = False
    note: str = ("Validation only: nothing was added to a twin. Structural parse of the fields GlucoTwin uses; "
                 "not a full FHIR validation, not certified, not a compliance claim.")


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
    # Additive, descriptive only (glucotwin.twin.personal_uncertainty); never used by a forecast.
    observed_weight: float | None = None  # n / (3 + n): share of the estimate from observed meals
    response_sd_mg_dl_per_g: float | None = None  # SD of observed meal-response ratios (n >= 2)
    sampling_se_mg_dl_per_g: float | None = None  # sampling standard error, not a posterior SD (n >= 2)


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
    start_offset_hours: float = Field(default=24.0, ge=0, le=24 * 366, description="Warm-up history pre-loaded before replay")
    duration_hours: float | None = Field(default=None, gt=0, le=24 * 366)


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


class CounterfactualRequest(_Model):
    """A hypothetical meal eaten *now*. It is never ingested into the patient record."""

    meal_grams: float = Field(ge=1, le=300, description="Carbohydrates of the hypothetical meal in grams (1-300)")


class CounterfactualComparison(_Model):
    """Scenario minus one reference leg, per forecast horizon (backlog B-22).

    ``reference="zero_carb_meal_now"`` (primary) isolates the carb content: both legs log a
    meal at the same time. ``reference="no_meal"`` (secondary) also contains the models'
    learned meal-timing expectation. Both are learned model associations, not causal effects.
    """

    reference: Literal["zero_carb_meal_now", "no_meal"]
    label: str
    delta_glucose_mg_dl: dict[str, float] = Field(
        default_factory=dict, description="Horizon in minutes -> scenario minus reference glucose (mg/dL)")
    delta_probability: float | None = None
    reference_probability: float | None = None
    risk_saturated: bool = Field(
        default=False, description="Reference-leg risk > 0.95: a risk change cannot be meaningfully positive")


class JointSupportCheck(_Model):
    """B-23: whether the what-if scenario's meal inputs have a comparable example in the training data.

    A training-support diagnostic only: ``no_training_analogue`` is not evidence that the forecast is
    wrong, and ``within_training_support`` does not make it accurate. Never alters the forecast.
    """

    status: Literal["within_training_support", "no_training_analogue", "unavailable"]
    reasons: list[str] = Field(default_factory=list, description="Coordinates outside the training range")
    sparse: list[str] = Field(default_factory=list,
                              description="Coordinates inside the range but above the 99th training percentile")
    message: str | None = None
    reason: str | None = Field(default=None, description="Why the check is unavailable, if it is")
    coordinates: dict[str, float] = Field(default_factory=dict)
    training_range: dict[str, list[float]] = Field(default_factory=dict)
    caveat: str = ""


class TwinCurveEstimate(_Model):
    """Research estimate shown next to the tree-model What-If (glucotwin.twin.response_curve).

    Personalised meal curve (protocol addendum v3) and a cohort-level 20-min post-meal walk effect
    (addendum v4), both scored on held-out synthetic patients against simulator ground truth.
    Never changes the served forecast or the tree-model deltas.
    """

    kind: Literal["personalised_curve_research"] = "personalised_curve_research"
    delta_glucose_mg_dl: dict[str, float] = Field(
        default_factory=dict, description="Horizon in minutes -> meal-alone glucose change (mg/dL)")
    walk_delta_glucose_mg_dl: dict[str, float] | None = Field(
        default=None, description="Horizon -> change added by a 20-min post-meal walk (cohort level)")
    with_walk_delta_glucose_mg_dl: dict[str, float] | None = Field(
        default=None, description="Horizon -> meal + walk glucose change (mg/dL)")
    carb_sensitivity_mg_dl_per_g: float
    meals_used: int
    latest_cgm_mg_dl: float | None = None
    walk: dict[str, float] = Field(default_factory=dict)
    within_tested_range: bool
    outside_tested_reasons: list[str] = Field(default_factory=list)
    test_mae_mg_dl: dict[str, float] = Field(default_factory=dict)
    walk_test_mae_mg_dl: dict[str, float] = Field(default_factory=dict)
    caveat: str = ""


class CounterfactualResult(_Model):
    """Baseline versus simulated what-if forecast. Strictly a simulated scenario, never advice.

    ``primary`` compares against a zero-carb meal logged at the same time (``reference``);
    ``secondary`` against the no-meal ``baseline``. ``delta_glucose_60mg_dl`` and
    ``delta_probability`` keep their original no-meal meaning for backward compatibility.
    """

    patient_id: PatientId
    as_of: datetime
    meal_grams: float | None = None
    baseline: Forecast
    reference: Forecast | None = None
    scenario: Forecast
    delta_glucose_60mg_dl: float | None = None
    delta_probability: float | None = None
    primary: CounterfactualComparison | None = None
    secondary: CounterfactualComparison | None = None
    small_meal_unreliable: bool = False
    notes: list[str] = Field(default_factory=list)
    joint_support: JointSupportCheck | None = Field(
        default=None, description="B-23 training-support check of the scenario leg (additive; optional)")
    twin_curve: TwinCurveEstimate | None = Field(
        default=None, description="Research estimate: personalised meal curve and post-meal walk effect (additive)")
    is_simulated: Literal[True] = True
    disclaimer: str = (
        "Simulated what-if scenario. The hypothetical meal was never added to the patient record. "
        "Differences are learned associations of the forecasting models, not causal physiological effects. "
        "Not medical advice and not a treatment recommendation."
    )


IngestResult.model_rebuild()
