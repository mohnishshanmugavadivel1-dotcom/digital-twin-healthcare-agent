/** Clinician handover note: deterministic template and independent numeric grounding check. */
import assert from "node:assert/strict";
import { test } from "node:test";

import type { AgpSummary, Forecast, TwinState } from "../src/api/types.ts";
import { buildHandover, groundingFacts, groundingLabel, numberTokens, verifyGrounding, type HandoverInput } from "../src/handover.ts";

const state: TwinState = {
  patient_id: "SYN-0039", as_of: "2026-03-08T02:25:00Z", version: 1, observations_ingested: 100,
  last_glucose_mg_dl: 94, glucose_trend_mg_dl_per_min: -0.34, trend_arrow: "stable", carbs_on_board_g: 3.2,
  minutes_since_last_meal: 645, steps_last_60min: 412, mean_heart_rate_30min: 71,
  summary_24h: { window_hours: 24, n_readings: 287, mean_mg_dl: 121.6, cv_percent: 28, time_in_range_pct: 88.4,
                 time_above_range_pct: 10.2, time_below_range_pct: 1.4 },
  personal: { carb_sensitivity_mg_dl_per_g: 1.698, carb_sensitivity_prior: 1.5, meals_used: 20 },
  data_quality: { cgm_completeness_3h: 0.972, minutes_since_last_cgm: 5, stale: false, gaps_over_30min_24h: 0 },
};
const t = (h: number, g: number, lo: number, hi: number) => ({ horizon_min: h, timestamp: "2026-03-08T04:25:00Z", glucose_mg_dl: g, lower_mg_dl: lo, upper_mg_dl: hi });
const forecast: Forecast = {
  forecast_id: "f", patient_id: "SYN-0039", issued_at: state.as_of, model_version: "test", status: "ok", reason: null,
  current_glucose_mg_dl: 94, trajectory: [t(30, 101.2, 84.6, 118.1), t(60, 112.7, 81.3, 141.9), t(90, 118.4, 73.2, 160.4), t(120, 121.9, 66.8, 172.5)],
  excursion: { event_definition: "glucose > 180 mg/dL within 120 min", horizon_min: 120, probability: 0.2237, alert_threshold: 0.35,
               alert: false, risk_band: "moderate", top_factors: [] },
  interval_level: 0.8, disclaimer: "",
};
const agp: AgpSummary = {
  patient_id: "SYN-0039", as_of: state.as_of, window_days: 14, days_with_data: 6.3, n_readings: 1812, coverage_pct: 44.9,
  sufficient: false, mean_mg_dl: 122.3, gmi_pct: 6.2, cv_pct: 31.9, tir_70_180_pct: 88.2, tar_181_250_pct: 10.4,
  tar_over_250_pct: 0, tbr_54_69_pct: 1.3, tbr_under_54_pct: 0.1, hourly: [], utc_offset_minutes: 330, note: "",
};
const input: HandoverInput = {
  record: { patient_id: "SYN-0039", display_name: "Lakshmi R. (synthetic)", age_years: 58, diabetes_duration_years: 9,
            utc_offset_minutes: 330, medications: [{ name: "Metformin", drug_class: "biguanide", dose: "500 mg twice daily" },
                                                   { name: "Glimepiride", drug_class: "sulfonylurea", dose: "2 mg once daily" }] },
  state, forecast, agp,
};

test("every number in the note traces to the inputs, and the note is deterministic", () => {
  const text = buildHandover(input).join("\n");
  assert.equal(text, buildHandover(structuredClone(input)).join("\n"));
  const r = verifyGrounding(text, groundingFacts(input));
  assert.deepEqual(r.untraced, []);
  assert.ok(r.total >= 30, `only ${r.total} numbers`);
  assert.ok(r.fromDefinitions >= 1 && r.fromData > r.fromDefinitions);
  assert.match(groundingLabel(r), /^Verified: 100% of numbers/);
  // the expected values really are in the text, in local time
  for (const frag of ["07:55 local time (UTC+05:30)", "94 mg/dL", "−0.3 mg/dL/min", "22%", "alert threshold 35%",
                      "+120 min 122", "80% prediction interval at +120 min 67-173", "from +120 min", "1.70 mg/dL per g from 20 meals",
                      "GMI 6.2%", "below the 14-day / 70% consensus minimum", "Glimepiride 2 mg once daily"]) {
    assert.ok(text.includes(frag), frag);
  }
});

test("a changed or invented number is caught", () => {
  const facts = groundingFacts(input);
  const text = buildHandover(input).join("\n");
  const tampered = text.replace("94 mg/dL", "93 mg/dL").replace("22%", "12%");
  const r = verifyGrounding(tampered, facts);
  assert.deepEqual(r.untraced, ["93", "12"]);
  assert.match(groundingLabel(r), /^NOT verified: 2 of/);
  // a real input value moved to the wrong line is caught too: 88 is the 24-h time in range, not a risk
  assert.deepEqual(verifyGrounding(text.replace("22%", "88%"), facts).untraced, ["88"]);
  // an added sentence has no scope, so any number in it fails
  assert.deepEqual(verifyGrounding(`${text}\nRisk falls to 22% after a walk.`, facts).untraced, ["22"]);
  // documented limit: a swap between two in-scope values on the same line (97 = 3-h completeness) is not detected
  assert.deepEqual(verifyGrounding(text.replace("94 mg/dL", "97 mg/dL"), facts).untraced, []);
});

test("the note describes and never instructs; it states its limits", () => {
  const text = buildHandover(input).join("\n");
  assert.doesNotMatch(text, /\b(recommend\w*|should|must|advise\w*|administer|titrat\w*|increase|decrease|give|start|stop)\b/i);
  assert.match(text, /not a diagnosis, not a treatment instruction/);
  assert.match(text, /synthetic/);
  assert.match(text, /not validated on real patients/);
  assert.match(text, /not a probability/);
});

test("withheld forecast and missing AGP are handled without inventing numbers", () => {
  const inp: HandoverInput = { ...input, agp: null,
    forecast: { ...forecast, status: "insufficient_data", reason: "fewer than 6 CGM readings in the last 30 min", trajectory: [], excursion: null } };
  const text = buildHandover(inp).join("\n");
  assert.match(text, /Model forecast: withheld \(fewer than 6 CGM readings in the last 30 min\)/);
  assert.doesNotMatch(text, /Glucose profile/);
  assert.deepEqual(verifyGrounding(text, groundingFacts(inp)).untraced, []);
});

test("number tokens keep clock times whole and split ranges", () => {
  assert.deepEqual(numberTokens("at 07:55 (UTC+05:30), 70-180, −0.3, 1.70"), ["07:55", "05:30", "70", "180", "0.3", "1.70"]);
});
