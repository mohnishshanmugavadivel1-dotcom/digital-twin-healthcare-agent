/**
 * FHIR viewer summaries, checked against the FHIR export recorded in the static snapshot.
 *   node --experimental-strip-types --test tests/*.test.ts
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { fhirCodes, fhirResourceCounts } from "../src/fhir.ts";

const dir = new URL("../static-demo/demo/", import.meta.url);
const sc = JSON.parse(readFileSync(new URL("early-warning.json", dir), "utf8"));

test("the static snapshot carries a recorded FHIR R4 Bundle for the scenario patient", () => {
  const b = sc.fhir.bundle;
  assert.equal(b.resourceType, "Bundle");
  assert.equal(b.type, "collection");
  assert.equal(sc.fhir.frame_index, 0);
  const patient = b.entry[0].resource;
  assert.equal(patient.resourceType, "Patient");
  assert.equal(patient.identifier[0].value, sc.patient_id);
  // recorded at the replay start: no CGM reading after the first frame's clock
  const clock = new Date(sc.frames[0].clock).getTime();
  for (const e of b.entry) if (e.resource.effectiveDateTime) assert.ok(new Date(e.resource.effectiveDateTime).getTime() <= clock);
});

test("counts and codes summarise the bundle", () => {
  const b = sc.fhir.bundle;
  const counts = Object.fromEntries(fhirResourceCounts(b));
  assert.equal(counts.Patient, 1);
  assert.equal(Object.values(counts).reduce((a: number, c) => a + (c as number), 0), b.entry.length);
  const codes = fhirCodes(b);
  const cgm = codes.find((c) => c.code === "99504-3");
  assert.ok(cgm && cgm.system === "LOINC" && cgm.count > 0);
  assert.ok(codes.some((c) => c.system === "SNOMED CT" && c.code === "44054006"));
});

import { fhirRiskPredictions } from "../src/fhir.ts";

test("RiskAssessment predictions: probability only where the resource carries one", () => {
  const b = { resourceType: "Bundle" as const, id: "x", type: "collection", entry: [
    { fullUrl: "urn:uuid:1", resource: { resourceType: "Patient" } },
    { fullUrl: "urn:uuid:2", resource: { resourceType: "RiskAssessment", prediction: [
      { outcome: { text: "Hyperglycaemic excursion" }, probabilityDecimal: 0.424, rationale: "model" },
      { outcome: { text: "Low-glucose watch" }, rationale: "NOT a probability" }] } }] };
  assert.deepEqual(fhirRiskPredictions(b).map((p) => p.probability), [0.424, null]);
  assert.equal(fhirRiskPredictions(b)[1].outcome, "Low-glucose watch");
});
