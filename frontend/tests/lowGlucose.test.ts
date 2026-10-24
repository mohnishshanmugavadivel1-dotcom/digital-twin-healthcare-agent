/**
 * Low-glucose lower-bound indicator: reports only whether a prediction-interval lower bound is below 70 mg/dL.
 *   node --experimental-strip-types --test tests/*.test.ts
 */
import assert from "node:assert/strict";
import { test } from "node:test";

import { hypoglycaemiaMedications, lowerBoundBelow } from "../src/format.ts";

const pts = (lows: number[]) => [30, 60, 90, 120].map((h, i) => ({ horizon_min: h, lower_mg_dl: lows[i] }));

test("no indicator when every lower bound is at or above 70", () => {
  assert.equal(lowerBoundBelow(pts([81, 101, 70, 141])), null);
});

test("reports the earliest horizon below 70 and the lowest bound", () => {
  assert.deepEqual(lowerBoundBelow(pts([82, 66, 58, 61])), { horizon_min: 60, lowest_mg_dl: 58 });
});

test("ignores horizons outside 30-120 min", () => {
  assert.equal(lowerBoundBelow([{ horizon_min: 15, lower_mg_dl: 50 }, { horizon_min: 150, lower_mg_dl: 40 }]), null);
});

test("medication context lists only sulfonylureas and insulin from the record", () => {
  const meds = [
    { name: "Metformin", drug_class: "biguanide" }, { name: "Glimepiride", drug_class: "sulfonylurea" },
    { name: "Insulin glargine", drug_class: "basal_insulin" },
  ];
  assert.deepEqual(hypoglycaemiaMedications(meds), ["Glimepiride (sulfonylurea)", "Insulin glargine (basal insulin)"]);
  assert.deepEqual(hypoglycaemiaMedications([{ name: "Metformin", drug_class: "biguanide" }]), []);
});

import { scenarioLowWatchCell } from "../src/format.ts";

test("What-If low watch cell: flag text, medication context, never a probability", () => {
  const pts = [{ horizon_min: 30, lower_mg_dl: 90 }, { horizon_min: 60, lower_mg_dl: 72 }, { horizon_min: 90, lower_mg_dl: 66 }, { horizon_min: 120, lower_mg_dl: 61 }];
  const c = scenarioLowWatchCell(pts, ["Glimepiride (sulfonylurea)"]);
  assert.equal(c.flagged, true);
  assert.equal(c.text, "<70 from +90m · SU/insulin");
  assert.match(c.title, /lowest 61 mg\/dL/);
  assert.match(c.title, /Not a probability/);
  const ok = scenarioLowWatchCell([{ horizon_min: 30, lower_mg_dl: 90 }], []);
  assert.deepEqual([ok.flagged, ok.text], [false, "–"]);
  assert.equal(scenarioLowWatchCell(undefined, []).flagged, false);
});
