import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { CounterfactualResult, Forecast, ForecastSummary, Observation, PatientRecord, ReplayStatus, TwinState } from "../api/types";
import { fmtDateTime, fmtOffset, toMs } from "../format";
import { GlucoseChart } from "./GlucoseChart";
import { RiskPanel } from "./RiskPanel";
import { RiskTimeline } from "./RiskTimeline";
import { StatePanel } from "./StatePanel";

const WINDOW_HOURS = 12;
const SPEEDS = [
  { label: "5 min / tick", minutes: 5 },
  { label: "15 min / tick", minutes: 15 },
  { label: "30 min / tick", minutes: 30 },
  { label: "1 h / tick", minutes: 60 },
];

export function PatientView({ patientId, onTick, startOffsetHours = 24 }: { patientId: string; onTick: () => void; startOffsetHours?: number }) {
  const [record, setRecord] = useState<PatientRecord | null>(null);
  const [replay, setReplay] = useState<ReplayStatus | null>(null);
  const [state, setState] = useState<TwinState | null>(null);
  const [forecast, setForecast] = useState<Forecast | null>(null);
  const [cgm, setCgm] = useState<Observation[]>([]);
  const [meals, setMeals] = useState<Observation[]>([]);
  const [history, setHistory] = useState<ForecastSummary[]>([]);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(15);
  const [showPast, setShowPast] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [simGrams, setSimGrams] = useState(60);
  const [sim, setSim] = useState<CounterfactualResult | null>(null);
  const [simBusy, setSimBusy] = useState(false);
  const busy = useRef(false);

  const refresh = useCallback(async (status: ReplayStatus) => {
    const since = new Date(toMs(status.clock) - (WINDOW_HOURS + 1) * 3600_000).toISOString();
    const [c, m, h] = await Promise.all([
      api.observations(patientId, "cgm", since),
      api.observations(patientId, "meal", since),
      api.forecasts(patientId, since),
    ]);
    setCgm(c); setMeals(m); setHistory(h);
    setState(status.state); setForecast(status.forecast); setReplay(status);
  }, [patientId]);

  const start = useCallback(async () => {
    setPlaying(false);
    setError(null);
    setSim(null);
    try {
      const [rec, status] = await Promise.all([api.patient(patientId), api.createReplay(patientId, startOffsetHours)]);
      setRecord(rec);
      await refresh(status);
    } catch (e) { setError(String(e)); }
  }, [patientId, refresh, startOffsetHours]);

  const runSim = useCallback(async () => {
    setSimBusy(true);
    try {
      setSim(await api.counterfactual(patientId, simGrams));
    } catch (e) { setError(String(e)); }
    finally { setSimBusy(false); }
  }, [patientId, simGrams]);

  useEffect(() => { void start(); }, [start]);

  const step = useCallback(async (minutes: number) => {
    if (!replay || busy.current) return;
    busy.current = true;
    try {
      const status = await api.stepReplay(replay.session_id, minutes);
      setSim(null); // a what-if is tied to the "now" it was computed at
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
          <div className="clock" aria-live="polite">{fmtDateTime(clockMs, offset)} <span className="muted tiny">local ({fmtOffset(offset)})</span></div>
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
            <button onClick={() => void runSim()} disabled={simBusy}>{simBusy ? "Simulating…" : "Simulate meal"}</button>
            {sim && sim.baseline.status === "ok" && sim.scenario.status === "ok" && (
              <span className="small">
                Scenario at {fmtDateTime(toMs(sim.as_of), offset)}: <b>{sim.delta_glucose_60mg_dl! > 0 ? "+" : ""}{sim.delta_glucose_60mg_dl} mg/dL</b> at +60 min
                {sim.delta_probability != null && sim.baseline.excursion && sim.scenario.excursion && (
                  <> · excursion risk {(100 * sim.baseline.excursion.probability).toFixed(0)}% → <b>{(100 * sim.scenario.excursion.probability).toFixed(0)}%</b></>
                )}
              </span>
            )}
            <div className="muted tiny" style={{ flexBasis: "100%" }}>The hypothetical meal is never added to the patient record. A simulated scenario for exploration — not medical advice.</div>
          </div>
          <GlucoseChart cgm={cgm} meals={meals} forecast={forecast} scenario={sim?.scenario ?? null} history={history} clockMs={clockMs}
                        offsetMin={offset} windowHours={WINDOW_HOURS} showPastPredictions={showPast} />
        </section>
        <RiskPanel forecast={forecast} />
      </div>
      <RiskTimeline history={history} threshold={forecast?.excursion?.alert_threshold ?? null} clockMs={clockMs}
                    offsetMin={offset} windowHours={WINDOW_HOURS} />
      <StatePanel state={state} />
    </div>
  );
}
