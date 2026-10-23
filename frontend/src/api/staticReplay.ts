/**
 * Pure replay rules for the static demo snapshot (no I/O; unit-tested in tests/staticReplay.test.ts).
 *
 * They mirror the real API exactly, and scripts/export_static_demo.py checks this against live API answers before it
 * writes a snapshot: observations and forecast summaries are those with a timestamp > `since` and at or before
 * the replay clock, keeping the last `limit` items; replay steps advance whole 5-min frames.
 */
import type { CounterfactualResult, ForecastSummary, Observation, PatientRecord, PatientSummary, ReplayStatus } from "./types";

export interface SnapshotScenarioMeta {
  id: string; patient_id: string; start_offset_hours: number; title: string; description: string; file: string;
  start_clock: string; end_clock: string; whatif_clocks: string[]; n_frames: number;
}

export interface SnapshotManifest {
  kind: string; notice: string; recorded_at: string; generator: string; git_head: string;
  working_tree_dirty_at_recording: boolean; model_version: string; whatif_grams: number[];
  scenarios: SnapshotScenarioMeta[];
  health: unknown; model: unknown; evaluation: unknown;
}

export interface SnapshotScenario {
  id: string; patient_id: string; step_minutes: number; record: PatientRecord;
  frames: ReplayStatus[]; summaries: PatientSummary[]; observations: Observation[]; forecasts: ForecastSummary[];
  whatifs: { frame_index: number; grams: number; result: CounterfactualResult }[];
}

const ms = (iso: string) => new Date(iso).getTime();

export function filterObservations(obs: Observation[], kind: string | undefined, since: string | undefined,
                                   clock: string, limit: number): Observation[] {
  const s = since ? ms(since) : -Infinity, c = ms(clock);
  const out = obs.filter((o) => (kind === undefined || o.kind === kind) && ms(o.timestamp) > s && ms(o.timestamp) <= c);
  return out.slice(-limit);
}

export function filterForecasts(fcs: ForecastSummary[], since: string | undefined, clock: string, limit: number): ForecastSummary[] {
  const s = since ? ms(since) : -Infinity, c = ms(clock);
  return fcs.filter((f) => ms(f.issued_at) > s && ms(f.issued_at) <= c).slice(-limit);
}

/** Frame index after stepping `minutes` (a positive multiple of the frame step), clamped to the last frame. */
export function stepFrame(index: number, minutes: number, stepMinutes: number, nFrames: number): number {
  if (!Number.isFinite(minutes) || minutes <= 0) return index;
  return Math.min(index + Math.max(1, Math.round(minutes / stepMinutes)), nFrames - 1);
}

export function findWhatIf(sc: SnapshotScenario, frameIndex: number, grams: number): CounterfactualResult | null {
  return sc.whatifs.find((w) => w.frame_index === frameIndex && w.grams === grams)?.result ?? null;
}

/** Message shown when a what-if was not recorded: says what IS available instead of inventing a result. */
export function missingWhatIfMessage(sc: SnapshotScenario, grams: number, fmtClock: (iso: string) => string): string {
  const idx = [...new Set(sc.whatifs.map((w) => w.frame_index))];
  const when = idx.map((i) => fmtClock(sc.frames[i].clock)).join(" and ");
  const amounts = [...new Set(sc.whatifs.map((w) => w.grams))].sort((a, b) => a - b).join(", ");
  return `Static snapshot: no recorded what-if for ${grams} g at this moment. Recorded what-ifs exist at ${when} for ` +
    `${amounts} g. Run the app locally (make serve) to simulate any amount at any time.`;
}
