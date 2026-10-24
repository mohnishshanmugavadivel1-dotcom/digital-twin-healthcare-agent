/**
 * Static demo snapshot: pure replay rules plus checks on the REAL recorded snapshot (frontend/static-demo/demo/),
 * which scripts/export_static_demo.py recorded from the live API.
 *   node --experimental-strip-types --test tests/*.test.ts
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { jointSupportChip } from "../src/format.ts";
import { MEAL_PRESETS, presetGrams } from "../src/mealPresets.ts";
import { filterForecasts, filterObservations, findWhatIf, missingWhatIfMessage, stepFrame } from "../src/api/staticReplay.ts";

const dir = new URL("../static-demo/demo/", import.meta.url);
const manifest = JSON.parse(readFileSync(new URL("manifest.json", dir), "utf8"));
const load = (id: string) => JSON.parse(readFileSync(new URL(`${id}.json`, dir), "utf8"));
const obs = (t: string, kind = "cgm") => ({ patient_id: "SYN-0001", timestamp: t, kind, value: 100, unit: null, source: "x" }) as never;

test("observation filter: since is exclusive, clock inclusive, kind filter, keeps the LAST limit items", () => {
  const o = [obs("2026-03-01T00:00:00Z"), obs("2026-03-01T00:05:00Z"), obs("2026-03-01T00:05:00Z", "meal"),
             obs("2026-03-01T00:10:00Z"), obs("2026-03-01T00:15:00Z")];
  const got = filterObservations(o, "cgm", "2026-03-01T00:00:00.000Z", "2026-03-01T00:10:00Z", 5000);
  assert.deepEqual(got.map((x: { timestamp: string }) => x.timestamp), ["2026-03-01T00:05:00Z", "2026-03-01T00:10:00Z"]);
  assert.equal(filterObservations(o, "cgm", undefined, "2026-03-01T00:15:00Z", 2).length, 2);
  assert.equal((filterObservations(o, "cgm", undefined, "2026-03-01T00:15:00Z", 2)[0] as { timestamp: string }).timestamp,
               "2026-03-01T00:10:00Z");
  assert.equal(filterObservations(o, undefined, undefined, "2026-03-01T00:05:00Z", 5000).length, 3);
});

test("forecast filter never reveals forecasts issued after the replay clock", () => {
  const f = ["00:00", "00:05", "00:10"].map((h) => ({ issued_at: `2026-03-01T${h}:00Z` })) as never[];
  assert.equal(filterForecasts(f, undefined, "2026-03-01T00:05:00Z", 5000).length, 2);
  assert.equal(filterForecasts(f, "2026-03-01T00:05:00Z", "2026-03-01T00:10:00Z", 5000).length, 1);
});

test("stepping advances whole frames and clamps at the end; invalid steps do nothing", () => {
  assert.equal(stepFrame(0, 5, 5, 73), 1);
  assert.equal(stepFrame(0, 60, 5, 73), 12);
  assert.equal(stepFrame(70, 60, 5, 73), 72);
  assert.equal(stepFrame(3, 0, 5, 73), 3);
  assert.equal(stepFrame(3, Number.NaN, 5, 73), 3);
});

test("recorded snapshot: provenance, two scenarios, frames end the replay, faithfulness checks passed at export", () => {
  assert.equal(manifest.kind, "glucotwin-static-demo-snapshot/1");
  assert.match(manifest.notice, /recorded from the real API/);
  assert.ok(manifest.scenarios.length >= 2);
  for (const meta of manifest.scenarios) {
    const sc = load(meta.id);
    assert.equal(sc.frames.length, meta.n_frames);
    assert.equal(sc.frames.at(-1).finished, true);
    assert.equal(sc.checks.observation_and_forecast_replay_equals_api, true);
    assert.equal(sc.checks.step_60_equals_step_5_frames, true);
    for (const f of sc.frames) assert.equal(f.state.patient_id, meta.patient_id);
    // the snapshot never contains observations after its last frame
    const end = new Date(sc.frames.at(-1).clock).getTime();
    assert.ok(sc.observations.every((o: { timestamp: string }) => new Date(o.timestamp).getTime() <= end));
  }
});

test("every Indian meal preset has a recorded what-if (presets stay in sync with the export script)", () => {
  for (const p of MEAL_PRESETS) assert.ok(manifest.whatif_grams.includes(p.carbs), `${p.id}: ${p.carbs} g not recorded`);
  assert.deepEqual(manifest.preset_grams, presetGrams());
});

test("snapshot: every preset at every 15-min frame, the research twin curve beside the tree deltas, and the AGP", () => {
  for (const meta of manifest.scenarios) {
    const sc = load(meta.id);
    for (let i = 0; i < sc.frames.length; i += manifest.preset_grid_minutes / sc.step_minutes) {
      for (const g of presetGrams()) assert.ok(findWhatIf(sc, i, g), `${meta.id}: ${g} g missing at frame ${i}`);
    }
    for (const w of sc.whatifs) {
      const tc = w.result.twin_curve;
      assert.ok(tc && tc.kind === "personalised_curve_research", `${meta.id}: no twin curve at frame ${w.frame_index}`);
      assert.match(tc.caveat, /not the served forecast/);
      assert.equal(tc.within_tested_range, w.grams >= 20 && w.grams <= 120 && tc.latest_cgm_mg_dl <= 180);
    }
    assert.equal(sc.agp.frame_index, 0);
    assert.equal(sc.agp.summary.as_of, sc.frames[0].state.as_of);
    const hours = sc.agp.summary.hourly.map((h) => h.hour);
    if (meta.kind === "moment") { // one day of data: hours with a CGM gap have no bin (e.g. SYN-0009 has none at 10-11 h)
      assert.ok(sc.agp.summary.n_readings > 0 && hours.length > 0 && new Set(hours).size === hours.length && hours.every((h) => h >= 0 && h <= 23));
      assert.equal(sc.frames.length, 2); // the moment plus one 5-min step to the end of the recording
      assert.ok(!sc.frames[0].finished && sc.frames[1].finished);
    } else assert.ok(sc.agp.summary.n_readings > 0 && hours.length === 24);
  }
});

test("07:55 demo point in the snapshot: glucose 94, risk 0.2154; 120 g within support; 300 g flagged with the API text", () => {
  const sc = load("early-warning");
  assert.equal(sc.frames[0].state.last_glucose_mg_dl, 94);
  assert.equal(sc.frames[0].forecast.excursion.probability, 0.2154);
  const r120 = findWhatIf(sc, 0, 120)!;
  assert.equal(r120.scenario.excursion!.probability, 0.9986);
  assert.equal(r120.joint_support!.status, "within_training_support");
  assert.equal(jointSupportChip(r120.joint_support), null);
  const r300 = findWhatIf(sc, 0, 300)!;
  const chip = jointSupportChip(r300.joint_support)!;
  assert.equal(chip.title, `${r300.joint_support!.message} ${r300.joint_support!.caveat}`);
  assert.equal(findWhatIf(sc, 1, 120), null); // nothing recorded at 08:00
});

// Text in the export script, docs/STATIC_DEMO.md and docs/DEMO_SCRIPT.md describes these moments; keep them true.
const offsetIso = (iso: string, min: number) => new Date(new Date(iso).getTime() + min * 60_000).toISOString().slice(11, 16);
function firstAlertAndHigh(id: string) {
  const sc = load(id), off = sc.record.utc_offset_minutes, t0 = sc.frames[0].clock;
  const alert = sc.frames.find((f: { forecast: { excursion?: { alert: boolean } } | null }) => f.forecast?.excursion?.alert);
  const high = sc.observations.find((o: { kind: string; timestamp: string; value: number }) =>
    o.kind === "cgm" && o.timestamp >= t0 && o.value > 180);
  return { alert: offsetIso(alert.clock, off), alertGlucose: alert.state.last_glucose_mg_dl, high: offsetIso(high.timestamp, off) };
}

test("scenario descriptions match the recorded data (first alert, first CGM > 180, local time)", () => {
  assert.deepEqual(firstAlertAndHigh("early-warning"), { alert: "08:55", alertGlucose: 89, high: "10:20" });
  assert.deepEqual(firstAlertAndHigh("unlogged-meal"), { alert: "14:50", alertGlucose: 93, high: "15:35" });
  const sc = load("unlogged-meal");
  assert.equal(sc.frames[12].forecast.excursion.probability, 0.3123); // 14:45: below the 0.35 threshold, no alert
  assert.equal(sc.frames[12].forecast.excursion.alert, false);
});

test("an unrecorded what-if gets an explanatory message, not an invented result", () => {
  const sc = load("unlogged-meal");
  const msg = missingWhatIfMessage(sc, 77, (iso) => iso.slice(11, 16));
  assert.match(msg, /no recorded what-if for 77 g/);
  assert.match(msg, /make serve/);
  assert.equal(findWhatIf(sc, 0, 77), null);
});

test("snapshot: all 12 held-out test patients are recorded; the two full replays come first (SYN-0039 is the default view)", () => {
  const ids = manifest.scenarios.map((sc) => sc.patient_id);
  assert.equal(ids.length, 12);
  assert.equal(new Set(ids).size, 12);
  assert.deepEqual(manifest.scenarios.slice(0, 2).map((sc) => [sc.patient_id, sc.kind]), [["SYN-0039", "replay"], ["SYN-0019", "replay"]]);
  for (const sc of manifest.scenarios.slice(2)) {
    assert.equal(sc.kind, "moment");
    assert.equal(sc.start_offset_hours, 24); // the live app's default start, not a hand-picked moment
    assert.ok(sc.whatif_clocks?.length === 1 && sc.fhir_clock === sc.start_clock, sc.patient_id);
  }
});
