import type { TwinState } from "../api/types";
import { ARROWS, ARROW_TEXT, glucoseClass, num, pct, personalRuleText, personalUncertaintyText } from "../format";

export function StatePanel({ state }: { state: TwinState | null }) {
  if (!state) return null;
  const s = state.summary_24h;
  const dq = state.data_quality;
  const p = state.personal;
  return (
    <section className="state-grid">
      <div className="card stat">
        <div className="stat-label">Current glucose</div>
        <div className={`stat-value ${glucoseClass(state.last_glucose_mg_dl)}`}>
          {num(state.last_glucose_mg_dl)} <span className="unit">mg/dL</span>{" "}
          <span title={ARROW_TEXT[state.trend_arrow]} aria-label={ARROW_TEXT[state.trend_arrow]}>{ARROWS[state.trend_arrow]}</span>
        </div>
        <div className="muted small">{ARROW_TEXT[state.trend_arrow]}</div>
      </div>
      <div className="card stat">
        <div className="stat-label">Last 24 h ({s.n_readings} readings)</div>
        <div className="tir">
          <span className="tir-seg low" style={{ flex: s.time_below_range_pct ?? 0 }} />
          <span className="tir-seg ok" style={{ flex: s.time_in_range_pct ?? 0 }} />
          <span className="tir-seg high" style={{ flex: s.time_above_range_pct ?? 0 }} />
        </div>
        <div className="small">In range <b>{num(s.time_in_range_pct, 0, "%")}</b> · above <b>{num(s.time_above_range_pct, 0, "%")}</b> · below <b>{num(s.time_below_range_pct, 0, "%")}</b></div>
        <div className="muted small">Mean {num(s.mean_mg_dl)} mg/dL · CV {num(s.cv_percent, 0, "%")}</div>
      </div>
      <div className="card stat">
        <div className="stat-label">Meals and activity</div>
        <div className="small">Carbs on board <b>{num(state.carbs_on_board_g)} g</b></div>
        <div className="small">Last logged meal {state.minutes_since_last_meal === null ? "–" : <b>{Math.round(state.minutes_since_last_meal)} min ago</b>}</div>
        <div className="small">Steps, last hour <b>{num(state.steps_last_60min)}</b></div>
        <div className="small">Heart rate, 30 min <b>{num(state.mean_heart_rate_30min)} bpm</b></div>
      </div>
      <div className="card stat">
        <div className="stat-label">Personalised parameter</div>
        <div className="small">Carb sensitivity <b>{p.carb_sensitivity_mg_dl_per_g.toFixed(2)}</b> mg/dL per g</div>
        <div className="muted small">Started from record-based prior {p.carb_sensitivity_prior.toFixed(2)}; learned from {p.meals_used} observed meals.</div>
        {personalUncertaintyText(p) && (
          <div className="small personal-confidence" title="Sampling standard error from meal-to-meal variation, prior treated as fixed. Not a posterior SD; descriptive only, not used by any forecast.">
            {personalUncertaintyText(p)}
          </div>
        )}
        <details className="personal-rule small">
          <summary>How this parameter updates</summary>
          <div className="tiny">
            <div>{personalRuleText(p)}</div>
            <div className="muted">Prior from the record: <code>1.40 + 0.10 × (HbA1c − 7)</code>, clipped to 0.4–3.0 (a heuristic assumption).
              Each counted meal contributes its observed rise per gram: peak CGM in the 120 min after the meal minus the last reading before it,
              divided by the grams. Counted only for meals ≥ 10 g with no other meal within 120 min and ≥ 50% CGM coverage, and only once the
              120 min have passed, so a forecast never uses later data.</div>
            <div className="muted">The models use it through two inputs: carb sensitivity and expected meal rise (sensitivity × carbs on board).
              Updating a patient-specific parameter is not, on its own, evidence of better forecasts.</div>
          </div>
        </details>
      </div>
      <div className={`card stat ${dq.stale ? "dq-bad" : ""}`}>
        <div className="stat-label">Data quality</div>
        <div className="small">CGM completeness (3 h) <b>{pct(dq.cgm_completeness_3h)}</b></div>
        <div className="small">Last CGM {dq.minutes_since_last_cgm === null ? "–" : `${Math.round(dq.minutes_since_last_cgm)} min ago`}{dq.stale && <b className="warn-text"> · STALE</b>}</div>
        <div className="small">Gaps over 30 min (24 h) <b>{dq.gaps_over_30min_24h}</b></div>
        <div className="muted tiny">Twin state v{state.version} · {state.observations_ingested} observations</div>
      </div>
    </section>
  );
}
