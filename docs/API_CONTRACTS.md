# Shared data contracts and API (schema v0.1.0)

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
| POST | `/api/replay` | `ReplayCreate` {patient_id, start_offset_hours = 24, duration_hours?} | `ReplayStatus` (201) | 404 |
| GET | `/api/replay/{sid}` | – | `ReplayStatus` | 404 |
| POST | `/api/replay/{sid}/step` | `ReplayStep` {minutes: 5–1440} | `ReplayStatus` | 404, 422 |
| DELETE | `/api/replay/{sid}` | – | 204 | 404 |
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
