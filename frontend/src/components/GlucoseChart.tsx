import {
  Area, CartesianGrid, ComposedChart, Line, ReferenceArea, ReferenceLine, Scatter, Tooltip, XAxis, YAxis,
} from "recharts";
import type { Forecast, ForecastSummary, Observation } from "../api/types";
import { fmtTime, toMs } from "../format";
import { useWidth } from "../useWidth";

interface Props {
  cgm: Observation[];
  meals: Observation[];
  forecast: Forecast | null;
  scenario?: Forecast | null;
  history: ForecastSummary[];
  clockMs: number;
  offsetMin: number;
  windowHours: number;
  showPastPredictions: boolean;
}

type Pt = { t: number; v?: number | null; band?: [number, number]; mealG?: number };

export function GlucoseChart({ cgm, meals, forecast, scenario, history, clockMs, offsetMin, windowHours, showPastPredictions }: Props) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const startMs = clockMs - windowHours * 3600_000;
  const endMs = clockMs + 2.25 * 3600_000;
  // Each series has its own data array; CGM gaps > 10 min are broken explicitly (never drawn across).
  const cgmPts: Pt[] = [];
  let prev: number | null = null;
  for (const o of cgm) {
    const t = toMs(o.timestamp);
    if (t < startMs) continue;
    if (prev !== null && t - prev > 10 * 60_000) cgmPts.push({ t: prev + 5 * 60_000, v: null });
    cgmPts.push({ t, v: o.value });
    prev = t;
  }
  const fcPts: Pt[] = [];
  if (forecast?.status === "ok" && forecast.current_glucose_mg_dl !== null) {
    const g0 = forecast.current_glucose_mg_dl;
    fcPts.push({ t: toMs(forecast.issued_at), v: g0, band: [g0, g0] });
    for (const p of forecast.trajectory) fcPts.push({ t: toMs(p.timestamp), v: p.glucose_mg_dl, band: [p.lower_mg_dl, p.upper_mg_dl] });
  }
  const pastPts: Pt[] = showPastPredictions
    ? history.flatMap((h) => {
        const v = h.predicted["60"];
        const t = toMs(h.issued_at) + 60 * 60_000;
        return v !== undefined && t >= startMs && t <= clockMs ? [{ t, v }] : [];
      })
    : [];
  // Simulated what-if scenario (never ingested): dashed orange overlay on the same axis.
  const scenPts: Pt[] = [];
  if (scenario?.status === "ok" && scenario.current_glucose_mg_dl !== null) {
    const g0 = scenario.current_glucose_mg_dl;
    scenPts.push({ t: toMs(scenario.issued_at), v: g0, band: [g0, g0] });
    for (const p of scenario.trajectory) scenPts.push({ t: toMs(p.timestamp), v: p.glucose_mg_dl, band: [p.lower_mg_dl, p.upper_mg_dl] });
  }
  const mealPts: Pt[] = meals.filter((m) => toMs(m.timestamp) >= startMs).map((m) => ({ t: toMs(m.timestamp), v: 52, mealG: m.value }));

  const ticks: number[] = [];
  const firstTick = Math.ceil(startMs / 3600_000) * 3600_000;
  for (let t = firstTick; t <= endMs; t += 2 * 3600_000) ticks.push(t);

  return (
    <div className="chart-wrap" ref={ref} role="img" aria-label="Glucose history and two-hour forecast">
      {width > 0 && (
        <ComposedChart width={width} height={340} margin={{ top: 10, right: 16, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="#e7ebf0" vertical={false} />
          <ReferenceArea y1={70} y2={180} fill="#e8f5ee" fillOpacity={0.7} ifOverflow="hidden" />
          <ReferenceArea x1={clockMs} x2={endMs} fill="#f4f6fa" fillOpacity={0.9} ifOverflow="hidden" />
          <XAxis dataKey="t" type="number" allowDuplicatedCategory={false} scale="time" domain={[startMs, endMs]} ticks={ticks}
                 tickFormatter={(t) => fmtTime(t, offsetMin)} tick={{ fontSize: 12, fill: "#5b6573" }} />
          <YAxis domain={[40, 350]} ticks={[40, 70, 100, 140, 180, 250, 350]} tick={{ fontSize: 12, fill: "#5b6573" }}
                 width={44} label={{ value: "mg/dL", angle: -90, position: "insideLeft", fontSize: 11, fill: "#5b6573" }} />
          <ReferenceLine y={180} stroke="#d98a1f" strokeDasharray="4 3" label={{ value: "180", position: "right", fontSize: 11, fill: "#a5650f" }} />
          <ReferenceLine y={70} stroke="#c0392b" strokeDasharray="4 3" label={{ value: "70", position: "right", fontSize: 11, fill: "#c0392b" }} />
          <ReferenceLine x={clockMs} stroke="#334155" label={{ value: "now", position: "top", fontSize: 11, fill: "#334155" }} />
          <Area data={fcPts} dataKey="band" stroke="none" fill="#6c8ef5" fillOpacity={0.18} isAnimationActive={false} name="80% interval" />
          {scenPts.length > 0 && <Area data={scenPts} dataKey="band" stroke="none" fill="#e8590c" fillOpacity={0.10} isAnimationActive={false} name="What-if 80% interval (simulated)" />}
          <Line data={cgmPts} dataKey="v" stroke="#1f2a44" strokeWidth={2} dot={false} connectNulls={false} isAnimationActive={false} name="CGM" />
          <Line data={fcPts} dataKey="v" stroke="#3b5bdb" strokeWidth={2} strokeDasharray="6 4" dot={{ r: 3 }} isAnimationActive={false} name="Forecast" />
          {scenPts.length > 0 && <Line data={scenPts} dataKey="v" stroke="#e8590c" strokeWidth={2} strokeDasharray="2 4" dot={false} isAnimationActive={false} name="What-if meal (simulated)" />}
          {showPastPredictions && <Scatter data={pastPts} dataKey="v" fill="#9aa8c7" shape={(p: { cx?: number; cy?: number }) => <circle cx={p.cx} cy={p.cy} r={2.5} fill="#8d9bbd" />} isAnimationActive={false} name="Past 60-min prediction" />}
          <Scatter data={mealPts} dataKey="v" fill="#2f9e44" shape="triangle" isAnimationActive={false} name="Logged meal" />
          <Tooltip
            labelFormatter={(t) => fmtTime(Number(t), offsetMin)}
            formatter={(value, name, item) => {
              if (name === "Logged meal") return [`${(item.payload as Pt).mealG ?? ""} g carbs`, "Meal"];
              if (Array.isArray(value)) return [`${value[0]}–${value[1]} mg/dL`, "80% interval"];
              return [`${Math.round(Number(value))} mg/dL`, String(name)];
            }}
          />
        </ComposedChart>
      )}
      <div className="legend">
        <span><i className="sw sw-cgm" /> CGM (observed)</span>
        <span><i className="sw sw-fc" /> Twin forecast</span>
        <span><i className="sw sw-band" /> 80% prediction interval</span>
        <span><i className="sw sw-range" /> Target range 70–180</span>
        <span><i className="sw sw-meal" /> Logged meal</span>
        {showPastPredictions && <span><i className="sw sw-past" /> Earlier 60-min predictions</span>}
        {scenPts.length > 0 && <span><i className="sw sw-scen" /> What-if meal (simulated, not in record)</span>}
      </div>
    </div>
  );
}
