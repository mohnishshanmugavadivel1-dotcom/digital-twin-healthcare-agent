/** personalUncertaintyText: confidence line for the personalised carb sensitivity (node --test). */
import assert from "node:assert/strict";
import { test } from "node:test";
import { personalUncertaintyText } from "../src/format.ts";

test("older snapshots without the field show nothing", () => {
  assert.equal(personalUncertaintyText({ meals_used: 4 }), null);
});

test("prior only and single meal", () => {
  assert.match(personalUncertaintyText({ meals_used: 0, observed_weight: 0 })!, /prior only/);
  assert.match(personalUncertaintyText({ meals_used: 1, observed_weight: 0.25 })!, /25% from 1 observed meal;/);
});

test("reports weight, SE and SD, never calls the SE a probability or posterior", () => {
  const t = personalUncertaintyText({ meals_used: 12, observed_weight: 0.8, response_sd_mg_dl_per_g: 0.5, sampling_se_mg_dl_per_g: 0.115 })!;
  assert.equal(t, "Confidence: 80% from 12 observed meals; ± 0.12 sampling error (meal-to-meal SD 0.50).");
  assert.doesNotMatch(t, /probab|posterior/i);
});
