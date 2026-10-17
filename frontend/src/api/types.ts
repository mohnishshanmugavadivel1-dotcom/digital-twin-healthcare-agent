// Mirrors src/glucotwin/contracts.py (schema v0.1.0). Keep in sync; the backend is the source of truth.

export type ISODate = string;
export type Split = "train" | "validation" | "test";

export interface Medication { name: string; drug_class: string; dose: string | null }
export interface LabResult { name: string; value: number; unit: string; measured_at: ISODate }

export interface PatientRecord {
  patient_id: string;
  is_synthetic: true;
  display_name: string;
  age_years: number;
  sex: "female" | "male";
  height_cm: number;
  weight_kg: number;
  bmi: number;
  diabetes_type: "T2D";
  diabetes_duration_years: number;
  hba1c_percent: number;
  fasting_glucose_mg_dl: number;
  egfr_ml_min_1_73m2: number;
  conditions: string[];
  medications: Medication[];
  labs: LabResult[];
  utc_offset_minutes: number;
  split: Split | null;
}

export interface PatientSummary {
  patient_id: string;
  display_name: string;
  age_years: number;
  sex: "female" | "male";
  hba1c_percent: number;
  split: Split | null;
  data_start: ISODate | null;
  data_end: ISODate | null;
  latest_risk_probability: number | null;
  latest_glucose_mg_dl: number | null;
}

export type ObservationKind = "cgm" | "meal" | "steps" | "heart_rate";
export interface Observation { patient_id: string; timestamp: ISODate; kind: ObservationKind; value: number; unit: string | null; source: string }

export type TrendArrow = "rising_fast" | "rising" | "stable" | "falling" | "falling_fast" | "unknown";

export interface TwinState {
  patient_id: string;
  as_of: ISODate;
  version: number;
  observations_ingested: number;
  last_glucose_mg_dl: number | null;
  glucose_trend_mg_dl_per_min: number | null;
  trend_arrow: TrendArrow;
  carbs_on_board_g: number;
  minutes_since_last_meal: number | null;
  steps_last_60min: number;
  mean_heart_rate_30min: number | null;
  summary_24h: {
    window_hours: number; n_readings: number; mean_mg_dl: number | null; cv_percent: number | null;
    time_in_range_pct: number | null; time_above_range_pct: number | null; time_below_range_pct: number | null;
  };
  personal: { carb_sensitivity_mg_dl_per_g: number; carb_sensitivity_prior: number; meals_used: number };
  data_quality: { cgm_completeness_3h: number; minutes_since_last_cgm: number | null; stale: boolean; gaps_over_30min_24h: number };
}

export interface ForecastPoint { horizon_min: number; timestamp: ISODate; glucose_mg_dl: number; lower_mg_dl: number; upper_mg_dl: number }
export interface RiskFactor { feature: string; label: string; value: number | null; contribution: number }
export interface ExcursionRisk {
  event_definition: string; horizon_min: number; probability: number; alert_threshold: number; alert: boolean;
  risk_band: "low" | "moderate" | "high"; top_factors: RiskFactor[];
}
export interface Forecast {
  forecast_id: string; patient_id: string; issued_at: ISODate; model_version: string;
  status: "ok" | "insufficient_data"; reason: string | null; current_glucose_mg_dl: number | null;
  trajectory: ForecastPoint[]; excursion: ExcursionRisk | null; interval_level: number; disclaimer: string;
}
export interface ForecastSummary {
  issued_at: ISODate; status: "ok" | "insufficient_data"; current_glucose_mg_dl: number | null;
  probability: number | null; alert: boolean; predicted: Record<string, number>;
}

export interface ReplayStatus {
  session_id: string; patient_id: string; clock: ISODate; start: ISODate; end: ISODate; finished: boolean;
  observations_replayed: number; state: TwinState | null; forecast: Forecast | null;
}

export interface TrajectoryMetrics {
  model: string; horizon_min: number; n: number; mae_mg_dl: number; rmse_mg_dl: number; mard_percent: number;
  clarke_a_pct: number; clarke_ab_pct: number; interval_coverage: number | null;
}
export interface EventMetrics {
  model: string; n: number; prevalence: number; auroc: number | null; auprc: number | null; brier: number | null;
  threshold: number | null; sensitivity: number | null; specificity: number | null; ppv: number | null;
  event_sensitivity: number | null; median_lead_time_min: number | null; false_alert_episodes_per_patient_day: number | null;
}
export interface EvaluationReport {
  schema_version: string; generated_at: ISODate; model_version: string;
  dataset: { name: string; version: string; seed: number; is_synthetic: boolean; n_patients: number; days_per_patient: number;
    split_patients: Record<string, number>; split_samples: Record<string, number> };
  target_definition: string; split_protocol: string; trajectory: TrajectoryMetrics[]; event: EventMetrics[];
  served_models: Record<string, string>; notes: string[];
}
export interface HealthStatus { status: "ok"; schema_version: string; model_version: string; patients_available: number; data_is_synthetic: boolean }
export interface ModelCard {
  model_version: string; trained_at: ISODate; feature_names: string[]; event_model: string; trajectory_model: string;
  alert_threshold: number; interval_level: number; target_definition: string; training_data: string;
  intended_use: string; limitations: string[];
}
