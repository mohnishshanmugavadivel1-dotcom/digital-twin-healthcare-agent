/**
 * Display helpers for the what-if scenario table and API error messages (backlog B-22, UI fixes).
 *   node --experimental-strip-types --test tests/*.test.ts
 */
import assert from "node:assert/strict";
import { test } from "node:test";

import { comparisonCells, fmtDelta, formatApiError } from "../src/format.ts";

const cmp = (over: Partial<Parameters<typeof comparisonCells>[0] & object> = {}) => ({
  delta_glucose_mg_dl: { "30": 10.5, "60": 55.9, "90": 50, "120": 32.6 },
  delta_probability: 0.8097, reference_probability: 0.0727, risk_saturated: false, ...over,
});

test("signed deltas: one decimal, explicit plus, dash when unavailable", () => {
  assert.equal(fmtDelta(3.7), "+3.7");
  assert.equal(fmtDelta(-0.6), "-0.6");
  assert.equal(fmtDelta(0), "0.0");
  assert.equal(fmtDelta(null), "—");
  assert.equal(fmtDelta(undefined), "—");
  assert.equal(fmtDelta(Number.NaN), "—");
});

test("comparison cells show per-horizon deltas and reference → scenario risk", () => {
  const c = comparisonCells(cmp());
  assert.deepEqual([c.d30, c.d60, c.d120], ["+10.5", "+55.9", "+32.6"]);
  assert.equal(c.risk, "7% → 88%");
  assert.equal(c.riskQualified, false);
});

test("a saturated starting risk is qualified, never presented as a meaningful change", () => {
  const c = comparisonCells(cmp({ reference_probability: 0.9998, delta_probability: 0.0002, risk_saturated: true }));
  assert.equal(c.risk, ">99% → >99%");
  assert.equal(c.riskQualified, true);
  assert.match(c.riskTitle, /above 95%/);
});

test("withheld comparisons and missing risk render as placeholders", () => {
  const w = comparisonCells(null);
  assert.deepEqual([w.d30, w.d60, w.d120, w.risk], ["—", "—", "—", "n/a"]);
  const noRisk = comparisonCells(cmp({ delta_probability: null, reference_probability: null }));
  assert.equal(noRisk.risk, "n/a");
  assert.equal(comparisonCells(cmp({ delta_glucose_mg_dl: { "60": 1 } })).d30, "—");
});

test("REGRESSION: FastAPI validation errors are readable, not raw JSON", () => {
  const body = { detail: [{ type: "less_than_equal", loc: ["body", "start_offset_hours"], msg: "Input should be less than or equal to 8784", input: 99999 }] };
  const msg = formatApiError(422, body);
  assert.equal(msg, "Invalid request: start offset hours: Input should be less than or equal to 8784");
  assert.ok(!msg.includes("{") && !msg.includes("["));
});

test("string details, duplicated prefixes and non-JSON bodies", () => {
  assert.equal(formatApiError(404, { detail: "not found: NOPE" }), "Not found: NOPE");
  assert.equal(formatApiError(404, { detail: "SYN-0001 is not a held-out test patient" }), "Not found: SYN-0001 is not a held-out test patient");
  assert.equal(formatApiError(500, undefined, "Internal Server Error"), "Request failed (500): Internal Server Error");
  assert.equal(formatApiError(503, "oops"), "Request failed (503)");
  assert.equal(formatApiError(422, { detail: [{}] }), "Invalid request: invalid value");
});

// ---------------------------------------------------------------- B-23 joint training support
import { jointSupportChip } from "../src/format.ts";

test("joint support: chip only when the scenario has no training analogue", () => {
  const chip = jointSupportChip({
    status: "no_training_analogue",
    message: "No comparable training example: another meal was logged 30-60 min earlier (no training meal had one).",
    caveat: "Training-support check: it flags meal inputs with no comparable example in the training data.",
  });
  assert.ok(chip);
  assert.equal(chip.label, "outside training support");
  assert.match(chip.title, /30-60 min earlier/);
  assert.match(chip.title, /Training-support check/);
  // the label is shown inline: worded as training support, never as an error (the caveat itself says "not evidence
  // that the forecast is wrong", so only the label is checked)
  assert.doesNotMatch(chip.label, /\b(error|wrong|invalid|unsafe)\b/i);
});

test("joint support: no chip when within support, unavailable, or absent (older servers)", () => {
  assert.equal(jointSupportChip({ status: "within_training_support" }), null);
  assert.equal(jointSupportChip({ status: "unavailable", message: null }), null);
  assert.equal(jointSupportChip(null), null);
  assert.equal(jointSupportChip(undefined), null);
});
