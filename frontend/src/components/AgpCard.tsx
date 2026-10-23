import { useEffect, useState } from "react";

import { api, IS_STATIC_DEMO } from "../api/client";
import type { AgpSummary } from "../api/types";
import { fmtDateTime, toMs } from "../format";

const W = 480, H = 150, PAD = { l: 34, r: 8, t: 8, b: 20 };
const YMIN = 40, YMAX = 300;
const x = (h: number) => PAD.l + ((h + 0.5) / 24) * (W - PAD.l - PAD.r);
const y = (g: number) => PAD.t + (1 - (Math.min(Math.max(g, YMIN), YMAX) - YMIN) / (YMAX - YMIN)) * (H - PAD.t - PAD.b);

function band(a: AgpSummary, lo: "p5" | "p25", hi: "p75" | "p95") {
  const top = a.hourly.map((p) => `${x(p.hour)},${y(p[hi])}`);
  const bottom = [...a.hourly].reverse().map((p) => `${x(p.hour)},${y(p[lo])}`);
  return [...top, ...bottom].join(" ");
}

/** Ambulatory glucose profile of the CGM this twin has received (descriptive; synthetic data). */
export function AgpCard({ patientId, offset, onLoad }: { patientId: string; offset: number; onLoad?: (a: AgpSummary | null) => void }) {
  const [agp, setAgp] = useState<AgpSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    setAgp(null); setError(null);
    api.agp(patientId).then((a) => { if (live) { setAgp(a); onLoad?.(a); } })
      .catch((e) => { if (live) { setError(String(e?.message ?? e)); onLoad?.(null); } });
    return () => { live = false; };
  }, [patientId, onLoad]);

  const v = (n: number | null, suffix = "%") => (n == null ? "–" : `${n}${suffix}`);
  return (
    <section className="card agp-card" aria-label="Ambulatory glucose profile">
      <div className="card-title-row">
        <h3>Glucose profile (AGP, up to 14 days)</h3>
        {agp && <span className="muted tiny">as of {fmtDateTime(toMs(agp.as_of), offset)}{IS_STATIC_DEMO && " · recorded at the replay start"}</span>}
      </div>
      {error && <p className="sim-error small" role="alert">Glucose profile unavailable: {error}</p>}
      {!agp && !error && <p className="muted small">Loading…</p>}
      {agp && agp.n_readings === 0 && <p className="muted small">No CGM received yet.</p>}
      {agp && agp.n_readings > 0 && (
        <div className="agp-body">
          <div className="agp-stats small">
            <div><span className="stat-label">Time in range 70–180</span><b className="g-ok">{v(agp.tir_70_180_pct)}</b></div>
            <div><span className="stat-label">Above 180 / 250</span><b className="g-high">{v(agp.tar_181_250_pct)}</b> / {v(agp.tar_over_250_pct)}</div>
            <div><span className="stat-label">Below 70 / 54</span><b className="g-low">{v(agp.tbr_54_69_pct)}</b> / {v(agp.tbr_under_54_pct)}</div>
            <div><span className="stat-label">Mean · CV</span>{v(agp.mean_mg_dl, " mg/dL")} · {v(agp.cv_pct)}</div>
            <div title="Glucose management indicator = 3.31 + 0.02392 × mean glucose (mg/dL); an estimate, not a laboratory HbA1c">
              <span className="stat-label">GMI (estimate)</span>{v(agp.gmi_pct)}</div>
            <div><span className="stat-label">Data</span>{agp.days_with_data} d · {agp.coverage_pct}% coverage</div>
          </div>
          <svg className="agp-chart" viewBox={`0 0 ${W} ${H}`} role="img"
               aria-label="Hourly glucose percentiles by local hour: 5 to 95 percent band, 25 to 75 percent band and median">
            <rect x={PAD.l} y={y(180)} width={W - PAD.l - PAD.r} height={y(70) - y(180)} className="agp-range" />
            {[70, 180, 250].map((g) => (
              <g key={g}><line x1={PAD.l} x2={W - PAD.r} y1={y(g)} y2={y(g)} className="agp-grid" />
                <text x={PAD.l - 4} y={y(g) + 3} textAnchor="end" className="agp-tick">{g}</text></g>
            ))}
            {[0, 6, 12, 18, 23].map((h) => <text key={h} x={x(h)} y={H - 6} textAnchor="middle" className="agp-tick">{String(h).padStart(2, "0")}:00</text>)}
            <polygon points={band(agp, "p5", "p95")} className="agp-outer" />
            <polygon points={band(agp, "p25", "p75")} className="agp-inner" />
            <polyline points={agp.hourly.map((p) => `${x(p.hour)},${y(p.p50)}`).join(" ")} className="agp-median" />
          </svg>
          <p className="muted tiny">
            Bands: 5–95th and 25–75th percentiles, line: median, by hour of the local day. Metrics follow the 2019 international
            consensus on CGM reporting; {agp.sufficient
              ? "this window meets its 14-day / 70% data minimum."
              : <b>this window is below its 14-day / 70% data minimum, so read it as indicative only.</b>} Synthetic CGM; descriptive,
            not used by any forecast, not a diagnosis.
          </p>
        </div>
      )}
    </section>
  );
}
