import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { EvaluationReport } from "../api/types";
import { num, pct } from "../format";

export function EvaluationView() {
  const [rep, setRep] = useState<EvaluationReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api.evaluation().then(setRep).catch((e) => setError(String(e))); }, []);
  if (error) return <div className="card error">Evaluation report unavailable: {error}</div>;
  if (!rep) return <div className="card muted">Loading evaluation…</div>;
  const served = rep.served_models;
  return (
    <div className="eval">
      <section className="card">
        <h2>Model evaluation <span className="muted small">{rep.model_version}</span></h2>
        <p className="warn-text small"><b>Synthetic data only.</b> These numbers describe the simulator, not real-world performance.</p>
        <p className="small"><b>Target:</b> {rep.target_definition}</p>
        <p className="small"><b>Protocol:</b> {rep.split_protocol}</p>
        <p className="small"><b>Dataset:</b> {rep.dataset.name} v{rep.dataset.version}, seed {rep.dataset.seed}, {rep.dataset.n_patients} patients ×
          {" "}{rep.dataset.days_per_patient} days. Patients per split: {Object.entries(rep.dataset.split_patients).map(([k, v]) => `${k} ${v}`).join(", ")}.</p>
        <p className="small"><b>Served:</b> trajectory = {served.trajectory} ({served.trajectory_selection}); event = {served.event} ({served.event_selection}).</p>
      </section>
      <section className="card">
        <h3>Excursion onset within 2 h (held-out test patients)</h3>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Model</th><th>AUROC</th><th>AUPRC</th><th>Brier</th><th>Threshold</th><th>Sensitivity</th><th>Specificity</th><th>PPV</th><th>Excursions warned</th><th>Median lead</th><th>False alert episodes / day</th></tr></thead>
            <tbody>
              {rep.event.map((e) => (
                <tr key={e.model} className={e.model === served.event ? "served" : ""}>
                  <td>{e.model}{e.model === served.event && <span className="badge badge-low">served</span>}</td>
                  <td>{num(e.auroc, 3)}</td><td>{num(e.auprc, 3)}</td><td>{num(e.brier, 3)}</td><td>{num(e.threshold, 2)}</td>
                  <td>{pct(e.sensitivity)}</td><td>{pct(e.specificity)}</td><td>{pct(e.ppv)}</td><td>{pct(e.event_sensitivity)}</td>
                  <td>{num(e.median_lead_time_min, 0, " min")}</td><td>{num(e.false_alert_episodes_per_patient_day, 2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="muted tiny">Prevalence {pct(rep.event[0]?.prevalence, 1)} of {rep.event[0]?.n} eligible test points. Lead time is capped at 120 min by definition.</p>
      </section>
      <section className="card">
        <h3>Glucose trajectory (held-out test patients)</h3>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Model</th><th>Horizon</th><th>MAE</th><th>RMSE</th><th>MARD</th><th>Clarke A</th><th>Clarke A+B</th><th>80% interval coverage</th></tr></thead>
            <tbody>
              {rep.trajectory.map((t) => (
                <tr key={`${t.model}-${t.horizon_min}`} className={t.model === served.trajectory ? "served" : ""}>
                  <td>{t.model}</td><td>{t.horizon_min} min</td><td>{num(t.mae_mg_dl, 1)}</td><td>{num(t.rmse_mg_dl, 1)}</td>
                  <td>{num(t.mard_percent, 1, "%")}</td><td>{num(t.clarke_a_pct, 1, "%")}</td><td>{num(t.clarke_ab_pct, 1, "%")}</td>
                  <td>{t.interval_coverage === null ? "–" : pct(t.interval_coverage)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <section className="card">
        <h3>Notes</h3>
        <ul className="small">{rep.notes.map((n) => <li key={n}>{n}</li>)}</ul>
      </section>
    </div>
  );
}
