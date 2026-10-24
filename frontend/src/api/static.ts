/**
 * Static demo client: same interface as the live client, answering from a snapshot that
 * scripts/export_static_demo.py recorded from the real API. Nothing is computed in the browser; requests that were
 * not recorded fail with a clear message instead of an invented answer. Used only in `npm run build:static`.
 */
import { fmtDateTime } from "../format";
import { ApiError } from "./errors";
import {
  filterForecasts, filterObservations, findWhatIf, missingWhatIfMessage, stepFrame,
  type SnapshotManifest, type SnapshotScenario,
} from "./staticReplay";
import type {
  CounterfactualResult, EvaluationReport, Forecast, ForecastSummary, HealthStatus, ModelCard, Observation, ObservationKind,
  PatientRecord, PatientSummary, ReplayStatus, TwinState,
} from "./types";

const BASE = `${import.meta.env.BASE_URL}demo/`;
let manifestP: Promise<SnapshotManifest> | null = null;
const scenarios = new Map<string, Promise<SnapshotScenario>>();
const cursor = new Map<string, number>(); // patient id -> current frame index

async function getJson<T>(file: string): Promise<T> {
  const res = await fetch(BASE + file);
  if (!res.ok) throw new ApiError(res.status, `Static snapshot file ${file} could not be loaded (${res.status}).`);
  return (await res.json()) as T;
}

export const loadManifest = () => (manifestP ??= getJson<SnapshotManifest>("manifest.json"));

async function scenarioFor(pid: string): Promise<SnapshotScenario> {
  const meta = (await loadManifest()).scenarios.find((s) => s.patient_id === pid);
  if (!meta) throw new ApiError(404, `${pid} is not part of the static demo snapshot.`);
  if (!scenarios.has(pid)) scenarios.set(pid, getJson<SnapshotScenario>(meta.file));
  return scenarios.get(pid)!;
}

async function current(pid: string): Promise<{ sc: SnapshotScenario; i: number; frame: ReplayStatus }> {
  const sc = await scenarioFor(pid);
  const i = cursor.get(pid) ?? 0;
  return { sc, i, frame: sc.frames[i] };
}

export const staticApi = {
  health: async () => (await loadManifest()).health as HealthStatus,
  patients: async (): Promise<PatientSummary[]> => {
    const m = await loadManifest();
    return Promise.all(m.scenarios.map(async (s) => {
      const sc = await scenarioFor(s.patient_id);
      return sc.summaries[cursor.get(s.patient_id) ?? 0];
    }));
  },
  patient: async (id: string) => (await scenarioFor(id)).record as PatientRecord,
  observations: async (id: string, kind?: ObservationKind, since?: string): Promise<Observation[]> => {
    const { sc, frame } = await current(id);
    return filterObservations(sc.observations, kind, since, frame.clock, 5000);
  },
  state: async (id: string) => (await current(id)).frame.state as TwinState,
  forecast: async (id: string) => (await current(id)).frame.forecast as Forecast,
  forecasts: async (id: string, since?: string): Promise<ForecastSummary[]> => {
    const { sc, frame } = await current(id);
    return filterForecasts(sc.forecasts, since, frame.clock, 5000);
  },
  // The snapshot always starts at its recorded start time, whatever offset is requested.
  createReplay: async (patient_id: string, _start_offset_hours = 24): Promise<ReplayStatus> => {
    const sc = await scenarioFor(patient_id);
    cursor.set(patient_id, 0);
    return sc.frames[0];
  },
  stepReplay: async (sid: string, minutes: number): Promise<ReplayStatus> => {
    const m = await loadManifest();
    for (const s of m.scenarios) {
      const sc = await scenarioFor(s.patient_id);
      if (sc.frames[0].session_id !== sid) continue;
      const i = stepFrame(cursor.get(s.patient_id) ?? 0, minutes, sc.step_minutes, sc.frames.length);
      cursor.set(s.patient_id, i);
      return sc.frames[i];
    }
    throw new ApiError(404, "not found: replay session (static snapshot)");
  },
  counterfactual: async (id: string, meal_grams: number): Promise<CounterfactualResult> => {
    const { sc, i } = await current(id);
    const r = findWhatIf(sc, i, meal_grams);
    if (r) return r;
    const offset = sc.record.utc_offset_minutes;
    throw new ApiError(409, missingWhatIfMessage(sc, meal_grams, (iso) => fmtDateTime(new Date(iso).getTime(), offset)));
  },
  evaluation: async () => (await loadManifest()).evaluation as EvaluationReport,
  model: async () => (await loadManifest()).model as ModelCard,
};
