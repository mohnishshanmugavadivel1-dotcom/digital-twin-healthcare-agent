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
