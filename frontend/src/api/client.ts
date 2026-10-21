import type {
  CounterfactualResult, EvaluationReport, Forecast, ModelCard, ForecastSummary, HealthStatus, Observation, ObservationKind,
  PatientRecord, PatientSummary, ReplayStatus, TwinState,
} from "./types";
import { formatApiError } from "../format";

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...init });
  if (!res.ok) {
    let body: unknown = undefined;
    try { body = await res.json(); } catch { /* not JSON */ }
    throw new ApiError(res.status, formatApiError(res.status, body, res.statusText));
  }
  return (res.status === 204 ? undefined : await res.json()) as T;
}

const qs = (params: Record<string, string | number | undefined>) => {
  const e = Object.entries(params).filter(([, v]) => v !== undefined) as [string, string | number][];
  return e.length ? "?" + new URLSearchParams(e.map(([k, v]) => [k, String(v)])).toString() : "";
};

export const api = {
  health: () => request<HealthStatus>("/api/health"),
  patients: () => request<PatientSummary[]>("/api/patients"),
  patient: (id: string) => request<PatientRecord>(`/api/patients/${id}`),
  observations: (id: string, kind?: ObservationKind, since?: string) =>
    request<Observation[]>(`/api/patients/${id}/observations${qs({ kind, since, limit: 5000 })}`),
  state: (id: string) => request<TwinState>(`/api/patients/${id}/state`),
  forecast: (id: string) => request<Forecast>(`/api/patients/${id}/forecast`),
  forecasts: (id: string, since?: string) => request<ForecastSummary[]>(`/api/patients/${id}/forecasts${qs({ since, limit: 5000 })}`),
  createReplay: (patient_id: string, start_offset_hours = 24) =>
    request<ReplayStatus>("/api/replay", { method: "POST", body: JSON.stringify({ patient_id, start_offset_hours }) }),
  stepReplay: (sid: string, minutes: number) =>
    request<ReplayStatus>(`/api/replay/${sid}/step`, { method: "POST", body: JSON.stringify({ minutes }) }),
  counterfactual: (id: string, meal_grams: number) =>
    request<CounterfactualResult>(`/api/patients/${id}/counterfactual`, { method: "POST", body: JSON.stringify({ meal_grams }) }),
  evaluation: () => request<EvaluationReport>("/api/evaluation"),
  model: () => request<ModelCard>("/api/model"),
};
