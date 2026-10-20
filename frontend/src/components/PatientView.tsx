import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { CounterfactualResult, Forecast, ForecastSummary, Observation, PatientRecord, ReplayStatus, TwinState } from "../api/types";
import { fmtDateTime, fmtOffset, riskPct, toMs } from "../format";
import { GlucoseChart } from "./GlucoseChart";
import { RiskPanel } from "./RiskPanel";
import { RiskTimeline } from "./RiskTimeline";
import { SensorTimeline } from "./SensorTimeline";
import { StatePanel } from "./StatePanel";

const WINDOW_HOURS = 12;
const SPEEDS = [
  { label: "5 min / tick", minutes: 5 },
  { label: "15 min / tick", minutes: 15 },
  { label: "30 min / tick", minutes: 30 },
  { label: "1 h / tick", minutes: 60 },
];

/** Scenario-vs-baseline difference at one horizon (mg/dL), rounded to 0.1. Null when either leg was withheld. */
function deltaAt(sim: CounterfactualResult, horizon: number): number | null {
  if (sim.baseline.status !== "ok" || sim.scenario.status !== "ok") return null;
  const b = sim.baseline.trajectory.find((p) => p.horizon_min === horizon);
  const s = sim.scenario.trajectory.find((p) => p.horizon_min === horizon);
  return b && s ? Math.round((s.glucose_mg_dl - b.glucose_mg_dl) * 10) / 10 : null;
}
const fmtDelta = (d: number) => (d > 0 ? "+" : "") + d.toFixed(1);

