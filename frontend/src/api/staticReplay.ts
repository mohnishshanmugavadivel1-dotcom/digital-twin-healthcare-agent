/**
 * Pure replay rules for the static demo snapshot (no I/O; unit-tested in tests/staticReplay.test.ts).
 *
 * They mirror the real API exactly, and scripts/export_static_demo.py checks this against live API answers before it
 * writes a snapshot: observations and forecast summaries are those with a timestamp > `since` and at or before
 * the replay clock, keeping the last `limit` items; replay steps advance whole 5-min frames.
 */
import type { CounterfactualResult, FhirBundle, ForecastSummary, Observation, PatientRecord, PatientSummary, ReplayStatus } from "./types";

export interface SnapshotScenarioMeta {
  id: string; patient_id: string; start_offset_hours: number; title: string; description: string; file: string;
  start_clock: string; end_clock: string; whatif_clocks: string[]; n_frames: number;
  preset_clocks?: string[]; fhir_clock?: string; // optional: older snapshots lack them
}

export interface SnapshotManifest {
  kind: string; notice: string; recorded_at: string; generator: string; git_head: string;
  working_tree_dirty_at_recording: boolean; model_version: string; whatif_grams: number[];
  preset_grams?: number[]; preset_grid_minutes?: number;
  scenarios: SnapshotScenarioMeta[];
  health: unknown; model: unknown; evaluation: unknown;
}

export interface SnapshotScenario {
  id: string; patient_id: string; step_minutes: number; record: PatientRecord;
  frames: ReplayStatus[]; summaries: PatientSummary[]; observations: Observation[]; forecasts: ForecastSummary[];
  whatifs: { frame_index: number; grams: number; result: CounterfactualResult }[];
  fhir?: { frame_index: number; hours: number; bundle: FhirBundle };
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
export function missingWhatIfMessage(sc: SnapshotScenario, grams: number, fmtClock: (iso: string) => string,
                                     frameIndex?: number): string {
  const byFrame = new Map<number, Set<number>>();
  for (const w of sc.whatifs) byFrame.set(w.frame_index, (byFrame.get(w.frame_index) ?? new Set()).add(w.grams));
  const allAmounts = [...new Set(sc.whatifs.map((w) => w.grams))].sort((a, b) => a - b);
  const full = [...byFrame].filter(([, g]) => g.size === allAmounts.length).map(([i]) => i).sort((a, b) => a - b);
  const when = full.map((i) => fmtClock(sc.frames[i].clock)).join(" and ");
  const here = frameIndex === undefined ? null : [...(byFrame.get(frameIndex) ?? [])].sort((a, b) => a - b);
  const herePart = here === null ? "" : here.length
    ? ` At this moment the snapshot has ${here.join(", ")} g.`
    : " This moment has none: the meal presets are recorded every 15 min of the replay.";
  return `Static snapshot: no recorded what-if for ${grams} g at this moment.${herePart} Every amount ` +
    `(${allAmounts.join(", ")} g) is recorded at ${when}. Run the app locally (make serve) to simulate any amount at any time.`;
}
