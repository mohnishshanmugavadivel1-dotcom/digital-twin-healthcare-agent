import type { Forecast, ForecastSummary, Medication, TwinState } from "../api/types";
import { fmtDateTime, hypoglycaemiaMedications, lowerBoundBelow, num, riskPct, toMs } from "../format";

/**
 * Excursion-risk card plus the evidence behind the current forecast: data
 * quality, earlier predictions made during this replay, and explicit labels
 * separating observed values, model predictions and simulated scenarios.
 * Everything shown comes from engine outputs (forecast, twin state, forecast
 * history) — no derived or invented values.
 */

interface Props {
  forecast: Forecast | null;
  state: TwinState | null;
  history: ForecastSummary[];
  offset: number; // patient-local UTC offset in minutes (record.utc_offset_minutes)
  medications?: Medication[]; // record medications, display context for the low-glucose lower-bound note only
}

/** Lower-bound note: states exactly what is computed. Not a probability; rule audited in twin_validity.json (D). */
function LowerBoundNote({ forecast, medications }: { forecast: Forecast; medications: Medication[] }) {
  const low = lowerBoundBelow(forecast.trajectory);
  if (!low) return null;
  const meds = hypoglycaemiaMedications(medications);
  const level = Math.round((forecast.interval_level ?? 0.8) * 100);
  return (
    <div className="lowbound small" role="note">
      <b>Low-glucose watch:</b> the {level}% forecast lower bound falls below 70 mg/dL from +{low.horizon_min} min
      (lowest {Math.round(low.lowest_mg_dl)} mg/dL).{meds.length > 0 && <> Record medication that can cause hypoglycaemia: {meds.join(", ")}.</>}
      <div className="muted tiny">This is the lower edge of the prediction interval, <b>not a probability of hypoglycaemia</b> and not a
        validated hypoglycaemia predictor. On synthetic held-out patients a reading below 70 mg/dL followed within 2 h at
        3,178 of 9,495 moments when it showed (test) and 208 of 2,186 (validation); the simulator under-represents lows.</div>
    </div>
  );
}

function Evidence({ state, history, offset }: { state: TwinState | null; history: ForecastSummary[]; offset: number }) {
  if (!state) return null;
  const dq = state.data_quality;
  return (
    <div className="evidence">
      <h4>Evidence &amp; data quality behind this card</h4>
      <ul className="ev-list small">
        <li>
          CGM freshness: <b>{dq.minutes_since_last_cgm == null ? "unknown" : `${Math.round(dq.minutes_since_last_cgm)} min ago`}</b>
          {dq.stale && <b className="warn-text"> · STALE (sensor silent too long)</b>}
          {" · "}3-h completeness <b>{Math.round(dq.cgm_completeness_3h * 100)}%</b>
          {" · "}gaps &gt; 30 min (24 h): <b>{dq.gaps_over_30min_24h}</b>
        </li>
        <li>Twin has ingested <b>{state.observations_ingested}</b> observations up to {fmtDateTime(toMs(state.as_of), offset)}.</li>
        {history.length > 0 && (
          <li>
            Earlier predictions this replay:
            <span className="ev-past">
              {history.slice(-2).map((f) => (
                <span key={f.issued_at} className="ev-past-item" title={`Issued ${f.issued_at} · status ${f.status}`}>
                  {fmtDateTime(toMs(f.issued_at), offset)}: {f.status === "ok" && f.predicted?.["60"] != null
                    ? `+60 min → ${Math.round(f.predicted["60"])} mg/dL${f.probability != null ? `, risk ${riskPct(f.probability)}` : ""}`
                    : f.status}
                </span>
              ))}
            </span>
            — what actually happened is visible on the chart.
          </li>
        )}
      </ul>
      <p className="muted tiny">
        <b>How to read the labels:</b> <b>observed</b> = values measured by the (simulated) sensors; <b>predicted</b> = model output with
        model-generated uncertainty; <b>simulated</b> = the what-if scenarios below the chart. Factor bars are model attributions —
        associations the model uses, <b>not</b> established biological causation.
      </p>
    </div>
  );
}

export function RiskPanel({ forecast, state, history, offset, medications = [] }: Props) {
  if (!forecast) return <section className="card"><h3>Excursion risk</h3><p className="muted">No forecast yet.</p>{state && <Evidence state={state} history={history} offset={offset} />}</section>;
  if (forecast.status !== "ok") {
    return (
      <section className="card">
        <h3>Excursion risk</h3>
        <p className="warn-text">Forecast withheld: {forecast.reason}</p>
        <p className="muted small">The twin does not guess when recent CGM data are insufficient.</p>
        <Evidence state={state} history={history} offset={offset} />
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
        <Evidence state={state} history={history} offset={offset} />
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
      <p className="muted tiny">Predicted values with the {Math.round((forecast.interval_level ?? 0.8) * 100)}% interval — <b>model-generated</b>, not observed measurements.</p>
      <LowerBoundNote forecast={forecast} medications={medications} />
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
      <Evidence state={state} history={history} offset={offset} />
      <p className="muted tiny">Model <code>{forecast.model_version}</code> · research prototype on synthetic patients — not a medical device.</p>
    </section>
  );
}
