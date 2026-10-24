# Shared data contracts and API (schema v0.3.0; additive fields and routes since, no breaking change)

**Changes in 0.3.0 (U1, submission day):** new `POST /api/patients/{id}/counterfactual` (`CounterfactualRequest{meal_grams 1–300}` → 201 `CounterfactualResult`, 422 out of bounds, 404 unknown or non-test patient). It simulates "what if the patient ate this many carbs now" and **never mutates the twin** (state, version, streams and forecast history are untouched; enforced by `tests/test_counterfactual.py`). `CounterfactualResult` is labelled `is_simulated: true` with a fixed disclaimer; the hypothetical meal is never ingested into the record.

**Changes in 0.2.0 (wave 2):** `PatientRecord` gains `family_history_t2d` and `genetic_markers[]`. Both are synthetic, display-only, and not model inputs. `ReplayCreate.start_offset_hours` and `duration_hours` are now bounded to ≤ 8,784 h (previously, huge values caused HTTP 500; now they return 422). Replay is restricted to held-out **test** patients (others return 404). Fractional offsets are rounded to the 5-min grid.

`src/glucotwin/contracts.py` is the source of truth; `frontend/src/api/types.ts` mirrors it. The live
OpenAPI schema is at `/docs` (Swagger UI) and `/openapi.json` while the server runs. Any change to a
contract requires a `SCHEMA_VERSION` bump plus an entry in [DECISIONS.md](DECISIONS.md).

## Conventions

* Timestamps are timezone-aware ISO-8601 strings (naive timestamps are rejected with 422). They are stored and returned in UTC. The dashboard
  shows patient-local time using `PatientRecord.utc_offset_minutes` (330 = IST).
* Units: glucose mg/dL; carbohydrates g; steps per 5-minute bin; heart rate bpm.
* Identifiers are `SYN-0001` and so on. The pattern `^SYN-\d{4}$` is enforced, so a real MRN cannot be ingested by accident.
* Every record carries `is_synthetic: true`, and every forecast carries a `disclaimer`.
* Unknown fields are rejected (`extra="forbid"`).

## Core schemas

| Schema | Purpose | Key fields |
|---|---|---|
| `PatientRecord` | Static or historical synthetic EHR | demographics, BMI, diabetes duration, HbA1c, fasting glucose, eGFR, conditions, medications (drug class), labs, `split` |
| `Observation` | One dynamic data point | `patient_id`, `timestamp`, `kind` (`cgm`, `meal`, `steps`, `heart_rate`), `value`, optional `unit` (validated) |
| `TwinState` | The virtual patient now | `as_of`, `version`, last glucose, trend and arrow, carbs on board, minutes since meal, steps over 60 min, HR over 30 min, `summary_24h` (TIR/TAR/TBR/mean/CV), `personal` (learned carb sensitivity versus EHR prior, meals used), `data_quality` (completeness, staleness, gaps) |
| `Forecast` | Output at a CGM reading | `status` (`ok` or `insufficient_data`), `trajectory` (30/60/90/120 min with 80% interval), `excursion` (probability, threshold, alert, band, top factor groups), `model_version`, `disclaimer` |
| `ForecastSummary` | Compact history row | `issued_at`, probability, alert, predicted glucose by horizon |
| `ReplayStatus` | Replay session | `clock` (nothing after it has been revealed), start, end, finished, state, forecast |
| `EvaluationReport` | Transparent evaluation | dataset card, target definition, split protocol, trajectory and event metrics per model, served models, notes |
| `ModelCard` | Served model metadata | version, features, threshold, intended use, limitations |

## Target definition (frozen)

> **Onset of a hyperglycaemic excursion** means 3 or more consecutive CGM readings above 180 mg/dL (at least 15 minutes) starting
> within the next 120 minutes. It is predicted only at times when the latest reading is at or below 180 mg/dL.

A missing reading breaks a run, and labels are undefined (excluded) when less than 50% of the future window was observed.
Trajectory targets are the observed CGM values at t+30, t+60, t+90 and t+120 minutes.

## REST endpoints

