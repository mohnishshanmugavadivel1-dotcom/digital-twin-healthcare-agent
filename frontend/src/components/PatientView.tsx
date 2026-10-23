import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import type { AgpSummary, CounterfactualResult, Forecast, ForecastSummary, Observation, PatientRecord, ReplayStatus, TwinState } from "../api/types";
import { comparisonCells, fmtDateTime, fmtDelta, fmtOffset, hypoglycaemiaMedications, jointSupportChip, scenarioLowWatchCell, toMs } from "../format";
import type { HandoverInput } from "../handover";
import { GI_LABEL, MEAL_PRESETS, PRESET_NOTE, REGIONS, presetById, presetTitle, scenarioLabel } from "../mealPresets";
import { AgpCard } from "./AgpCard";
import { FhirViewer } from "./FhirViewer";
import { GlucoseChart } from "./GlucoseChart";
import { HandoverCard } from "./HandoverCard";
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

const errText = (e: unknown) => (e instanceof Error ? e.message : String(e));

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
  const [presetId, setPresetId] = useState<string | null>(null);
  const [sims, setSims] = useState<{ grams: number; label: string | null; result: CounterfactualResult }[]>([]);
  const [simBusy, setSimBusy] = useState(false);
  const [simError, setSimError] = useState<string | null>(null);
  const [showWalk, setShowWalk] = useState(false);
  const [agp, setAgp] = useState<AgpSummary | null>(null);
  const busy = useRef(false);
  const handover: HandoverInput | null = useMemo(
    () => (record && state ? { record, state, forecast, agp } : null), [record, state, forecast, agp]);

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
    } catch (e) { setError(errText(e)); }
  }, [patientId, refresh, startOffsetHours]);

  const runSim = useCallback(async () => {
    setSimBusy(true);
    setSimError(null);
    try {
      const result = await api.counterfactual(patientId, simGrams);
      const label = scenarioLabel(simGrams, presetId);
      setSims((prev) => [...prev.slice(-3), { grams: simGrams, label, result }]); // keep the last 4 scenarios
    } catch (e) { setSimError(errText(e)); } // local to the strip: a failed simulation must not blank the workspace
    finally { setSimBusy(false); }
  }, [patientId, simGrams, presetId]);

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
    } catch (e) { setError(errText(e)); setPlaying(false); }
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
  const hypoMeds = hypoglycaemiaMedications(record.medications);
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
          <FhirViewer key={patientId} patientId={patientId} handover={handover} />
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
            <select className="small" value={presetId ?? ""} aria-label="Indian meal preset (approximate carbs, editable)" title={PRESET_NOTE}
                    onChange={(e) => { const p = presetById(e.target.value); setPresetId(p ? p.id : null); if (p) setSimGrams(p.carbs); }}>
              <option value="">Indian meal preset (approx.)…</option>
              {REGIONS.map((r) => (
                <optgroup key={r} label={r}>
                  {MEAL_PRESETS.filter((p) => p.region === r).map((p) => (
                    <option key={p.id} value={p.id} title={presetTitle(p)}>
                      {p.label}: {p.serving} ≈ {p.carbs} g · {GI_LABEL[p.gi]}{p.basis === "team_estimate" ? " · team est." : ""}</option>
                  ))}
                </optgroup>
              ))}
            </select>
            {presetId && (() => {
              const p = presetById(presetId);
              return p ? <span className={`gi-badge gi-${p.gi.replace(" ", "-")}`} title={presetTitle(p)}>{GI_LABEL[p.gi]}
                {p.basis === "team_estimate" && <span className="tiny"> · team estimate</span>}</span> : null;
            })()}
            <label className="small walk-toggle" title="Research estimate: adds a cohort-level walk effect (20 min, 2,500 steps, starting 15 min after the meal) to the personalised twin curve. The served forecast models have no causal walk input.">
              <input type="checkbox" checked={showWalk} onChange={(e) => setShowWalk(e.target.checked)} /> compare with a post-meal walk (+20 min, 2,500 steps)</label>
            <button className="primary" onClick={() => void runSim()} disabled={simBusy || sims.length >= 4}
                    title={sims.length >= 4 ? "Comparison is limited to 4 scenarios — clear them to explore further" : "Runs on an isolated copy of the twin; the record is never changed"}>
              {simBusy ? "Simulating…" : sims.length ? "Add scenario" : "Simulate meal"}</button>
            {sims.length > 0 && <button onClick={clearSim}>Clear scenarios</button>}
            {simError && <span className="sim-error small" role="alert">Simulation failed: {simError}</span>}
            {sims.length > 0 && (<>
              <p className="swipe-cue tiny muted" aria-hidden="true">← Swipe the table for more columns (no-meal comparison, low watch) →</p>
              <div className="table-wrap sim-wrap">
                <table className="sim-table small" aria-label="Hypothetical meal scenarios: carb effect versus a zero-carb meal at the same time, and versus no meal">
                  <thead>
                    <tr>
                      <th scope="col" rowSpan={2}>Meal</th>
                      <th scope="colgroup" colSpan={4} title="Scenario minus a zero-carb meal logged at the same time: both legs reset the model's time-since-meal input, so this isolates the carb content">
                        vs zero-carb meal now (primary)</th>
                      <th scope="colgroup" colSpan={showWalk ? 3 : 2} className="sim-twin" title="Research estimate, not the served forecast: grams × this patient's learned carb sensitivity × a response shape fitted on synthetic training patients. Held-out synthetic test MAE 5.9 mg/dL at +120 min (served What-If 37.3).">
                        Personalised twin curve (research)</th>
                      <th scope="colgroup" colSpan={2} className="sim-secondary" title="Scenario minus the forecast with no meal. Also contains the model's learned meal-timing expectation (after a long gap it anticipates a meal), so it can differ from the primary comparison">
                        vs no meal</th>
                      <th scope="col" rowSpan={2} className="sim-low" title="Whether the lower edge of the scenario forecast's 80% prediction interval falls below 70 mg/dL within 120 min. An interval edge, not a probability.">
                        Low watch<br /><span className="tiny muted">lower bound &lt;70</span></th>
                    </tr>
                    <tr>
                      <th scope="col">Δ +30 min</th><th scope="col">Δ +60 min</th><th scope="col">Δ +120 min</th><th scope="col">Excursion risk</th>
                      <th scope="col" className="sim-twin">Δ +60 min</th><th scope="col" className="sim-twin">Δ +120 min</th>
                      {showWalk && <th scope="col" className="sim-twin" title="Meal plus the walk; in brackets the walk's own effect">+ walk, Δ +120 min</th>}
                      <th scope="col" className="sim-secondary">Δ +60 min</th><th scope="col" className="sim-secondary">Excursion risk</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sims.map(({ grams, label, result }) => {
                      const p = comparisonCells(result.primary), s = comparisonCells(result.secondary);
                      const support = jointSupportChip(result.joint_support);
                      const low = scenarioLowWatchCell(result.scenario?.trajectory, hypoMeds);
                      return (
                        <tr key={`${result.as_of}-${grams}`} className={result.small_meal_unreliable ? "sim-unreliable" : undefined}>
                          <td>{grams} g{label && <span className="muted tiny sim-label">{label}</span>}{result.small_meal_unreliable && (
                            <span className="sim-flag" title="Meals under 30 g are unreliable in this model: few training meals are that small and the audited small-meal differences are unstable">unreliable &lt;30 g</span>)}{support && (
                            <span className="sim-flag sim-support" title={support.title}>{support.label}</span>)}</td>
                          <td>{p.d30}</td><td>{p.d60}</td><td>{p.d120}</td>
                          <td className={p.riskQualified ? "sim-qualified" : undefined} title={p.riskTitle}>{p.risk}{p.riskQualified && " *"}</td>
                          {(() => {
                            const tc = result.twin_curve;
                            const span = showWalk ? 3 : 2;
                            if (!tc) return <td className="sim-twin muted" colSpan={span} title="This server or snapshot predates the research twin curve, or the twin has no carb-sensitivity estimate yet">n/a</td>;
                            const flag = tc.within_tested_range ? "" : " sim-twin-outside";
                            const title = `${tc.caveat}${tc.within_tested_range ? "" : ` Outside the tested range: ${tc.outside_tested_reasons.join("; ")}.`}`;
                            return (<>
                              <td className={`sim-twin${flag}`} title={title}>{fmtDelta(tc.delta_glucose_mg_dl["60"])}</td>
                              <td className={`sim-twin${flag}`} title={title}>{fmtDelta(tc.delta_glucose_mg_dl["120"])}{!tc.within_tested_range && <span className="sim-flag">untested</span>}</td>
                              {showWalk && <td className={`sim-twin${flag}`} title={title}>{tc.with_walk_delta_glucose_mg_dl
                                ? <>{fmtDelta(tc.with_walk_delta_glucose_mg_dl["120"])} <span className="muted tiny">(walk {fmtDelta(tc.walk_delta_glucose_mg_dl?.["120"])})</span></>
                                : "–"}</td>}
                            </>);
                          })()}
                          <td className="sim-secondary">{s.d60}</td>
                          <td className={`sim-secondary${s.riskQualified ? " sim-qualified" : ""}`} title={s.riskTitle}>{s.risk}{s.riskQualified && " *"}</td>
                          <td className={`sim-low${low.flagged ? " sim-low-flag" : ""}`} title={low.title}>{low.text}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </>)}
            {sims.length > 0 && (() => {
              const last = sims[sims.length - 1].result;
              if (!last.primary) {
                return <span className="muted small" style={{ flexBasis: "100%" }}>Latest scenario withheld — not enough recent CGM data for a reliable what-if at this moment.</span>;
              }
              const d60 = last.primary.delta_glucose_mg_dl["60"];
              const cob = state?.carbs_on_board_g ?? 0;
              const notes = [...last.notes];
              if (d60 != null && Math.abs(d60) < 2 && !last.small_meal_unreliable) {
                notes.push(cob >= 5
                  ? `≈ no carb effect — the model already carries ~${Math.round(cob)} g of carbs on board from logged meals, so additional carbs add little.`
                  : "≈ no carb effect — at this moment the hypothetical carbs barely move the +60-min forecast.");
              }
              return notes.length ? (
                <ul className="sim-notes muted tiny" aria-label="Notes on the latest scenario">
                  {notes.map((n) => <li key={n}>{n}</li>)}
                </ul>
              ) : null;
            })()}
            <div className="muted tiny" style={{ flexBasis: "100%" }}>Each scenario is computed independently on a copy of the observation history — the hypothetical
              meal is never added to the patient record, and scenarios do not affect each other or the replay. Differences are <b>learned associations</b> of
              forecasting models trained on synthetic simulator data, not causal physiological effects (backlog B-22). Meal presets: {PRESET_NOTE} An
              "outside training support" tag means no training meal was comparable; inputs inside the training range still do not make a forecast accurate. <span className="sim-qualified">*</span> starting
              risk above 95%: change not informative. Not medical advice, not a treatment recommendation. The chart overlays the latest scenario.</div>
            <div className="muted tiny whatif-research" style={{ flexBasis: "100%" }}>
              <b>Personalised twin curve column (research; synthetic simulator):</b> grams × this patient's learned carb sensitivity × a
              response shape fitted on training patients, scale chosen on validation patients, test scored once. Against simulator ground truth
              at +120 min (2,953 scenarios, 12 held-out patients) it had MAE 5.9 mg/dL, versus 16.8 for a train-only cohort-average curve and
              37.3 for the served What-If columns. The simulator's near-linear meal response favours it. <b>Walk toggle:</b> a cohort-level
              effect (the twin has no personal activity parameter) scaled by the latest CGM; held-out test MAE 4.3 mg/dL at +120 min against
              11.6 for assuming no effect. It reflects the simulator's built-in exercise model. Neither is real-data evidence, neither changes
              the served forecast, and "untested" marks inputs outside the 20–120 g / CGM ≤180 mg/dL test range. Details:
              docs/research/TWIN_VALIDITY.md (addenda v3 and v4).
            </div>
          </div>
          <GlucoseChart cgm={cgm} meals={meals} forecast={forecast} scenario={sims.length ? sims[sims.length - 1].result.scenario : null}
                        history={history} clockMs={clockMs} offsetMin={offset} windowHours={WINDOW_HOURS} showPastPredictions={showPast} />
        </section>
        <RiskPanel forecast={forecast} state={state} history={history} offset={offset} medications={record.medications} />
      </div>
      <SensorTimeline clockMs={clockMs} offsetMin={offset} windowHours={WINDOW_HOURS}
                      cgm={cgm} meals={meals} steps={steps} heartRate={heartRate} forecasts={history} />
      <RiskTimeline history={history} threshold={forecast?.excursion?.alert_threshold ?? null} clockMs={clockMs}
                    offsetMin={offset} windowHours={WINDOW_HOURS} />
      <div className="insight-row">
        <AgpCard patientId={patientId} offset={offset} onLoad={setAgp} />
        <HandoverCard input={handover} />
      </div>
      <StatePanel state={state} />
    </div>
  );
}
