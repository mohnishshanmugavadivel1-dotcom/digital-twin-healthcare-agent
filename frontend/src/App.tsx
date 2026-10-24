import { useCallback, useEffect, useState } from "react";
import { api, IS_STATIC_DEMO } from "./api/client";
import { loadManifest } from "./api/static";
import type { SnapshotManifest } from "./api/staticReplay";
import type { HealthStatus, PatientSummary } from "./api/types";
import { EvaluationView } from "./components/EvaluationView";
import { PatientView } from "./components/PatientView";
import { glucoseClass, num, riskPct } from "./format";

type Tab = "patients" | "evaluation";

export default function App() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [patients, setPatients] = useState<PatientSummary[]>([]);
  // Deep link for reproducible demos: ?patient=SYN-0004&start=36 (replay starts 36 h into the record)
  const params = new URLSearchParams(window.location.search);
  const linkPatient = params.get("patient");
  const linkStart = Number(params.get("start"));
  const [selected, setSelected] = useState<string | null>(linkPatient);
  const [tab, setTab] = useState<Tab>("patients");
  const [error, setError] = useState<string | null>(null);
  const [threshold, setThreshold] = useState(0.5);
  const [snapshot, setSnapshot] = useState<SnapshotManifest | null>(null);
  useEffect(() => { if (IS_STATIC_DEMO) loadManifest().then(setSnapshot).catch((e) => setError(String(e))); }, []);

  const loadPatients = useCallback(() => {
    api.patients().then((p) => {
      setPatients(p);
      setSelected((s) => s ?? p[0]?.patient_id ?? null);
    }).catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    api.health().then(setHealth).catch((e) => setError(String(e)));
    api.model().then((m) => setThreshold(m.alert_threshold)).catch(() => undefined);
    loadPatients();
  }, [loadPatients]);

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">GlucoTwin <span className="muted small">clinician dashboard</span></div>
        <nav>
          <button className={tab === "patients" ? "tab active" : "tab"} onClick={() => setTab("patients")}>Patients</button>
          <button className={tab === "evaluation" ? "tab active" : "tab"} onClick={() => setTab("evaluation")}>Model evaluation</button>
        </nav>
        <div className="muted tiny">{health ? `model ${health.model_version}` : ""}</div>
      </header>
      <div className="banner" role="note">
        Research prototype on <b>synthetic patients</b>. Not a medical device. Forecasts are not diagnoses or treatment instructions.
      </div>
      {IS_STATIC_DEMO && (
        <div className="static-banner" role="note" aria-label="Static snapshot notice">
          <div className="static-headline"><b>Interactive Static Demo Snapshot (GitHub Pages)</b> · Precomputed from the GlucoTwin Engine ·
            Explore Featured Clinical Scenarios, Indian Meal What-If Presets &amp; ABDM FHIR R4 Records</div>
          <div className="static-provenance tiny">Static recorded snapshot, not a live system: precomputed by <code>scripts/export_static_demo.py</code> from
            the real GlucoTwin API{snapshot && <> (model {snapshot.model_version}, commit {snapshot.git_head.slice(0, 7)}{snapshot.working_tree_dirty_at_recording ? " plus uncommitted changes" : ""},
            recorded {snapshot.recorded_at.slice(0, 10)})</>}. Nothing is computed in your browser. Synthetic patients only; the FHIR
            export is an R4 interoperability prototype, not ABDM-certified or profiled against NRCeS guides.{" "}
            <details className="static-details">
              <summary>What was recorded</summary>
              Meal presets every {snapshot?.preset_grid_minutes ?? 15} min of each replay, and every amount ({snapshot?.whatif_grams.join(", ")} g)
              at the marked moments; other requests say they were not recorded instead of guessing. The FHIR export is recorded once, at the
              replay start. {snapshot && <>Scenarios: {snapshot.scenarios.map((sc, i) => (
                <span key={sc.id}>{i > 0 && " · "}<a href={`?patient=${sc.patient_id}`} title={sc.description}>{sc.title}</a></span>))}. </>}
              For the full interactive app, run it locally (<code>make setup train serve</code>).
            </details>
          </div>
        </div>
      )}
      {error && <div className="card error">{IS_STATIC_DEMO ? "Snapshot could not be loaded" : "Backend unreachable"}: {error}</div>}
      {tab === "evaluation" ? <main className="content"><EvaluationView /></main> : (
        <div className="layout">
          <aside className="sidebar" aria-label="Patient list">
            <div className="muted tiny side-title">Held-out test patients ({patients.length})</div>
            {patients.map((p) => {
              const risk = p.latest_risk_probability;
              return (
                <button key={p.patient_id} className={p.patient_id === selected ? "pt active" : "pt"} onClick={() => setSelected(p.patient_id)}>
                  <div className="pt-name">{p.display_name}</div>
                  <div className="pt-meta">{p.age_years} y · {p.sex[0].toUpperCase()} · HbA1c {p.hba1c_percent}%</div>
                  <div className="pt-meta">
                    <span className={glucoseClass(p.latest_glucose_mg_dl)}>{num(p.latest_glucose_mg_dl)} mg/dL</span>
                    {risk !== null && <span className={`dot ${risk >= threshold ? "dot-high" : risk >= threshold / 2 ? "dot-mod" : "dot-low"}`} title="Latest excursion risk">{riskPct(risk)}</span>}
                  </div>
                </button>
              );
            })}
          </aside>
          <main className="content">
            {selected ? <PatientView key={selected} patientId={selected} onTick={loadPatients}
              startOffsetHours={selected === linkPatient && Number.isFinite(linkStart) && linkStart > 0 ? linkStart : 24} /> : <div className="card muted">Select a patient.</div>}
          </main>
        </div>
      )}
    </div>
  );
}
