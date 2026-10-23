/** Summaries of the FHIR R4 export for the viewer (pure; unit-tested in tests/fhir.test.ts). */
import type { FhirBundle } from "./api/types";

export interface FhirCode { resourceType: string; system: string; code: string; display: string; count: number }

const SYSTEM_NAMES: Record<string, string> = {
  "http://loinc.org": "LOINC", "http://snomed.info/sct": "SNOMED CT", "http://www.nlm.nih.gov/research/umls/rxnorm": "RxNorm",
};
export const systemName = (url: string) => SYSTEM_NAMES[url] ?? url;

export function fhirResourceCounts(b: FhirBundle): [string, number][] {
  const n = new Map<string, number>();
  for (const e of b.entry) n.set(e.resource.resourceType, (n.get(e.resource.resourceType) ?? 0) + 1);
  return [...n].sort((a, c) => a[0].localeCompare(c[0]));
}

/** Distinct clinical codes (Condition/Observation code, MedicationStatement medication), with how often each occurs. */
export function fhirCodes(b: FhirBundle): FhirCode[] {
  const out = new Map<string, FhirCode>();
  for (const { resource: r } of b.entry) {
    const concept = (r.code ?? r.medicationCodeableConcept) as { coding?: { system: string; code: string; display?: string }[] } | undefined;
    for (const c of concept?.coding ?? []) {
      const key = `${r.resourceType}|${c.system}|${c.code}`;
      const prev = out.get(key);
      if (prev) prev.count += 1;
      else out.set(key, { resourceType: r.resourceType, system: systemName(c.system), code: c.code, display: c.display ?? "", count: 1 });
    }
  }
  return [...out.values()];
}

export interface FhirRiskPrediction { outcome: string; probability: number | null; rationale: string }

/** RiskAssessment predictions. `probability` is set only when the resource itself carries probabilityDecimal. */
export function fhirRiskPredictions(b: FhirBundle): FhirRiskPrediction[] {
  const out: FhirRiskPrediction[] = [];
  for (const { resource: r } of b.entry) {
    if (r.resourceType !== "RiskAssessment") continue;
    for (const p of (r.prediction ?? []) as { outcome?: { text?: string }; probabilityDecimal?: number; rationale?: string }[]) {
      out.push({ outcome: p.outcome?.text ?? "", probability: typeof p.probabilityDecimal === "number" ? p.probabilityDecimal : null,
        rationale: p.rationale ?? "" });
    }
  }
  return out;
}
