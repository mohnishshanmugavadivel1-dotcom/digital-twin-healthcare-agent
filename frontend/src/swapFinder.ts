/**
 * Automated gentle meal-swap finder: a deterministic search over the Indian meal presets, ranked by the
 * personalised twin curve (research estimate) at +120 min.
 *
 * What it does, exactly:
 *  1. Reference = the meal being considered (the latest What-If scenario). The search runs automatically when that
 *     meal is large (>= LARGE_MEAL_G) or its simulated excursion risk is at or above the model's alert threshold.
 *  2. Candidates = presets with FEWER grams of carbohydrate than the reference, each simulated at the same "now".
 *  3. A candidate is dropped when: no result is available at this moment; it is under 30 g (the served model flags
 *     those meals unreliable, so its low watch cannot be trusted); it is outside B-23 training support; the twin
 *     curve is missing or outside its tested range (20-120 g, CGM <= 180 mg/dL); or the scenario's 80% lower bound
 *     falls below 70 mg/dL within 120 min (low watch).
 *  4. Survivors are sorted by the twin-curve rise at +120 min, then grams, then label; the top 3 are shown.
 *
 * Honest limits, also shown in the UI: the curve receives ONLY grams of carbohydrate (rise = grams x personal
 * sensitivity x a shared shape), so this order is the same as ordering by grams. GI badges are context only. The
 * walk effect depends on the latest CGM, not the meal, so it is the same for every candidate. Educational
 * simulation on synthetic data; never a prescription, never about insulin or medicines.
 *
 * Self-contained (type-only imports) so the Node test runner can load it directly.
 */
import type { CounterfactualResult } from "./api/types";

export const SWAP_LABEL = "Deterministic Twin Scenario Search (ranked by Personalised Twin Curve inside training support; " +
  "educational simulation, not a clinical prescription).";
export const LARGE_MEAL_G = 60;
export const SMALL_MEAL_G = 30;
export const TOP_N = 3;

export interface SwapPreset { id: string; label: string; region: string; carbs: number; gi: string; basis: string }
export interface SwapCandidate { preset: SwapPreset; result: CounterfactualResult | null }
export interface RankedSwap {
  preset: SwapPreset; rise30: number; rise60: number; rise120: number;
  withWalk120: number | null; walk120: number | null;
}
export type ExclusionReason = "not_lower" | "unavailable" | "under_30g" | "outside_support" | "no_curve" | "untested" | "low_watch" | "not_lower_rise";
export const EXCLUSION_TEXT: Record<ExclusionReason, string> = {
  not_lower: "not lower in carbohydrate than the meal being considered",
  unavailable: "no simulation available at this moment",
  under_30g: "under 30 g (served model unreliable, so the low watch cannot be checked)",
  outside_support: "outside training support (B-23)",
  no_curve: "no twin-curve estimate",
  untested: "outside the twin curve's tested range",
  low_watch: "low watch triggered (80% lower bound below 70 mg/dL)",
  not_lower_rise: "twin-curve rise not lower than the meal being considered",
};
export interface SwapSearch {
  ranked: RankedSwap[];
  excluded: { preset: SwapPreset; reason: ExclusionReason }[];
  considered: number;
}

export interface SwapTrigger { triggered: boolean; reasons: string[] }

/** Does the meal being considered call for an automatic search? */
export function swapTrigger(grams: number, ref: CounterfactualResult): SwapTrigger {
  const reasons: string[] = [];
  if (grams >= LARGE_MEAL_G) reasons.push(`large meal (${grams} g, threshold ${LARGE_MEAL_G} g)`);
  const ex = ref.scenario?.status === "ok" ? ref.scenario.excursion : null;
  if (ex && ex.probability >= ex.alert_threshold) {
    reasons.push(`simulated excursion risk ${Math.round(ex.probability * 100)}% at or above the alert threshold ${Math.round(ex.alert_threshold * 100)}%`);
  }
  return { triggered: reasons.length > 0, reasons };
}

/** Presets worth simulating for this reference: fewer grams than the meal being considered (distinct grams only). */
export function candidateGrams(presets: readonly SwapPreset[], referenceGrams: number): number[] {
  return [...new Set(presets.filter((p) => p.carbs < referenceGrams).map((p) => p.carbs))].sort((a, b) => a - b);
}

/**
 * Filter and rank. `lowFlag` receives the scenario trajectory and returns true when the low watch is triggered
 * (the UI passes the same check the What-If table uses).
 */
export function rankSwaps(referenceGrams: number, referenceRise120: number | null, candidates: SwapCandidate[],
  lowFlag: (points: { horizon_min: number; lower_mg_dl: number }[]) => boolean, topN = TOP_N): SwapSearch {
  const excluded: SwapSearch["excluded"] = [];
  const kept: RankedSwap[] = [];
  for (const { preset, result } of candidates) {
    const drop = (reason: ExclusionReason) => excluded.push({ preset, reason });
    if (preset.carbs >= referenceGrams) { drop("not_lower"); continue; }
    if (!result || !result.primary || result.scenario?.status !== "ok") { drop("unavailable"); continue; }
    if (result.small_meal_unreliable || preset.carbs < SMALL_MEAL_G) { drop("under_30g"); continue; }
    if (result.joint_support?.status !== "within_training_support") { drop("outside_support"); continue; }
    const tc = result.twin_curve;
    const r120 = tc?.delta_glucose_mg_dl["120"];
    if (!tc || r120 == null) { drop("no_curve"); continue; }
    if (!tc.within_tested_range) { drop("untested"); continue; }
    if (lowFlag(result.scenario.trajectory)) { drop("low_watch"); continue; }
    if (referenceRise120 != null && r120 >= referenceRise120) { drop("not_lower_rise"); continue; }
    kept.push({
      preset, rise30: tc.delta_glucose_mg_dl["30"], rise60: tc.delta_glucose_mg_dl["60"], rise120: r120,
      withWalk120: tc.with_walk_delta_glucose_mg_dl?.["120"] ?? null, walk120: tc.walk_delta_glucose_mg_dl?.["120"] ?? null,
    });
  }
  kept.sort((a, b) => a.rise120 - b.rise120 || a.preset.carbs - b.preset.carbs || a.preset.label.localeCompare(b.preset.label));
  return { ranked: kept.slice(0, topN), excluded, considered: candidates.length };
}

/** "3 not lower in carbohydrate…; 2 under 30 g…" in a fixed order. */
export function exclusionSummary(s: SwapSearch): string {
  const order = Object.keys(EXCLUSION_TEXT) as ExclusionReason[];
  return order.map((r) => [r, s.excluded.filter((e) => e.reason === r).length] as const)
    .filter(([, n]) => n > 0).map(([r, n]) => `${n} ${EXCLUSION_TEXT[r]}`).join("; ");
}