export function PatientView({ patientId, onTick, startOffsetHours = 24 }: { patientId: string; onTick: () => void; startOffsetHours?: number }) {
  const [record, setRecord] = useState<PatientRecord | null>(null);
  const [replay, setReplay] = useState<ReplayStatus | null>(null);
  const [state, setState] = useState<TwinState | null>(null);
  const [forecast, setForecast] = useState<Forecast | null>(null);
  const [cgm, setCgm] = useState<Observation[]>([]);
  const [meals, setMeals] = useState<Observation[]>([]);
  const [steps, setSteps] = useState<Observation[]>([]);
  const [heartRate, setHeartRate] = useState<Observation[]>([]);
  const [history, setHistory] = useState<ForecastSummary[]>([]);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(15);
  const [showPast, setShowPast] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [simGrams, setSimGrams] = useState(60);
  const [sims, setSims] = useState<{ grams: number; result: CounterfactualResult }[]>([]);
  const [simBusy, setSimBusy] = useState(false);
  const [simError, setSimError] = useState<string | null>(null);
  const busy = useRef(false);

  const refresh = useCallback(async (status: ReplayStatus) => {
    const since = new Date(toMs(status.clock) - (WINDOW_HOURS + 1) * 3600_000).toISOString();
    const [c, m, s, hr, h] = await Promise.all([
      api.observations(patientId, "cgm", since),
      api.observations(patientId, "meal", since),
      api.observations(patientId, "steps", since),
      api.observations(patientId, "heart_rate", since),
      api.forecasts(patientId, since),
    ]);
    setCgm(c); setMeals(m); setSteps(s); setHeartRate(hr); setHistory(h);
    setState(status.state); setForecast(status.forecast); setReplay(status);
  }, [patientId]);

  const start = useCallback(async () => {
    setPlaying(false);
    setError(null);
    setSims([]);
    setSimError(null);
    try {
      const [rec, status] = await Promise.all([api.patient(patientId), api.createReplay(patientId, startOffsetHours)]);
      setRecord(rec);
      await refresh(status);
    } catch (e) { setError(String(e)); }
  }, [patientId, refresh, startOffsetHours]);

  const runSim = useCallback(async () => {
    setSimBusy(true);
    setSimError(null);
    try {
      const result = await api.counterfactual(patientId, simGrams);
      setSims((prev) => [...prev.slice(-3), { grams: simGrams, result }]); // keep the last 4 scenarios
    } catch (e) { setSimError(String(e)); } // local to the strip: a failed simulation must not blank the workspace
    finally { setSimBusy(false); }
  }, [patientId, simGrams]);

  const clearSim = useCallback(() => { setSims([]); setSimError(null); }, []);

  useEffect(() => { void start(); }, [start]);

  const step = useCallback(async (minutes: number) => {
    if (!replay || busy.current) return;
    busy.current = true;
    try {
      const status = await api.stepReplay(replay.session_id, minutes);
      setSims([]); // a what-if is tied to the "now" it was computed at
      setSimError(null);
      await refresh(status);
      onTick();
      if (status.finished) setPlaying(false);
    } catch (e) { setError(String(e)); setPlaying(false); }
    finally { busy.current = false; }
  }, [replay, refresh, onTick]);

  useEffect(() => {
    if (!playing) return;
    const id = window.setInterval(() => void step(speed), 900);
    return () => window.clearInterval(id);
  }, [playing, speed, step]);

  if (error) return <div className="card error">Could not load the patient twin: {error} <button onClick={() => void start()}>Retry</button></div>;
  if (!record || !replay) return <div className="card muted">Loading patient twin…</div>;
  const offset = record.utc_offset_minutes;
  const clockMs = toMs(replay.clock);
  const progress = (clockMs - toMs(replay.start)) / Math.max(toMs(replay.end) - toMs(replay.start), 1);

  return (
    <div className="patient-view">
      <section className="card patient-header">
        <div>
          <h2>{record.display_name} <span className="muted small">{record.patient_id}</span></h2>
          <div className="small">
            {record.age_years} y · {record.sex} · BMI {record.bmi} · T2D for {record.diabetes_duration_years} y ·
            HbA1c <b>{record.hba1c_percent}%</b> · FPG {record.fasting_glucose_mg_dl} mg/dL · eGFR {record.egfr_ml_min_1_73m2}
          </div>
          <div className="chips">
            {record.medications.map((m) => <span key={m.name} className="chip" title={m.drug_class}>{m.name} {m.dose}</span>)}
          </div>
          <div className="muted small">{record.conditions.join(" · ")}</div>
          {(record.genetic_markers?.length || record.family_history_t2d != null) && (
            <div className="muted small" title="Synthetic, display-only: no simulated effect and not used by the model">
              Family history of T2D: {record.family_history_t2d ? "yes" : "no"}
              {record.genetic_markers?.map((g) => ` · ${g.gene} ${g.variant} ${g.genotype}`).join("")}
              {" "}(synthetic, context only; not a model input)
            </div>
          )}
        </div>
        <div className="replay">
          <div className="clock" aria-live="polite">{fmtDateTime(clockMs, offset)} <span className="muted tiny">local ({fmtOffset(offset)})</span>
            {state?.data_quality && (
              <span className={`fresh${state.data_quality.stale ? " fresh-stale" : ""}`}
                    title="Minutes since the last CGM reading reached the twin">
                CGM {state.data_quality.minutes_since_last_cgm == null ? "–" : Math.round(state.data_quality.minutes_since_last_cgm)} min ago{state.data_quality.stale ? " · STALE" : ""}
              </span>
            )}
          </div>
          <div className="progress"><span style={{ width: `${Math.min(progress, 1) * 100}%` }} /></div>
          <div className="controls">
            <button className="primary" onClick={() => setPlaying((p) => !p)} disabled={replay.finished}>{playing ? "Pause" : "Play"}</button>
            <button onClick={() => void step(5)} disabled={playing || replay.finished}>+5 min</button>
            <button onClick={() => void step(60)} disabled={playing || replay.finished}>+1 h</button>
            <select value={speed} onChange={(e) => setSpeed(Number(e.target.value))} aria-label="Replay speed">
              {SPEEDS.map((s) => <option key={s.minutes} value={s.minutes}>{s.label}</option>)}
            </select>
            <button onClick={() => void start()}>Restart</button>
          </div>
          <div className="muted tiny">Chronological replay: the twin only sees data up to "now". {replay.finished && <b>Replay finished.</b>}</div>
        </div>
      </section>

      <div className="main-row">
        <section className="card chart-card">
          <div className="card-title-row">
            <h3>Glucose: last {WINDOW_HOURS} h and 2 h forecast</h3>
            <label className="small"><input type="checkbox" checked={showPast} onChange={(e) => setShowPast(e.target.checked)} /> show earlier 60-min predictions</label>
          </div>
          <div className="whatif">
            <b className="sim-tag">SIMULATED</b>
            <label className="small">What if the patient eats <input type="number" min={1} max={300} value={simGrams}
              onChange={(e) => setSimGrams(Math.max(1, Math.min(300, Number(e.target.value))))} aria-label="Hypothetical meal carbs in grams" /> g of carbs now?</label>
            <button className="primary" onClick={() => void runSim()} disabled={simBusy || sims.length >= 4}
                    title={sims.length >= 4 ? "Comparison is limited to 4 scenarios — clear them to explore further" : "Runs on an isolated copy of the twin; the record is never changed"}>
              {simBusy ? "Simulating…" : sims.length ? "Add scenario" : "Simulate meal"}</button>
            {sims.length > 0 && <button onClick={clearSim}>Clear scenarios</button>}
            {simError && <span className="sim-error small" role="alert">Simulation failed: {simError}</span>}
            {sims.length > 0 && (
              <table className="sim-table small" aria-label="Hypothetical meal scenarios compared with the current baseline forecast">
                <thead>
                  <tr><th scope="col">Meal</th><th scope="col">Δ +30 min</th><th scope="col">Δ +60 min</th><th scope="col">Δ +120 min</th><th scope="col">Excursion risk</th></tr>
                </thead>
                <tbody>
                  {sims.map(({ grams, result }) => {
                    const d30 = deltaAt(result, 30), d60 = deltaAt(result, 60), d120 = deltaAt(result, 120);
                    return (
                      <tr key={`${result.as_of}-${grams}`}>
                        <td>{grams} g</td>
                        <td>{d30 == null ? "—" : fmtDelta(d30)}</td>
                        <td>{d60 == null ? "—" : fmtDelta(d60)}</td>
                        <td>{d120 == null ? "—" : fmtDelta(d120)}</td>
                        <td>{result.baseline.excursion && result.scenario.excursion
                          ? `${riskPct(result.baseline.excursion.probability)} → ${riskPct(result.scenario.excursion.probability)}` : "n/a"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
            {sims.length > 0 && (() => {
              const last = sims[sims.length - 1].result;
              if (last.baseline.status !== "ok" || last.scenario.status !== "ok") {
                return <span className="muted small" style={{ flexBasis: "100%" }}>Latest scenario withheld — not enough recent CGM data for a reliable what-if at this moment.</span>;
              }
              const d60 = deltaAt(last, 60);
              if (d60 != null && d60 < 0) {
                return (
                  <span className="muted tiny" style={{ flexBasis: "100%" }}>
                    Negative Δ at this small meal: a known simulator artifact when the hypothetical meal lands inside another logged
                    meal's learned-response window. Treat small-carb scenarios qualitatively (backlog B-22).
                  </span>
                );
              }
              if (d60 != null && Math.abs(d60) < 2) {
                return (
                  <span className="muted tiny" style={{ flexBasis: "100%" }}>
                    ≈ no scenario change{(state?.carbs_on_board_g ?? 0) >= 5
                      ? ` — the model already carries ~${Math.round(state?.carbs_on_board_g ?? 0)} g of carbs on board from logged meals, so an additional hypothetical meal adds little.`
                      : " — at this moment the simulated meal barely moves the +60-min forecast."}
                  </span>
                );
              }
              return null;
            })()}
            <div className="muted tiny" style={{ flexBasis: "100%" }}>Each scenario is computed independently on a copy of the observation history — the hypothetical
              meal is never added to the patient record, and scenarios do not affect each other or the replay. A simulated comparison for exploration, from a
              synthetic research simulator — not medical advice, not a treatment recommendation. The chart overlays the latest scenario.</div>
          </div>
          <GlucoseChart cgm={cgm} meals={meals} forecast={forecast} scenario={sims.length ? sims[sims.length - 1].result.scenario : null}
                        history={history} clockMs={clockMs} offsetMin={offset} windowHours={WINDOW_HOURS} showPastPredictions={showPast} />
        </section>
        <RiskPanel forecast={forecast} state={state} history={history} offset={offset} />
      </div>
      <SensorTimeline clockMs={clockMs} offsetMin={offset} windowHours={WINDOW_HOURS}
                      cgm={cgm} meals={meals} steps={steps} heartRate={heartRate} forecasts={history} />
      <RiskTimeline history={history} threshold={forecast?.excursion?.alert_threshold ?? null} clockMs={clockMs}
                    offsetMin={offset} windowHours={WINDOW_HOURS} />
      <StatePanel state={state} />
    </div>
  );
}
