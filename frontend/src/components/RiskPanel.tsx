import type { Forecast } from "../api/types";
import { num, riskPct } from "../format";

export function RiskPanel({ forecast }: { forecast: Forecast | null }) {
  if (!forecast) return <section className="card"><h3>Excursion risk</h3><p className="muted">No forecast yet.</p></section>;
  if (forecast.status !== "ok") {
    return (
      <section className="card">
        <h3>Excursion risk</h3>
        <p className="warn-text">Forecast withheld: {forecast.reason}</p>
        <p className="muted small">The twin does not guess when recent CGM data are insufficient.</p>
      </section>
    );
  }
  const ex = forecast.excursion;
  if (!ex) {
    return (
      <section className="card">
        <h3>Excursion risk</h3>
        <p className="big g-high">{num(forecast.current_glucose_mg_dl)} mg/dL</p>
        <p className="muted small">Glucose is already above 180 mg/dL, so an onset forecast does not apply.
          The trajectory forecast is still shown on the chart.</p>
      </section>
    );
  }
  const maxAbs = Math.max(...ex.top_factors.map((f) => Math.abs(f.contribution)), 0.01);
  return (
    <section className={`card risk risk-${ex.risk_band}`}>
      <h3>Excursion risk · next {ex.horizon_min} min</h3>
      <div className="risk-head">
        <div className="big">{riskPct(ex.probability)}</div>
        <div>
          <span className={`badge badge-${ex.risk_band}`}>{ex.risk_band.toUpperCase()}</span>
          {ex.alert && <div className="alert-text">Above the alert threshold ({Math.round(ex.alert_threshold * 100)}%). Consider reviewing.</div>}
        </div>
      </div>
      <p className="muted small">{ex.event_definition}</p>
      <div className="horizons" role="list" aria-label="Predicted glucose by horizon">
        {forecast.trajectory.map((p) => (
          <div key={p.horizon_min} className="hz" role="listitem" title={`Model-predicted glucose ${p.lower_mg_dl}–${p.upper_mg_dl} mg/dL in ${p.horizon_min} minutes`}>
            <span className="hz-h">+{p.horizon_min} min</span>
            <span className="hz-v">{Math.round(p.glucose_mg_dl)}<span className="unit"> mg/dL</span></span>
            <span className="muted tiny">[{Math.round(p.lower_mg_dl)}–{Math.round(p.upper_mg_dl)}]</span>
          </div>
        ))}
      </div>
      <p className="muted tiny">Predicted values with the 80% interval — <b>model-generated</b>, not observed measurements.</p>
      <h4>What drives this estimate</h4>
      <ul className="factors">
        {ex.top_factors.map((f) => (
          <li key={f.feature}>
            <span className="f-label">{f.label}{f.value !== null && <span className="muted"> ({f.value})</span>}</span>
            <span className="f-bar">
              <span className={f.contribution >= 0 ? "bar up" : "bar down"} style={{ width: `${(Math.abs(f.contribution) / maxAbs) * 100}%` }} />
            </span>
            <span className={f.contribution >= 0 ? "f-dir up" : "f-dir down"}>{f.contribution >= 0 ? "raises" : "lowers"}</span>
          </li>
        ))}
      </ul>
      <p className="muted tiny">Each bar sums the logistic-regression log-odds terms of a group of related inputs, relative to the training
        average. Grouping avoids misleading signs from correlated inputs. These are associations, not causes.</p>
    </section>
  );
}
