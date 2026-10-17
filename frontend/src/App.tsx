import { useCallback, useEffect, useState } from "react";
import { api } from "./api/client";
import type { HealthStatus, PatientSummary } from "./api/types";
import { EvaluationView } from "./components/EvaluationView";
import { PatientView } from "./components/PatientView";
import { glucoseClass, num } from "./format";

type Tab = "patients" | "evaluation";

export default function App() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [patients, setPatients] = useState<PatientSummary[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("patients");
  const [error, setError] = useState<string | null>(null);
  const [threshold, setThreshold] = useState(0.5);

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
      {error && <div className="card error">Backend unreachable: {error}</div>}
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
                    {risk !== null && <span className={`dot ${risk >= threshold ? "dot-high" : risk >= threshold / 2 ? "dot-mod" : "dot-low"}`} title="Latest excursion risk">{Math.round(risk * 100)}%</span>}
                  </div>
                </button>
              );
            })}
          </aside>
          <main className="content">
            {selected ? <PatientView key={selected} patientId={selected} onTick={loadPatients} /> : <div className="card muted">Select a patient.</div>}
          </main>
        </div>
      )}
    </div>
  );
}
