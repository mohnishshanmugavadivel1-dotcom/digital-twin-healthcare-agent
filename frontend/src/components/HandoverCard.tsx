import { useMemo, useState } from "react";

import { buildHandover, groundingFacts, groundingLabel, verifyGrounding, type HandoverInput } from "../handover";

/**
 * Clinician handover note from a fixed template, with the numeric grounding check shown beside it.
 * Rendered in the patient view and inside the FHIR drawer (`compact`).
 */
export function HandoverCard({ input, compact = false }: { input: HandoverInput | null; compact?: boolean }) {
  const [copied, setCopied] = useState(false);
  const note = useMemo(() => {
    if (!input) return null;
    const lines = buildHandover(input);
    const text = lines.join("\n");
    return { lines, text, report: verifyGrounding(text, groundingFacts(input)) };
  }, [input]);
  if (!note) return null;
  const ok = note.report.untraced.length === 0;
  const copy = () => {
    if (!ok) return;
    navigator.clipboard?.writeText(note.text).then(() => setCopied(true), () => setCopied(false));
  };
  return (
    <details className={`handover${compact ? " handover-compact" : " card"}`} open={!compact}>
      <summary>Clinician handover note <span className="muted tiny">(fact-grounded, fixed template)</span></summary>
      <p className={`grounding small ${ok ? "grounding-ok" : "grounding-bad"}`} role={ok ? undefined : "alert"}
         title="A separate parser re-reads the finished note, extracts every number and checks that each one is a value of a field the line describes, or a stated threshold. It does not check whether the forecast is right, and a swap between two values on the same line would not be caught.">
        {ok ? "✓ " : "✗ "}{groundingLabel(note.report)}
      </p>
      {ok && (
        <ul className="handover-lines small">
          {note.lines.map((l) => <li key={l}>{l}</li>)}
        </ul>
      )}
      {ok && (
        <div className="small handover-actions">
          <button type="button" className="link-button" onClick={copy}>{copied ? "Copied" : "Copy note"}</button>
          {" · "}
          <details className="handover-sources">
            <summary className="link-button">Where each number comes from</summary>
            <div className="table-wrap">
              <table className="sim-table small" aria-label="Source of each number in the handover note">
                <thead><tr><th scope="col">Number</th><th scope="col">Source</th></tr></thead>
                <tbody>{note.report.sources.map((s, i) => <tr key={`${i}-${s.token}`}><td>{s.token}</td><td>{s.source}</td></tr>)}</tbody>
              </table>
            </div>
          </details>
        </div>
      )}
    </details>
  );
}
