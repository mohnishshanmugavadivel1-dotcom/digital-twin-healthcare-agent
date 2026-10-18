import { Area, AreaChart, CartesianGrid, ReferenceLine, Tooltip, XAxis, YAxis } from "recharts";
import type { ForecastSummary } from "../api/types";
import { fmtTime, toMs } from "../format";
import { useWidth } from "../useWidth";

export function RiskTimeline({ history, threshold, clockMs, offsetMin, windowHours }: {
  history: ForecastSummary[]; threshold: number | null; clockMs: number; offsetMin: number; windowHours: number;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const startMs = clockMs - windowHours * 3600_000;
  const endMs = clockMs + 2.25 * 3600_000; // aligned with the glucose chart above
  const data = history
    .map((h) => ({ t: toMs(h.issued_at), p: h.probability === null ? null : Math.round(h.probability * 100) }))
    .filter((d) => d.t >= startMs);
  const ticks: number[] = [];
  for (let t = Math.ceil(startMs / 3600_000) * 3600_000; t <= endMs; t += 2 * 3600_000) ticks.push(t);
  return (
    <div className="card">
      <h3>Risk history <span className="muted small">(probability of excursion onset within 2 h, as estimated at each reading)</span></h3>
      <div ref={ref}>{width > 0 && (
        <AreaChart width={width} height={130} data={data} margin={{ top: 6, right: 16, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="#eef1f5" vertical={false} />
          <XAxis dataKey="t" type="number" scale="time" domain={[startMs, endMs]} ticks={ticks}
                 tickFormatter={(t) => fmtTime(t, offsetMin)} tick={{ fontSize: 11, fill: "#5b6573" }} />
          <YAxis domain={[0, 100]} ticks={[0, 50, 100]} width={44} tick={{ fontSize: 11, fill: "#5b6573" }} unit="%" />
          {threshold !== null && <ReferenceLine y={threshold * 100} stroke="#d98a1f" strokeDasharray="4 3" />}
          <ReferenceLine x={clockMs} stroke="#334155" />
          <Area dataKey="p" stroke="#7048e8" fill="#7048e8" fillOpacity={0.15} connectNulls={false} isAnimationActive={false} />
          <Tooltip labelFormatter={(t) => fmtTime(Number(t), offsetMin)} formatter={(v) => [`${v}%`, "Risk"]} />
        </AreaChart>
      )}</div>
      <p className="muted tiny">Gaps mean glucose was already above 180 mg/dL or data were insufficient. Dashed line: alert threshold.</p>
    </div>
  );
}
