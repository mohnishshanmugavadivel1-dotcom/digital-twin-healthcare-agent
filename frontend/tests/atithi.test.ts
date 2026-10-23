/** Atithi (patient) companion: plain language, same grounding verifier, refuses to render on any untraced number. */
import assert from "node:assert/strict";
import { test } from "node:test";

import type { Forecast, TwinCurveEstimate, TwinState } from "../src/api/types.ts";
import { COMPANION_SCOPES, COMPANION_SECTIONS, buildCompanion, companionFacts, companionText, verifyGrounding, type CompanionInput } from "../src/handover.ts";

const state: TwinState = {
  patient_id: "SYN-0039", as_of: "2026-03-08T02:25:00Z", version: 1, observations_ingested: 100,
  last_glucose_mg_dl: 94, glucose_trend_mg_dl_per_min: -0.34, trend_arrow: "stable", carbs_on_board_g: 0.2,
  minutes_since_last_meal: 681, steps_last_60min: 655, mean_heart_rate_30min: 71,
  summary_24h: { window_hours: 24, n_readings: 285, mean_mg_dl: 116, cv_percent: 28, time_in_range_pct: 94, time_above_range_pct: 5, time_below_range_pct: 1 },
  personal: { carb_sensitivity_mg_dl_per_g: 1.698, carb_sensitivity_prior: 1.5, meals_used: 20 },
  data_quality: { cgm_completeness_3h: 0.97, minutes_since_last_cgm: 0, stale: false, gaps_over_30min_24h: 0 },
};
const t = (h: number, g: number, lo: number, hi: number) => ({ horizon_min: h, timestamp: "x", glucose_mg_dl: g, lower_mg_dl: lo, upper_mg_dl: hi });
const forecast: Forecast = {
  forecast_id: "f", patient_id: "SYN-0039", issued_at: state.as_of, model_version: "test", status: "ok", reason: null, current_glucose_mg_dl: 94,
  trajectory: [t(30, 103.4, 90, 117), t(60, 119.2, 98, 141), t(120, 171.3, 141.2, 201.4)],
  excursion: { event_definition: "", horizon_min: 120, probability: 0.22, alert_threshold: 0.35, alert: false, risk_band: "moderate", top_factors: [] },
  interval_level: 0.8, disclaimer: "",
};
const twin = { kind: "personalised_curve_research", delta_glucose_mg_dl: { "30": 10, "60": 42.5, "120": 60 },
  walk_delta_glucose_mg_dl: { "120": -11.2 }, with_walk_delta_glucose_mg_dl: { "120": 48.8 }, carb_sensitivity_mg_dl_per_g: 1.698,
  meals_used: 20, latest_cgm_mg_dl: 94, walk: { minutes: 20, steps: 2500, start_after_meal_min: 15 }, within_tested_range: true,
  outside_tested_reasons: [], test_mae_mg_dl: {}, walk_test_mae_mg_dl: {}, caveat: "" } as TwinCurveEstimate;
const base: CompanionInput = {
  record: { patient_id: "SYN-0039", display_name: "Farah N. (synthetic)", age_years: 32, diabetes_duration_years: 5.1, utc_offset_minutes: 330,
            medications: [{ name: "Metformin", drug_class: "biguanide", dose: "1000 mg BD" }, { name: "Glimepiride", drug_class: "sulfonylurea", dose: "2 mg OD" }] },
  state, forecast, agp: null,
  scenario: { grams: 35, dish: "Idli with sambar", twin },
  swap: { grams: 32, dish: "Dhokla", rise120: 54.9 },
};
const check = (inp: CompanionInput) => {
  const sections = buildCompanion(inp);
  return { sections, text: companionText(sections), report: verifyGrounding(companionText(sections), companionFacts(inp), COMPANION_SCOPES) };
};

test("three plain-language sections; every number traces; deterministic", () => {
  const { sections, text, report } = check(base);
  assert.deepEqual(sections.map((s) => s.section), [...COMPANION_SECTIONS]);
  assert.deepEqual(report.untraced, []);
  assert.ok(report.total >= 15, `numbers checked: ${report.total}`);
  assert.equal(text, check(structuredClone(base)).text);
  assert.match(text, /latest glucose reading is 94 mg\/dL and it is steady/);
  assert.match(text, /in about 2 hours the twin's best guess is around 171 mg\/dL; it could reasonably be anywhere from 141 to 201 mg\/dL \(its 80% range\)/);
  assert.match(text, /The upper end goes above 180 mg\/dL/);
  assert.match(text, /from 20 of your logged meals.*about 1\.7 mg\/dL/);
  assert.match(text, /last logged meal was about 11 hours ago/);
  assert.match(text, /Idli with sambar \(about 35 g of carbohydrate\) is followed by a rise of about 60 mg\/dL after 2 hours; with an easy 20-minute walk after it \(about 2500 steps\) the simulated rise is about 49 mg\/dL/);
  assert.match(text, /Dhokla \(about 32 g\), simulated rise about 55 mg\/dL/);
});

test("describes, never prescribes: no dosing or medication-change instructions", () => {
  const { text } = check(base);
  assert.doesNotMatch(text, /\b(take|increase|decrease|reduce|stop|skip|inject)\b/i);
  assert.doesNotMatch(text, /metformin|glimepiride|units/i);
  assert.match(text, /does not change any medicine or treatment; please talk to your doctor/);
});

test("refuses: a number that does not trace (or sits on the wrong line) is reported", () => {
  const { text } = check(base);
  const facts = companionFacts(base);
  const tampered = text.replace("around 171 mg/dL", "around 163 mg/dL");
  assert.deepEqual(verifyGrounding(tampered, facts, COMPANION_SCOPES).untraced, ["163"]);
  // 94 is a real input (latest CGM), but it is not allowed on the meal-sensitivity line
  const wrongLine = text.replace("about 1.7 mg/dL", "about 94 mg/dL");
  assert.deepEqual(verifyGrounding(wrongLine, facts, COMPANION_SCOPES).untraced, ["94"]);
});

test("without a What-If scenario the doctor section has no numbers; low lower bound is explained, not alarming", () => {
  const low = structuredClone(base);
  low.scenario = null; low.swap = null;
  low.forecast!.trajectory[2] = t(120, 88, 64, 120);
  const { text, report } = check(low);
  assert.deepEqual(report.untraced, []);
  assert.match(text, /To discuss: your care team can use the twin's What-If comparison/);
  assert.match(text, /lower end dips under 70 mg\/dL, which your care team can explain/);
});
