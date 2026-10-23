// Times are shown in the patient's local clock (record.utc_offset_minutes), labelled as such.
export const toMs = (iso: string) => new Date(iso).getTime();

export function localParts(ms: number, offsetMin: number) {
  const d = new Date(ms + offsetMin * 60_000);
  return { d, hh: String(d.getUTCHours()).padStart(2, "0"), mm: String(d.getUTCMinutes()).padStart(2, "0") };
}

export const fmtTime = (ms: number, offsetMin: number) => {
  const { hh, mm } = localParts(ms, offsetMin);
  return `${hh}:${mm}`;
};

const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
export const fmtDateTime = (ms: number, offsetMin: number) => {
  const { d, hh, mm } = localParts(ms, offsetMin);
  return `${DAYS[d.getUTCDay()]} ${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} · ${hh}:${mm}`;
};

export const fmtOffset = (offsetMin: number) => {
  const sign = offsetMin >= 0 ? "+" : "-";
  const a = Math.abs(offsetMin);
  return `UTC${sign}${String(Math.floor(a / 60)).padStart(2, "0")}:${String(a % 60).padStart(2, "0")}`;
};

export const num = (v: number | null | undefined, digits = 0, suffix = "") =>
  v === null || v === undefined || Number.isNaN(v) ? "–" : `${v.toFixed(digits)}${suffix}`;

export const pct = (v: number | null | undefined, digits = 0) => (v === null || v === undefined ? "–" : `${(v * 100).toFixed(digits)}%`);

export const ARROWS: Record<string, string> = {
  rising_fast: "⇈", rising: "↗", stable: "→", falling: "↘", falling_fast: "⇊", unknown: "?",
};
export const ARROW_TEXT: Record<string, string> = {
  rising_fast: "rising fast (>2 mg/dL/min)", rising: "rising (1–2 mg/dL/min)", stable: "stable (<1 mg/dL/min)",
  falling: "falling (1–2 mg/dL/min)", falling_fast: "falling fast (>2 mg/dL/min)", unknown: "trend unavailable",
};

export function glucoseClass(g: number | null | undefined) {
  if (g === null || g === undefined) return "";
  if (g < 70) return "g-low";
  if (g > 180) return "g-high";
  return "g-ok";
}

/** Risk as a percentage that never displays false certainty: >99% / <1% at the extremes. */
export const riskPct = (v: number | null | undefined) =>
  v === null || v === undefined ? "–" : v >= 0.995 ? ">99%" : v < 0.005 ? "<1%" : `${Math.round(v * 100)}%`;

/** The row shape the glucose chart feeds its tooltip (only the fields the formatter reads). */
export interface ChartTipRow { t: number; v?: number | null; band?: [number, number]; mealG?: number }

const GLUCOSE_SERIES = new Set(["CGM", "Forecast", "What-if meal (simulated)", "Past 60-min prediction"]);

/**
 * Tooltip entry formatter for the glucose chart. Recharts hands the formatter
 * EVERY tooltip payload entry — including the X-axis's own dataKey entry
 * ("t", an epoch-millisecond timestamp), which the chart's old fall-through
 * branch rendered as "t : 1772447220000 mg/dL". Only genuine glucose-valued
 * series may display "mg/dL": the hovered time is already the tooltip label
 * (labelFormatter renders it in the patient's local clock), so unknown or
 * non-glucose entries return null, which Recharts' tooltip renderer treats as
 * "skip this row" (DefaultTooltipContent returns null for them). Bands (the
 * 80% interval series) render as a range, meal markers as grams of carbs.
 * Returns [value, name] for entries to display, null to omit the row.
 */
export function formatChartTooltipEntry(value: unknown, name: string, row?: ChartTipRow): [string, string] | null {
  if (name === "Logged meal") {
    return row?.mealG != null ? [`${row.mealG} g carbs`, "Meal"] : null;
  }
  if (Array.isArray(value)) {
    return [`${value[0]}–${value[1]} mg/dL`, "80% interval"];
  }
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  if (GLUCOSE_SERIES.has(name)) return [`${Math.round(value)} mg/dL`, name];
  return null;
}

/** Signed delta with one decimal ("+3.7", "-0.6", "0.0"); "—" when unavailable. */
export const fmtDelta = (d: number | null | undefined) =>
  d === null || d === undefined || !Number.isFinite(d) ? "—" : (d > 0 ? "+" : "") + d.toFixed(1);

/** The comparison fields the scenario table reads (structural, so tests need no API types). */
export interface ComparisonLike {
  delta_glucose_mg_dl: Record<string, number>;
  delta_probability: number | null; reference_probability: number | null; risk_saturated: boolean;
}

