import { useEffect, useMemo, useState } from "react";

import { api, IS_STATIC_DEMO } from "../api/client";
import type { FhirBundle } from "../api/types";
import type { HandoverInput } from "../handover";
import { HandoverCard } from "./HandoverCard";
import { fhirCodes, fhirResourceCounts, fhirRiskPredictions } from "../fhir";

/** FHIR R4 export of the synthetic patient: an interoperability prototype, loaded only when opened. */
export function FhirViewer({ patientId, handover = null }: { patientId: string; handover?: HandoverInput | null }) {
  const [bundle, setBundle] = useState<FhirBundle | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const copy = () => {
    if (!bundle) return;
    navigator.clipboard?.writeText(JSON.stringify(bundle, null, 2)).then(() => setCopied(true), () => setCopied(false));
  };
  const load = () => {
    if (bundle) return;
    api.fhir(patientId).then(setBundle).catch((e) => setError(String(e?.message ?? e)));
  };
  const href = useMemo(() => (bundle ? URL.createObjectURL(new Blob([JSON.stringify(bundle, null, 2)], { type: "application/fhir+json" })) : undefined), [bundle]);
  useEffect(() => () => { if (href) URL.revokeObjectURL(href); }, [href]);
  return (
    <details className="fhir" onToggle={(e) => { if ((e.target as HTMLDetailsElement).open) load(); }}>
      <summary>FHIR R4 record (interoperability prototype)</summary>
      <p className="muted tiny">
        Deterministic FHIR R4 (4.0.1) Bundle of this <b>synthetic</b> patient: Patient, Condition, MedicationStatement and
        Observation resources with LOINC, SNOMED CT and RxNorm codes, plus a RiskAssessment for the latest forecast
        (excursion probability; the low-glucose watch is a qualitative interval flag with no probability). Identifier: GlucoTwin's
        own synthetic ID namespace, not an ABHA number. eGFR has display text only (no method-matched LOINC code). Checked against the R4 resource structure; not
        certified, not profiled against ABDM/NRCeS guides, not a compliance claim, not for clinical use.
        {IS_STATIC_DEMO && <> <b>Static snapshot:</b> recorded once at the replay start; it does not advance with the replay.</>}
      </p>
      {error && <p className="sim-error small" role="alert">FHIR export unavailable: {error}</p>}
      {!bundle && !error && <p className="muted small">Loading…</p>}
      {bundle && (
        <>
          <p className="small">
            {fhirResourceCounts(bundle).map(([t, n]) => `${n} ${t}`).join(" · ")}
            {bundle.timestamp && <> · latest data {bundle.timestamp}</>}
            {" · "}<a href={href} download={`${bundle.id}.fhir.json`}>Download JSON</a>
            {" · "}<button type="button" className="link-button" onClick={copy}>{copied ? "Copied" : "Copy JSON"}</button>
          </p>
          {fhirRiskPredictions(bundle).length > 0 && (
            <ul className="fhir-risk small" aria-label="RiskAssessment predictions">
              {fhirRiskPredictions(bundle).map((p) => (
                <li key={p.outcome} title={p.rationale}>{p.outcome}{p.probability !== null
                  ? <> — probabilityDecimal <b>{p.probability.toFixed(3)}</b></> : <> — <i>qualitative flag, no probability</i></>}</li>
              ))}
            </ul>
          )}
          <div className="table-wrap">
            <table className="sim-table small" aria-label="Codes used in the FHIR export">
              <thead><tr><th scope="col">Resource</th><th scope="col">System</th><th scope="col">Code</th><th scope="col">Display</th><th scope="col">Count</th></tr></thead>
              <tbody>
                {fhirCodes(bundle).map((c) => (
                  <tr key={`${c.resourceType}-${c.system}-${c.code}`}><td>{c.resourceType}</td><td>{c.system}</td><td>{c.code}</td><td>{c.display}</td><td>{c.count}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
          <pre className="fhir-json">{JSON.stringify(bundle.entry.slice(0, 3), null, 2)}{"\n"}… first 3 of {bundle.entry.length} entries; download for the full Bundle</pre>
          {handover && (<>
            <p className="muted tiny">Handover note for the receiving clinician, from the twin's current state (the same note as below
              the chart; plain text, not a FHIR resource).</p>
            <HandoverCard input={handover} compact />
          </>)}
        </>
      )}
    </details>
  );
}
