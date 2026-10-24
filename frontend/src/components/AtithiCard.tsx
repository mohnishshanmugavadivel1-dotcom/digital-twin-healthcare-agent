import { useMemo } from "react";

import { COMPANION_SCOPES, buildCompanion, companionFacts, companionText, groundingLabel, verifyGrounding, type CompanionInput } from "../handover";

/**
 * Atithi (patient) plain-language companion summary. Same fixed-template approach and the SAME numeric
 * verifier as the clinician handover note: if any number fails to trace, the summary is not shown.
 */
export function AtithiCard({ input }: { input: CompanionInput | null }) {
  const out = useMemo(() => {
    if (!input) return null;
    const sections = buildCompanion(input);
    return { sections, report: verifyGrounding(companionText(sections), companionFacts(input), COMPANION_SCOPES) };
  }, [input]);
  if (!out) return null;
  const ok = out.report.untraced.length === 0;
  return (
    <details className="card handover atithi" open>
      <summary>Atithi (Patient) Plain-Language Companion Summary <span className="muted tiny">(fact-grounded, fixed template)</span></summary>
      <p className={`grounding small ${ok ? "grounding-ok" : "grounding-bad"}`} role={ok ? undefined : "alert"}
         title="The same parser as the clinician note re-reads this summary, extracts every number and checks each one against the field its line describes. It does not check whether the forecast is right.">
        {ok ? "✓ " : "✗ "}{ok ? groundingLabel(out.report) : `Summary withheld. ${groundingLabel(out.report)}`}
      </p>
      {ok && (
        <div className="atithi-sections">
          {out.sections.map((s) => (
            <section key={s.section}>
              <h4>{s.section}</h4>
              <ul className="handover-lines small">{s.lines.map((l) => <li key={l}>{l}</li>)}</ul>
            </section>
          ))}
        </div>
      )}
      <p className="muted tiny">"Atithi" (guest) follows Happiest Health's wording for the people it serves. Synthetic patient; research prototype.</p>
    </details>
  );
}
