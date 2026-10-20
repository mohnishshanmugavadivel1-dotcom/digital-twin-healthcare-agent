/**
 * Regression tests for the glucose-chart tooltip formatter (run with the
 * Node test runner, no browser or extra dependency needed):
 *   node --experimental-strip-types --test tests/format.test.ts
 *
 * The defect (2026-10-20): Recharts includes the X-axis's dataKey entry
 * ("t", an epoch-ms timestamp) in the tooltip payload, and the chart's
 * fall-through branch rendered any unknown entry as a glucose value,
 * producing the line "t : 1772447220000 mg/dL".
 */
import assert from "node:assert/strict";
import { test } from "node:test";

import { formatChartTooltipEntry } from "../src/format.ts";

test("REGRESSION: the axis timestamp entry is never rendered as a glucose value", () => {
  assert.equal(formatChartTooltipEntry(1772447220000, "t", undefined), null);
  assert.equal(formatChartTooltipEntry(1772447220000, "t", { t: 1772447220000, v: 89 }), null);
});

test("genuine glucose series render rounded mg/dL under their own name", () => {
  assert.deepEqual(formatChartTooltipEntry(89.4, "CGM", { t: 0, v: 89.4 }), ["89 mg/dL", "CGM"]);
  assert.deepEqual(formatChartTooltipEntry(204.7, "Forecast", { t: 0, v: 204.7 }), ["205 mg/dL", "Forecast"]);
  assert.deepEqual(
    formatChartTooltipEntry(197, "What-if meal (simulated)", { t: 0, v: 197 }),
    ["197 mg/dL", "What-if meal (simulated)"],
  );
  assert.deepEqual(
    formatChartTooltipEntry(103, "Past 60-min prediction", { t: 0, v: 103 }),
    ["103 mg/dL", "Past 60-min prediction"],
  );
});

test("interval bands render as a range; meal markers show grams from the row", () => {
  assert.deepEqual(
    formatChartTooltipEntry([186.4, 223.0], "80% interval", { t: 0, band: [186.4, 223.0] }),
    ["186.4–223 mg/dL", "80% interval"],
  );
  assert.deepEqual(
    formatChartTooltipEntry([150, 180], "What-if 80% interval (simulated)", { t: 0, band: [150, 180] }),
    ["150–180 mg/dL", "80% interval"],
  );
  assert.deepEqual(formatChartTooltipEntry(52, "Logged meal", { t: 0, v: 52, mealG: 140 }), ["140 g carbs", "Meal"]);
  // a meal row without grams must not fabricate a value
  assert.equal(formatChartTooltipEntry(52, "Logged meal", { t: 0, v: 52 }), null);
});

test("null, non-finite, and unknown-series entries are skipped entirely", () => {
  assert.equal(formatChartTooltipEntry(null, "CGM", { t: 0, v: null }), null);
  assert.equal(formatChartTooltipEntry(undefined, "CGM", undefined), null);
  assert.equal(formatChartTooltipEntry(NaN, "Forecast", { t: 0 }), null);
  // any series added to the chart later must opt in explicitly, never fall through to mg/dL
  assert.equal(formatChartTooltipEntry(123, "SomeFutureSeries", { t: 0, v: 123 }), null);
});
