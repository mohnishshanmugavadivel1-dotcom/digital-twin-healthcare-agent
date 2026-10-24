/** Indian meal presets: approximate, editable, labelled; and the personalisation equation text. */
import assert from "node:assert/strict";
import { test } from "node:test";

import { personalRuleText } from "../src/format.ts";
import { GI_LABEL, MEAL_PRESETS, PRESET_NOTE, REGIONS, presetById, presetGrams, presetTitle, scenarioLabel } from "../src/mealPresets.ts";

test("presets are plausible, unique, within the API range, with serving sizes and a stated basis", () => {
  const ids = new Set(MEAL_PRESETS.map((p) => p.id));
  assert.equal(ids.size, MEAL_PRESETS.length);
  assert.equal(MEAL_PRESETS.length, 24);
  for (const p of MEAL_PRESETS) {
    assert.ok(p.carbs >= 1 && p.carbs <= 300, p.id);
    assert.ok(p.serving.length > 3, p.id);
    assert.ok(REGIONS.includes(p.region), p.id);
    assert.ok(p.giNote.length > 3 && GI_LABEL[p.gi], p.id);
    if (p.basis === "cited") {
      // cited presets are rounded source values: never more than 2.5 g outside what the cited sources report
      assert.ok(p.range && p.range[0] - 2.5 <= p.carbs && p.carbs <= p.range[1] + 2.5, `${p.id} value not backed by its sources`);
      assert.match(presetTitle(p), /cited range/);
    } else {
      // team estimates must never pose as sourced values
      assert.equal(p.range, null, p.id);
      assert.match(presetTitle(p), /team estimate, not source-verified/);
    }
    assert.match(presetTitle(p), /indicative/);
  }
  for (const r of REGIONS) assert.ok(MEAL_PRESETS.some((p) => p.region === r), r);
  assert.deepEqual(presetGrams(), [...presetGrams()].sort((a, b) => a - b));
  assert.match(PRESET_NOTE, /Approximate/);
  assert.match(PRESET_NOTE, /team estimates/);
  assert.match(PRESET_NOTE, /GI badges are indicative/);
  assert.match(PRESET_NOTE, /only sees grams of carbohydrate/);
});

test("scenario label is kept only while the grams still equal the preset (manual edits drop it)", () => {
  const idli = presetById("idli2")!;
  assert.match(scenarioLabel(idli.carbs, "idli2")!, /Idli.*approx\./);
  assert.equal(scenarioLabel(idli.carbs + 5, "idli2"), null);
  assert.equal(scenarioLabel(60, null), null);
  assert.equal(scenarioLabel(60, "no-such-preset"), null);
});

test("personalisation equation balances with the reported numbers", () => {
  // SYN-0039 at 07:55 in the recorded snapshot: prior 1.31, estimate 1.698 from 20 meals (values from the API)
  const p = { carb_sensitivity_mg_dl_per_g: 1.698, carb_sensitivity_prior: 1.31, meals_used: 20 };
  const t = personalRuleText(p);
  const m = /observed mean ≈ ([\d.]+)/.exec(t)!;
  const mean = Number(m[1]);
  const back = (3 * p.carb_sensitivity_prior + 20 * mean) / 23;
  assert.ok(Math.abs(back - p.carb_sensitivity_mg_dl_per_g) < 0.005, t);
  assert.match(t, /87% of the weight/);
  assert.match(personalRuleText({ ...p, meals_used: 0, carb_sensitivity_mg_dl_per_g: 1.31 }), /equals the prior/);
});
