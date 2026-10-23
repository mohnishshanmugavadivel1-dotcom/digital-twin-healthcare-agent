import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { CounterfactualResult } from "../api/types";
import { fmtDelta, lowerBoundBelow } from "../format";
import { GI_LABEL, MEAL_PRESETS, type MealPreset } from "../mealPresets";
import { EXCLUSION_TEXT, LARGE_MEAL_G, SWAP_LABEL, TOP_N, candidateGrams, exclusionSummary, rankSwaps, swapTrigger,
  type RankedSwap, type SwapSearch } from "../swapFinder";

export interface SwapReference { grams: number; label: string | null; result: CounterfactualResult }

/**
 * "Automated Gentle Meal-Swap Finder": simulates every lower-carbohydrate preset at the same moment and ranks the
 * supported ones by the personalised twin curve at +120 min. Logic and limits: ../swapFinder.ts.
 */
export function SwapFinder({ patientId, reference, onPick, onRanked }: {
  patientId: string; reference: SwapReference | null;
  onPick: (p: MealPreset) => void; onRanked: (top: RankedSwap | null) => void;
}) {
  const [search, setSearch] = useState<SwapSearch | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const token = useRef(0);
  const refKey = reference ? `${reference.result.as_of}|${reference.grams}` : "";
  const trigger = reference ? swapTrigger(reference.grams, reference.result) : null;

  const run = useCallback(async () => {
    if (!reference) return;
    const my = ++token.current;
    setBusy(true); setErr(null);
    try {
      const grams = candidateGrams(MEAL_PRESETS, reference.grams);
      const byGrams = new Map<number, CounterfactualResult | null>();
      for (let i = 0; i < grams.length; i += 4) { // a few at a time: the live API simulates each one
        const chunk = grams.slice(i, i + 4);
        const res = await Promise.all(chunk.map((g) => api.counterfactual(patientId, g).catch(() => null)));
        chunk.forEach((g, j) => byGrams.set(g, res[j]));
        if (my !== token.current) return;
      }
      const s = rankSwaps(reference.grams, reference.result.twin_curve?.delta_glucose_mg_dl["120"] ?? null,
        MEAL_PRESETS.map((p) => ({ preset: p, result: byGrams.get(p.carbs) ?? null })),
        (pts) => lowerBoundBelow(pts) != null);
      if (my !== token.current) return;
      setSearch(s); onRanked(s.ranked[0] ?? null);
    } catch (e) { if (my === token.current) setErr(e instanceof Error ? e.message : String(e)); }
    finally { if (my === token.current) setBusy(false); }
  }, [patientId, reference, onRanked]);

  useEffect(() => { // a new meal under consideration: forget the old search, run automatically when triggered
    token.current++; setSearch(null); setErr(null); setBusy(false); onRanked(null);
    if (reference && trigger?.triggered) void run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refKey]);

  if (!reference) return null;
  const preset = (r: RankedSwap) => MEAL_PRESETS.find((p) => p.id === r.preset.id)!;
  return (
    <section className="swap-finder" aria-label="Automated gentle meal-swap finder">
      <div className="swap-head">
        <b>Automated Gentle Meal-Swap Finder <span className="muted">(Twin Curve Search)</span></b>
        <span className="swap-label tiny">{SWAP_LABEL}</span>
      </div>
      <p className="small swap-trigger">
        Meal being considered: <b>{reference.grams} g</b>{reference.label ? ` · ${reference.label}` : ""}.{" "}
        {trigger?.triggered
          ? <>Search ran automatically: {trigger.reasons.join("; ")}.</>
          : <>No automatic search (it runs for a meal of at least {LARGE_MEAL_G} g or when the simulated risk reaches the alert threshold).{" "}
              {!search && !busy && <button type="button" className="link-button" onClick={() => void run()}>Search anyway</button>}</>}
      </p>
      {busy && <p className="muted small" aria-live="polite">Simulating lower-carbohydrate presets at this moment…</p>}
      {err && <p className="sim-error small" role="alert">Search failed: {err}</p>}
      {search && (search.ranked.length === 0
        ? <p className="small">No preset passed every check at this moment. {exclusionSummary(search)}.</p>
        : (<>
          <div className="table-wrap">
            <table className="swap-table small" aria-label={`Top ${TOP_N} supported lower-carbohydrate presets ranked by the personalised twin curve`}>
              <thead><tr>
                <th scope="col">#</th><th scope="col">Indian meal option</th><th scope="col">Carbs</th>
                <th scope="col" className="sim-twin">Twin curve Δ +120 min</th>
                <th scope="col" className="sim-twin">+ walk, Δ +120 min</th>
                <th scope="col">Low watch</th><th scope="col" aria-label="Use this option" />
              </tr></thead>
              <tbody>{search.ranked.map((r, i) => {
                const p = preset(r);
                return (
                  <tr key={r.preset.id}>
                    <td>{i + 1}</td>
                    <td className="swap-dish">{p.label} <span className="muted tiny swap-serving">{p.region}; {p.serving}</span>{" "}
                      <span className={`gi-badge gi-${p.gi.replace(/\s+/g, "-")} tiny`} title="Indicative, context only: not used in the ranking">{GI_LABEL[p.gi]}</span>
                      {p.basis === "team_estimate" && <span className="muted tiny"> · team est.</span>}</td>
                    <td>{p.carbs} g</td>
                    <td className="sim-twin">{fmtDelta(r.rise120)}</td>
                    <td className="sim-twin">{r.withWalk120 == null ? "–" : <>{fmtDelta(r.withWalk120)} <span className="muted tiny">(walk {fmtDelta(r.walk120)})</span></>}</td>
                    <td title="Lower edge of this scenario's 80% prediction interval stays at or above 70 mg/dL through +120 min. Not a guarantee.">not triggered</td>
                    <td><button type="button" className="link-button" title="Put this option into the What-If input (then Add scenario to compare)" onClick={() => onPick(p)}>Load</button></td>
                  </tr>
                );
              })}</tbody>
            </table>
          </div>
          <p className="muted tiny swap-why">
            Versus the meal being considered: twin curve {fmtDelta(reference.result.twin_curve?.delta_glucose_mg_dl["120"])} mg/dL at +120 min.
            Checked {search.considered} presets: {search.ranked.length} shown{search.excluded.length ? `; ${exclusionSummary(search)}` : ""}.
            {" "}<b>Why this order:</b> the personalised curve receives only grams of carbohydrate (grams × this patient's carb sensitivity ×
            a shared shape), so ranking by its rise is the same as ranking by grams; GI badges are context only. The walk effect depends on
            the latest CGM, not on the meal, so it is the same for every option. Research estimate on synthetic data (held-out MAE 5.9 mg/dL
            at +120 min); not about insulin or medicines.
          </p>
        </>))}
      {search && search.ranked.length === 0 && (
        <ul className="muted tiny">{Object.entries(EXCLUSION_TEXT).filter(([k]) => search.excluded.some((e) => e.reason === k)).map(([k, v]) => (
          <li key={k}>{v}: {search.excluded.filter((e) => e.reason === k).map((e) => e.preset.label).join(", ")}</li>))}</ul>
      )}
    </section>
  );
}
