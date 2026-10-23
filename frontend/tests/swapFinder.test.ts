/** Automated meal-swap finder: deterministic filtering and ranking by the personalised twin curve. */
import assert from "node:assert/strict";
import { test } from "node:test";

import type { CounterfactualResult } from "../src/api/types.ts";
import { lowerBoundBelow } from "../src/format.ts";
import { MEAL_PRESETS } from "../src/mealPresets.ts";
import { SWAP_LABEL, candidateGrams, exclusionSummary, rankSwaps, swapTrigger, type SwapCandidate } from "../src/swapFinder.ts";

const SENS = 1.698, K = { 30: 0.1677, 60: 0.7107, 120: 1.0 }; // shape-like constants; only proportionality matters here
function result(grams: number, opts: { support?: string; lowerAt120?: number; untested?: boolean; prob?: number } = {}): CounterfactualResult {
  const d = (h: 30 | 60 | 120) => Math.round(K[h] * grams * SENS * 10) / 10;
  const traj = [30, 60, 90, 120].map((h) => ({ horizon_min: h, timestamp: "t", glucose_mg_dl: 150, lower_mg_dl: h === 120 ? (opts.lowerAt120 ?? 95) : 110, upper_mg_dl: 190 }));
  const fc = { status: "ok", trajectory: traj, excursion: { probability: opts.prob ?? 0.2, alert_threshold: 0.35 } };
  return {
    meal_grams: grams, as_of: "2026-03-08T02:25:00Z", scenario: fc, primary: { delta_glucose_mg_dl: {} },
    small_meal_unreliable: grams < 30,
    joint_support: { status: opts.support ?? "within_training_support" },
    twin_curve: { delta_glucose_mg_dl: { "30": d(30), "60": d(60), "120": d(120) },
                  walk_delta_glucose_mg_dl: { "120": -11.2 }, with_walk_delta_glucose_mg_dl: { "120": d(120) - 11.2 },
                  within_tested_range: !(opts.untested ?? false) && grams >= 20 && grams <= 120 },
  } as unknown as CounterfactualResult;
}
const lowFlag = (pts: { horizon_min: number; lower_mg_dl: number }[]) => lowerBoundBelow(pts) != null;
const all = (ref: number, f: (g: number) => CounterfactualResult | null = (g) => result(g)): SwapCandidate[] =>
  MEAL_PRESETS.map((p) => ({ preset: p, result: p.carbs < ref ? f(p.carbs) : null }));

test("label is the exact required wording and never mentions insulin or medication doses", () => {
  assert.equal(SWAP_LABEL, "Deterministic Twin Scenario Search (ranked by Personalised Twin Curve inside training support; educational simulation, not a clinical prescription).");
});

test("trigger: large meal (>= 60 g) or simulated risk at or above the alert threshold", () => {
  assert.equal(swapTrigger(68, result(68)).triggered, true);
  assert.equal(swapTrigger(35, result(35)).triggered, false);
  const risky = swapTrigger(45, result(45, { prob: 0.52 }));
  assert.equal(risky.triggered, true);
  assert.match(risky.reasons[0], /52% at or above the alert threshold 35%/);
});

test("top 3 for a 68 g meal: supported, >= 30 g, lower carbs, sorted by twin-curve rise (= grams), deterministic", () => {
  const ref = result(68).twin_curve!.delta_glucose_mg_dl["120"];
  const s = rankSwaps(68, ref, all(68), lowFlag);
  assert.equal(s.ranked.length, 3);
  assert.deepEqual(s.ranked.map((r) => r.preset.carbs), [32, 35, 35]);
  assert.deepEqual(s.ranked.map((r) => r.preset.id), ["dhokla", "idli2", "upma"].map((id) => MEAL_PRESETS.find((p) => p.id.startsWith(id))!.id));
  for (let i = 1; i < s.ranked.length; i++) assert.ok(s.ranked[i].rise120 >= s.ranked[i - 1].rise120);
  assert.ok(s.ranked.every((r) => r.rise120 < ref && r.withWalk120 != null));
  assert.equal(s.considered, MEAL_PRESETS.length);
  assert.deepEqual(rankSwaps(68, ref, all(68), lowFlag), s); // same inputs, same answer
  assert.match(exclusionSummary(s), /not lower in carbohydrate/);
  assert.match(exclusionSummary(s), /under 30 g/);
});

test("low watch, missing support, untested range and unavailable results are excluded, never ranked", () => {
  const s = rankSwaps(68, null, all(68, (g) =>
    g === 32 ? result(g, { lowerAt120: 64 }) : g === 35 ? result(g, { support: "no_training_analogue" }) : g === 36 ? null : g === 40 ? result(g, { untested: true }) : result(g)), lowFlag);
  const reasons = Object.fromEntries(s.excluded.filter((e) => [32, 35, 36, 40].includes(e.preset.carbs)).map((e) => [e.preset.id, e.reason]));
  assert.ok(Object.values(reasons).includes("low_watch"));
  assert.ok(Object.values(reasons).includes("outside_support"));
  assert.ok(Object.values(reasons).includes("unavailable"));
  assert.ok(Object.values(reasons).includes("untested"));
  assert.ok(s.ranked.every((r) => ![32, 35, 36, 40].includes(r.preset.carbs)));
  assert.deepEqual(s.ranked.map((r) => r.preset.carbs), [44, 45, 45]);
});

test("candidate grams are the distinct preset amounts below the reference", () => {
  assert.deepEqual(candidateGrams(MEAL_PRESETS, 36), [18, 22, 25, 28, 32, 35]);
});
