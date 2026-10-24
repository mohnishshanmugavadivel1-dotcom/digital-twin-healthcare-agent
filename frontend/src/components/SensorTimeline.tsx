import type { ForecastSummary, Observation } from "../api/types";
import { toMs } from "../format";

/**
 * Unified, time-aligned view of every observation stream the system actually
 * has (CGM, meals, steps, heart rate — there is no sleep stream in this
 * system) plus the moments forecasts were issued. Everything plotted here is
 * real engine output: observations come from the replay window fetch and the
 * forecast ticks come from the forecast history. Nothing is fabricated; when
 * a stream has no points in the window the lane says so.
 */

interface Props {
  clockMs: number;
  offsetMin: number;
  windowHours: number;
  cgm: Observation[];
  meals: Observation[];
  steps: Observation[];
  heartRate: Observation[];
  forecasts: ForecastSummary[];
}

const hhmm = (ms: number, offsetMin: number) =>
  new Date(ms + offsetMin * 60_000).toISOString().slice(11, 16);

function Lane({ label, aria, children }: { label: string; aria: string; children: React.ReactNode }) {
  return (
    <div className="sensor-lane">
      <span className="lane-label">{label}</span>
      <div className="lane-track" role="img" aria-label={aria}>{children}</div>
    </div>
  );
}

export function SensorTimeline({ clockMs, offsetMin, windowHours, cgm, meals, steps, heartRate, forecasts }: Props) {
  const winStart = clockMs - windowHours * 3_600_000;
  const winMs = windowHours * 3_600_000;
  const x = (iso: string) => ((toMs(iso) - winStart) / winMs) * 100;
  const clamp = (v: number) => Math.max(0, Math.min(100, v));

  // CGM gaps: consecutive readings inside the window more than 30 min apart.
  const inWindow = (o: Observation) => { const t = toMs(o.timestamp); return t >= winStart && t <= clockMs; };
  const cgmT = cgm.filter(inWindow).map((o) => toMs(o.timestamp)).sort((a, b) => a - b);
  const gaps: { from: number; to: number; minutes: number }[] = [];
  for (let i = 1; i < cgmT.length; i++) {
    const minutes = (cgmT[i] - cgmT[i - 1]) / 60_000;
    if (minutes > 30) gaps.push({ from: cgmT[i - 1], to: cgmT[i], minutes: Math.round(minutes) });
  }
  const maxSteps = Math.max(1, ...steps.filter(inWindow).map((o) => o.value));
  const hourMarks: number[] = [];
  for (let t = Math.ceil(winStart / 3_600_000) * 3_600_000; t <= clockMs; t += 3_600_000) hourMarks.push(t);

  return (
    <section className="card sensor-timeline">
      <div className="card-title-row">
        <h3>All streams · last {windowHours} h, aligned with the chart</h3>
        <span className="muted tiny">provenance: simulator-generated observations · synthetic wearable data</span>
      </div>
      <Lane label="CGM" aria={`Continuous glucose readings in the last ${windowHours} hours with sensor gaps highlighted`}>
        {gaps.map((g) => (
          <span key={`gap${g.from}`} className="st-gap" style={{ left: `${clamp(((g.from - winStart) / winMs) * 100)}%`,
            width: `${clamp(((g.to - winStart) / winMs) * 100) - clamp(((g.from - winStart) / winMs) * 100)}%` }}
            title={`Sensor gap: no CGM reading for ${g.minutes} min`} />
        ))}
        {cgm.filter(inWindow).map((o) => (
          <span key={o.timestamp} className="st-dot" style={{ left: `${clamp(x(o.timestamp))}%` }}
            title={`${hhmm(toMs(o.timestamp), offsetMin)} · ${o.value} mg/dL`} />
        ))}
        {cgmT.length === 0 && <span className="lane-empty tiny">no CGM readings in this window</span>}
      </Lane>
      <Lane label="Meals" aria="Logged meals, marker size proportional to carbohydrates">
        {meals.filter(inWindow).map((o) => (
          <span key={o.timestamp} className={`st-meal${o.value >= 80 ? " big" : ""}`} style={{ left: `${clamp(x(o.timestamp))}%` }}
            title={`${hhmm(toMs(o.timestamp), offsetMin)} · ${o.value} g carbs logged`} />
        ))}
        {meals.filter(inWindow).length === 0 && <span className="lane-empty tiny">no logged meals in this window</span>}
      </Lane>
      <Lane label="Steps" aria={`Step counts per five-minute interval, tallest bar = ${maxSteps} steps`}>
        {steps.filter(inWindow).map((o) => (
          <span key={o.timestamp} className="st-step" style={{ left: `${clamp(x(o.timestamp))}%`, height: `${Math.max(8, (o.value / maxSteps) * 100)}%` }}
            title={`${hhmm(toMs(o.timestamp), offsetMin)} · ${o.value} steps`} />
        ))}
        {steps.filter(inWindow).length === 0 && <span className="lane-empty tiny">no step observations in this window</span>}
      </Lane>
      <Lane label="Heart rate" aria="Heart-rate observations in beats per minute">
        {heartRate.filter(inWindow).map((o) => (
          <span key={o.timestamp} className="st-hr" style={{ left: `${clamp(x(o.timestamp))}%` }}
            title={`${hhmm(toMs(o.timestamp), offsetMin)} · ${o.value} bpm`} />
        ))}
        {heartRate.filter(inWindow).length === 0 && <span className="lane-empty tiny">no heart-rate observations in this window</span>}
      </Lane>
      <Lane label="Forecasts" aria="Moments a forecast was issued, coloured by status">
        {forecasts.map((f) => (
          <span key={f.issued_at} className={`st-fc${f.status === "ok" ? "" : " withheld"}`} style={{ left: `${clamp(x(f.issued_at))}%` }}
            title={`Forecast at ${hhmm(toMs(f.issued_at), offsetMin)} · ${f.status}${f.probability != null ? ` · risk ${(100 * f.probability).toFixed(0)}%` : ""}`} />
        ))}
        {forecasts.length === 0 && <span className="lane-empty tiny">no forecasts issued yet</span>}
      </Lane>
      <div className="lane-axis" aria-hidden="true">
        {hourMarks.map((t) => <span key={t} style={{ left: `${((t - winStart) / winMs) * 100}%` }}>{hhmm(t, offsetMin)}</span>)}
        <span className="st-now" style={{ right: 0 }} title={`Replay now: ${hhmm(clockMs, offsetMin)}`} />
      </div>
      <p className="muted tiny">
        Gaps (red bars) are periods where the CGM sensor reported nothing — the twin still refuses to over-claim inside them.
        All streams are outputs of the synthetic simulator; <b>there is no sleep stream in this system</b>, so none is shown.
      </p>
    </section>
  );
}