| Method | Path | Body / query | Returns | Errors |
|---|---|---|---|---|
| GET | `/api/health` | – | `HealthStatus` | – |
| GET | `/api/patients` | `split` = `test` (default), `validation` or `train` | `PatientSummary[]` | 422 for an invalid split |
| GET | `/api/patients/{id}` | – | `PatientRecord` | 404 |
| GET | `/api/patients/{id}/observations` | `kind`, `since`, `limit` (≤ 20000) | `Observation[]` (only what the twin has received) | 404 |
| POST | `/api/patients/{id}/observations` | `ObservationBatch` (1–5000) | `IngestResult` (accepted, duplicates, rejected, errors, state, forecast) | 404, 422 |
| GET | `/api/patients/{id}/state` | – | `TwinState` | 404 if there are no observations yet |
| GET | `/api/patients/{id}/forecast` | – | latest `Forecast` | 404 |
| GET | `/api/patients/{id}/forecasts` | `since`, `limit` | `ForecastSummary[]` | 404 |
| POST | `/api/replay` | `ReplayCreate` {patient_id (test split only), start_offset_hours = 24 (0–8784), duration_hours? (≤ 8784)} | `ReplayStatus` (201) | 404 |
| GET | `/api/replay/{sid}` | – | `ReplayStatus` | 404 |
| POST | `/api/replay/{sid}/step` | `ReplayStep` {minutes: 5–1440} | `ReplayStatus` | 404, 422 |
| DELETE | `/api/replay/{sid}` | – | 204 | 404 |
| POST | `/api/patients/{id}/counterfactual` | `CounterfactualRequest` {meal_grams: 1–300} | `CounterfactualResult` (201): `baseline` (no meal), `reference` (zero-carb meal at the same time) and `scenario` `Forecast`s; `primary` = scenario − reference and `secondary` = scenario − baseline (`CounterfactualComparison`: Δglucose per horizon, Δprobability, reference probability, `risk_saturated` when reference risk > 0.95); `small_meal_unreliable` (< 30 g), `notes`; legacy `delta_glucose_60mg_dl` / `delta_probability` keep their no-meal meaning; `is_simulated: true`, disclaimer (learned associations, not causal effects) — see B-22. Additive `twin_curve` (`TwinCurveEstimate`, may be null): research estimate from the personalised carb-response curve (Δ at +30/60/120 = k_h × grams × learned carb sensitivity) plus a cohort-level 20-min / 2,500-step post-meal walk effect (β_h × latest CGM) and their sum; `within_tested_range` (20–120 g, CGM ≤ 180), held-out synthetic test MAEs and a caveat. It never changes `primary`/`secondary` (see docs/research/TWIN_VALIDITY.md, addenda v3 and v4) | 404 (unknown or non-test patient), 422 (grams out of bounds / no CGM data) |
| GET | `/api/patients/{id}/agp` | `days` (1–14, default 14) | `AgpSummary`: hourly 5/25/50/75/95th percentiles by local hour, TIR 70–180, TAR >180 and >250, TBR <70 and <54, mean, CV, GMI (3.31 + 0.02392 × mean), coverage, `sufficient` (≥14 days and ≥70% of readings). Only CGM the twin has received; descriptive | 404, 409 (no observations yet), 422 |
| POST | `/api/fhir/Bundle` | FHIR R4 `Bundle` JSON (≤ 5000 entries); optional `patient_id` (`SYN-dddd`) | `FhirIngestResult`: parsed `observations` (CGM 99504-3, or 14749-6 with a lab-code warning and mmol/L × 18.016 conversion; heart rate 8867-4), `labs` (HbA1c 4548-4), `skipped` entries with reasons, `counts`, `warnings`, `ingested: false`. **Validation only**: nothing is added to any twin. Structural parse, not full FHIR validation | 422 (not a Bundle, too many entries, no synthetic patient ID) |
| GET | `/api/model` | – | `ModelCard` | – |
| GET | `/api/evaluation` | – | `EvaluationReport` | 404 if the report was never generated |

### Ingestion semantics

* **Validation per observation.** The patient id must match the path, the unit must equal the canonical unit when given, and the value
  must lie in the plausible range (CGM 20–600, HR 25–230, steps 0–2000 per 5 minutes, carbs 0–400). Rejected items are listed in `errors`,
  and the rest of the batch is still accepted.
* **Idempotency.** An observation with the same kind and timestamp as one already accepted is counted as a duplicate and ignored.
* **Ordering.** An observation older than the newest accepted observation of the same kind is rejected as out of order.
  Late-arriving data are deliberately not re-sorted in v0.1 (see backlog item B-12).
* **Forecast trigger.** One forecast is issued per accepted CGM reading.

### Replay semantics

Creating a session resets that patient's twin, pre-loads `start_offset_hours` of history, and sets the clock.
Each step reveals the observations in (clock, clock + minutes] and nothing else. Only one session per
patient is active at a time; a new one supersedes the old.