export interface ComparisonCells {
  d30: string; d60: string; d120: string;
  risk: string; riskQualified: boolean; riskTitle: string;
}

/**
 * Display values for one what-if comparison row. A withheld comparison renders as dashes;
 * a saturated starting risk (> 95 %) is flagged so the UI greys it out instead of
 * presenting a near-zero change as meaningful.
 */
export function comparisonCells(cmp: ComparisonLike | null | undefined): ComparisonCells {
  if (!cmp) return { d30: "—", d60: "—", d120: "—", risk: "n/a", riskQualified: false, riskTitle: "Withheld" };
  const d = (h: number) => fmtDelta(cmp.delta_glucose_mg_dl[String(h)]);
  const p0 = cmp.reference_probability;
  const p1 = p0 !== null && cmp.delta_probability !== null ? p0 + cmp.delta_probability : null;
  const risk = p0 === null || p1 === null ? "n/a" : `${riskPct(p0)} → ${riskPct(p1)}`;
  return {
    d30: d(30), d60: d(60), d120: d(120), risk, riskQualified: cmp.risk_saturated,
    riskTitle: cmp.risk_saturated
      ? "Starting risk is already above 95%, so the risk change is not informative"
      : "Excursion risk of the reference leg → risk with the hypothetical meal",
  };
}

/**
 * Human-readable message for a failed API call. FastAPI returns {"detail": string} for
 * 4xx errors raised by the app and {"detail": [{loc, msg, ...}]} for validation (422)
 * errors; the latter used to reach the screen as raw JSON.
 */
export function formatApiError(status: number, body: unknown, statusText = ""): string {
  const detail = body && typeof body === "object" && "detail" in body ? (body as { detail: unknown }).detail : undefined;
  const prefix = status === 422 ? "Invalid request" : status === 404 ? "Not found" : `Request failed (${status})`;
  if (typeof detail === "string" && detail) {
    // the API already says "not found: X" — don't print "Not found: not found: X"
    return detail.toLowerCase().startsWith(prefix.toLowerCase()) ? prefix + detail.slice(prefix.length) : `${prefix}: ${detail}`;
  }
  if (Array.isArray(detail) && detail.length) {
    const parts = detail.map((e) => {
      const item = (e ?? {}) as { loc?: unknown[]; msg?: string };
      const field = Array.isArray(item.loc) ? item.loc.filter((x) => x !== "body" && x !== "query").join(".") : "";
      const msg = typeof item.msg === "string" ? item.msg : "invalid value";
      return field ? `${field.replace(/_/g, " ")}: ${msg}` : msg;
    });
    return `${prefix}: ${parts.join("; ")}`;
  }
  return statusText ? `${prefix}: ${statusText}` : prefix;
}

/** B-23: chip for a what-if whose meal inputs have no comparable training example; null otherwise.
 * Worded as training support, never as an error: unavailable or in-support checks show nothing. */
export interface JointSupportLike { status: string; message?: string | null; caveat?: string }
export function jointSupportChip(js: JointSupportLike | null | undefined): { label: string; title: string } | null {
  if (!js || js.status !== "no_training_analogue") return null;
  const title = [js.message ?? "No comparable example in the training data.", js.caveat ?? ""].filter(Boolean).join(" ");
  return { label: "outside training support", title };
}

/** Pseudo-meals of prior weight; must equal CARB_SENS_SHRINKAGE_K in src/glucotwin/features.py. */
export const CARB_SENS_SHRINKAGE_K = 3;

/**
 * The personalised carb-sensitivity update, with the patient's own numbers (features.personal_carb_sensitivity):
 *   s = (K · prior + Σ observed rise per gram) / (K + n),  K = 3 pseudo-meals.
 * Reconstructs the sum of observed ratios from the reported values so the displayed equation balances.
 */
export function personalRuleText(p: { carb_sensitivity_mg_dl_per_g: number; carb_sensitivity_prior: number; meals_used: number }): string {
  const K = CARB_SENS_SHRINKAGE_K, n = p.meals_used;
  if (n <= 0) return `No meal response counted yet, so the estimate equals the prior: s = ${p.carb_sensitivity_prior.toFixed(2)} mg/dL per g.`;
  const observedMean = (p.carb_sensitivity_mg_dl_per_g * (K + n) - K * p.carb_sensitivity_prior) / n;
  const w = n / (K + n);
  return `s = (${K} × prior ${p.carb_sensitivity_prior.toFixed(2)} + ${n} × observed mean ≈ ${observedMean.toFixed(2)}) / (${K} + ${n}) = ` +
    `${p.carb_sensitivity_mg_dl_per_g.toFixed(2)} mg/dL per g; the observed meals carry ${Math.round(w * 100)}% of the weight.`;
}
