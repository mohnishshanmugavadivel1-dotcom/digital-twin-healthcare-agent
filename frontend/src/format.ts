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
