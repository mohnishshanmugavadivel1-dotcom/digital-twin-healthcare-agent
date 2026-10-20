# GlucoTwin — A Continuously Updated Glucose Digital Twin

**Happiest Health Digital Twin Challenge 2026 · Prototype & Code Submission**

GlucoTwin is a replayable, evidence-aware glucose digital-twin research prototype. It combines synthetic patient health records with simulated continuous glucose monitoring (CGM), meals, steps and heart-rate observations to forecast glucose trajectories, estimate hyperglycaemic excursion risk and explore hypothetical meal scenarios.

> **Safety notice:** GlucoTwin is an educational research prototype, not a medical device. All patients and observations are synthetic. Predictions and simulations are not clinical evidence, diagnoses, real-care alerts or treatment advice. The system has not been clinically validated.

## Table of contents

- [1. Project overview](#1-project-overview)
- [2. Problem statement](#2-problem-statement)
- [3. Healthcare use case](#3-healthcare-use-case)
- [4. Key features](#4-key-features)
- [5. System architecture](#5-system-architecture)
- [6. Technical stack](#6-technical-stack)
- [7. AI/ML models and methodology](#7-aiml-models-and-methodology)
- [8. Evaluation results](#8-evaluation-results)
- [9. Quick start](#9-quick-start)
- [10. Using the dashboard](#10-using-the-dashboard)
- [11. Counterfactual simulation and limitations](#11-counterfactual-simulation-and-limitations)
- [12. Repository structure](#12-repository-structure)
- [13. Testing and reproducibility](#13-testing-and-reproducibility)
- [14. Submission artefacts](#14-submission-artefacts)
- [15. Team and institution](#15-team-and-institution)
- [16. Open-source licence](#16-open-source-licence)
- [17. Limitations and future work](#17-limitations-and-future-work)
- [18. Submission compliance checklist](#18-submission-compliance-checklist)

## 1. Project overview

A glucose digital twin is a computational representation of a person's glucose-related state that can be updated as observations arrive and used to explore future trajectories.

GlucoTwin demonstrates this concept using reproducible synthetic patients with type 2 diabetes. It combines:

- **Synthetic health records:** HbA1c, fasting glucose, eGFR, medications and health conditions.
- **Simulated sensor observations:** CGM readings, step counts and heart rate.
- **Meal observations:** Logged carbohydrate intake.
- **A stateful twin engine:** Processes observations chronologically and maintains the current simulated patient state.
- **Forecasting models:** Predict glucose trajectories over the next 30–120 minutes, with model-generated uncertainty intervals.
- **An excursion-risk model:** Estimates the probability of a defined hyperglycaemic excursion onset within the next two hours.
- **An evidence-aware dashboard:** Displays observations, predictions, uncertainty, data quality, model information and hypothetical scenarios.

Family history and genotype may be displayed as synthetic contextual information; they are not model inputs in the current implementation.

### The central idea

The system is designed to make a prediction inspectable: what was observed, what was predicted, how uncertain the prediction is, what information was available at that time, and how the model's forecast changes in a hypothetical scenario.

![GlucoTwin dashboard](docs/screenshots/dashboard.png)

*Dashboard screenshot from the synthetic research prototype.*

### Processing pipeline

```text
Synthetic patient record
          |
          v
Time-ordered simulated sensor streams
          |
          v
Twin state update
          |
          v
Glucose trajectory forecast + uncertainty
          |
          v
Hyperglycaemic excursion-risk estimate
          |
          v
Evidence-aware clinician dashboard
          |
          +----> Transparent evaluation and audit
          |
          +----> Isolated counterfactual simulation
```

The twin only processes observations up to the current replay time. Future observations are not available to the twin before their simulated arrival.

## 2. Problem statement

Glucose forecasting outputs can be difficult to interpret when users cannot distinguish observed measurements from model predictions, assess the freshness of the input data, identify missing sensor periods or understand the uncertainty and provenance of a prediction.

A single risk score also does not show how a model's output relates to historical observations or how a hypothetical change affects its forecast.

GlucoTwin explores a transparent digital-twin workflow that brings together chronological replay, glucose forecasting, uncertainty intervals, data-quality evidence, historical prediction comparisons and isolated counterfactual scenarios.

The project focuses on demonstrating a reproducible research system—not establishing clinical effectiveness.

## 3. Healthcare use case

**Use case: Exploratory glucose trajectory forecasting and excursion-risk analysis.**

A researcher or demonstrator can select a synthetic patient and replay the patient's observations in chronological order. The dashboard shows the current simulated glucose state, forecasts at multiple horizons, an estimated excursion risk and the evidence available to the model.

The user can then inspect data gaps, compare earlier predictions with subsequent observations, and simulate hypothetical meals without adding them to the original patient record.

This workflow demonstrates how a digital-twin interface can support investigation of model behaviour and data quality.

### Demonstrated research tasks

1. Inspect a synthetic patient's health record and recent glucose history.
2. Replay sensor observations chronologically.
3. Examine predicted glucose values and model-generated uncertainty.
4. Inspect estimated excursion risk and grouped model attributions.
5. Identify stale or missing sensor observations.
6. Compare previous forecasts with later synthetic observations.
7. Explore hypothetical meal scenarios independently of the recorded history.
8. Review model evaluation metrics, assumptions and known limitations.

**Clinical boundary:** GlucoTwin does not diagnose diabetes, recommend medication changes, calculate insulin doses, or provide treatment instructions. It has no validated real-world clinical alerting capability.

## 4. Key features

### 4.1 Chronological replay

- Select from the available synthetic test patients.
- Advance the replay using the play control, five-minute steps or one-hour steps.
- Control replay speed using the dashboard.
- Inspect observations only after their simulated arrival time.
- Restart the replay to revisit a reproducible scenario.

### 4.2 Glucose forecasting

- Forecast horizons: 30, 60, 90 and 120 minutes.
- Historical glucose observations and predicted trajectories displayed separately.
- Model-generated 80% prediction intervals.
- Earlier 60-minute predictions can be compared with later observations.
- Model version and prediction provenance are displayed in the interface.

### 4.3 Hyperglycaemic excursion-risk estimation

The event model estimates the probability of a defined hyperglycaemic excursion onset within the next two hours.

The dashboard presents the estimated risk, the implemented event definition and grouped feature attributions. The risk estimate is model-generated and must not be interpreted as a clinically validated alert.

### 4.4 Forecast evidence and data quality

The evidence panel exposes information including:

- Time since the latest CGM observation.
- Recent observation completeness.
- Gaps exceeding the configured duration.
- Number of observations ingested.
- Replay timestamp.
- Previous forecast values.
- Forecast intervals and model provenance.

The application can represent insufficient or stale evidence without presenting every requested forecast as reliable.

### 4.5 Multisensor timeline

The timeline aligns the available synthetic streams:

- CGM observations and missing-data gaps.
- Logged meals.
- Step counts.
- Heart-rate observations.
- Forecast issue markers.

All streams are simulator-generated. The current system does not claim real wearable integration or a sleep-data stream.

### 4.6 Counterfactual scenario lab

The what-if interface allows hypothetical meal scenarios to be evaluated against the current simulated state.

- Compare scenario outputs at +30, +60 and +120 minutes, with the available intermediate horizons where displayed.
- Inspect predicted glucose differences and excursion-risk changes.
- Compare multiple hypothetical meals.
- Display the latest scenario as a distinct simulated chart overlay.
- Clear the scenario comparisons.
- Keep hypothetical meals out of the original patient record.

Each scenario is evaluated on a copy of the observation history. Scenarios are independent of each other and do not alter the underlying replay history.

Counterfactual outputs are exploratory simulator outputs, not predictions of a real person's physiological response.

## 5. System architecture

GlucoTwin uses a layered architecture.

| Layer | Responsibility |
|---|---|
| Synthetic data generation | Generates reproducible patient records and simulated sensor streams. |
| Dataset and feature pipeline | Constructs model targets and features and creates patient-level data splits. |
| Model training and evaluation | Trains trajectory and event-risk models and computes evaluation metrics. |
| Twin state engine | Ingests observations, updates patient state and produces forecasts. |
| Service layer | Coordinates patient records, replay sessions, forecasts, risk estimates and simulations. |
| FastAPI backend | Exposes application functionality through API routes and OpenAPI documentation. |
| React dashboard | Displays patient context, replay controls, glucose forecasts, evidence, sensor streams and scenarios. |
| Testing and audit | Checks temporal leakage, replay behaviour, scenario isolation, API behaviour and model evaluation. |

### Architecture diagram

**PDF:** [GlucoTwin Architecture](docs/submission/GlucoTwin_Architecture.pdf)

The diagram should be opened and verified before submission to confirm that it exists on the submitted branch and is accessible to public visitors.

## 6. Technical stack

| Component | Technology |
|---|---|
| Backend language | Python |
| API framework | FastAPI |
| Data validation and contracts | Pydantic |
| Frontend framework | React |
| Frontend language | TypeScript |
| Development server and bundler | Vite |
| Data visualization | Recharts |
| Model training and evaluation | Python-based ML pipeline |
| API specification | OpenAPI / Swagger UI |
| Python testing | pytest |
| Python linting | Ruff |
| Frontend verification | TypeScript checks and Vite production build |
| Test automation | Makefile-based checks and Node.js test runner for tooltip formatting |

For the supported environment, use Python 3.11+ and Node.js 20+. Consult the repository's lockfiles and configuration for exact dependency versions.

## 7. AI/ML models and methodology

GlucoTwin uses separate modeling tasks for continuous glucose trajectory forecasting and hyperglycaemic excursion-risk estimation.

### 7.1 Glucose trajectory forecasting

The trajectory pipeline evaluates the following candidates:

- Persistence baseline.
- Damped-trend baseline.
- Ridge regression.
- Histogram gradient boosting.

The reported served trajectory model is histogram gradient boosting. The selection protocol uses mean validation RMSE across the evaluated horizons rather than choosing a model based on individual test-set results.

Prediction intervals are generated by the repository's conformal-interval procedure. Their measured coverage is reported as a property of the synthetic evaluation, not a guarantee for real-world patients.

### 7.2 Excursion-risk estimation

The event-risk pipeline evaluates:

- A trend-rule baseline.
- Logistic regression.
- Histogram gradient boosting.

The reported served event model is logistic regression with standardized features and a validation-selected threshold. Its grouped additive contributions are used to explain the estimated log-odds without requiring an approximate SHAP explanation.

Histogram gradient boosting is reported as an alternative model for comparison.

### 7.3 Frozen event definition

At a time \(t\), the event question is evaluated only when the latest CGM reading is at or below 180 mg/dL.

An event is positive if at least three consecutive five-minute CGM readings above 180 mg/dL begin within the interval \((t, t + 120\text{ minutes}]\). Missing-data gaps break a consecutive run.

Full details: [API and data contracts](docs/API_CONTRACTS.md).

### 7.4 Validation protocol

The documented protocol uses 60 synthetic patients with patient-level splits:

| Split | Patients |
|---|---:|
| Training | 36 |
| Validation | 12 |
| Held-out test | 12 |
| Total | 60 |

Models are fitted using the training split. Thresholds and conformal interval widths are selected using validation data. The held-out test split is reserved for evaluation rather than model selection.

The reported results are generated by the repository's training and evaluation pipeline. See [ML baseline and validation plan](docs/ML_PLAN.md), [Wave-2 independent audit](docs/AUDIT_WAVE2.md) and [Model comparison and selection](docs/MODEL_COMPARISON.md).

## 8. Evaluation results

**All results in this section refer to synthetic patients. They are not clinical validation.** The simulator may be easier for a model to learn than real-world physiology, and the held-out cohort is limited.

### 8.1 Glucose trajectory forecasting

Reported test-split RMSE, in mg/dL:

| Model | 30 min | 60 min | 90 min | 120 min |
|---|---:|---:|---:|---:|
| Persistence (last value) | 18.7 | 31.4 | 40.7 | 46.6 |
| Damped trend | 17.4 | 31.1 | 42.5 | 50.4 |
| Ridge regression | 11.2 | **17.0** | 23.6 | 27.9 |
| **Histogram gradient boosting (served)** | **10.4** | 17.2 | **22.9** | **25.9** |

The Ridge model has a slight test-set advantage at 60 minutes, while histogram gradient boosting has lower reported RMSE at the other listed horizons. The served model is selected using the documented mean validation RMSE protocol, not by selecting individual test-set winners after evaluation.

### 8.2 Hyperglycaemic excursion-risk estimation

Reported held-out synthetic test results:

| Model | AUROC | AUPRC | Sensitivity | Specificity | Episodes warned | Median lead | False-alert episodes/day |
|---|---:|---:|---:|---:|---:|---:|---:|
| Trend-rule baseline | 0.655 | 0.324 | 0.44 | 0.74 | 100% | 60 min | 6.3 |
| **Logistic regression (served)** | **0.884** | **0.668** | 0.67 | 0.90 | 91% | 95 min | 1.4 |
| Histogram gradient boosting | 0.936 | 0.756 | 0.78 | 0.90 | 96% | 120 min* | 1.1 |

\*Lead time is capped at the 120-minute forecast horizon.

“Episodes warned” counts an episode if an alert occurs during the two hours before onset. Under the stricter sustained-warning definition—where the alert remains active immediately before onset—the served model warns about 69% of onsets, with a median lead of 85 minutes and a reported 95% patient-bootstrap confidence interval of 0.48–0.83 for the sustained-warning rate.

The served logistic-regression AUROC confidence interval is reported as 0.839–0.923.

### 8.3 Additional evaluation details

The repository reports:

- Test prevalence of 14.6% among eligible time points.
- Clarke error grid A+B of at least 95.7% at all evaluated horizons.
- 80% conformal prediction interval coverage of approximately 0.76–0.80.
- A documented model-selection protocol and alternative-model comparisons.

These figures describe the implemented synthetic evaluation. They do not establish clinical accuracy, safety, usefulness or generalization to real patients.

For detailed definitions, confidence intervals, ablations and caveats, consult [Wave-2 audit](docs/AUDIT_WAVE2.md) and [Model comparison](docs/MODEL_COMPARISON.md).

## 9. Quick start

### Requirements

- Python 3.11 or later.
- Node.js 20 or later.
- npm.
- Make.

The repository has been developed using pinned Python dependencies and npm lockfile-based frontend installation.

### Install and run

```bash
make setup
make train
make serve
```

The commands perform the following operations:

| Command | Purpose |
|---|---|
| `make setup` | Creates the Python virtual environment and installs pinned Python and frontend dependencies. |
| `make train` | Generates the deterministic synthetic cohort and trains/evaluates the models. |
| `make serve` | Builds the dashboard and starts the API and frontend application. |
| `make check` | Runs the configured lint, test, frontend type-check and build checks. |

The synthetic cohort is configured for 60 patients over 14 days using seed `20261017`.

### Local application URLs

When the server is running:

- Dashboard: [http://localhost:8000](http://localhost:8000)
- API documentation: [http://localhost:8000/docs](http://localhost:8000/docs)
- API health endpoint: [http://localhost:8000/api/health](http://localhost:8000/api/health)
- Vite development server: [http://localhost:5173](http://localhost:5173), when running `make dev-frontend`.

These are local development addresses, not public deployment URLs.

### Alternative setup without Make

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock
.venv/bin/pip install -e . --no-deps
.venv/bin/glucotwin train

cd frontend
npm ci
npm run build
cd ..

.venv/bin/glucotwin serve --host 0.0.0.0 --port 8000
```

On Windows, use the equivalent commands for the active shell and virtual-environment paths.

## 10. Using the dashboard

1. Select a synthetic test patient from the patient list.
2. Use **Play**, **+5 min** or **+1 h** to advance chronological replay.
3. Inspect the recent CGM trace, forecast curve and uncertainty band.
4. Review the excursion-risk estimate and its definition.
5. Inspect the grouped factor-attribution panel. These contributions are model associations, not proof of biological causation.
6. Toggle the earlier 60-minute predictions to compare earlier forecasts with subsequent synthetic observations.
7. Inspect the data-quality evidence, including freshness, completeness and gaps.
8. Open the aligned multisensor timeline.
9. Enter a hypothetical meal in the scenario lab and inspect the resulting simulated forecast.
10. Compare scenarios and clear them when finished.
11. Open the model-evaluation view to inspect the documented metrics.

### Reproducible demonstration scenarios

The README's existing demonstration notes identify the following deep links:

- `/?patient=SYN-0039&start=151.833` — documented as an example of an early warning before an excursion.
- `/?patient=SYN-0019&start=253.667` — documented as an example of a missed excursion after an unlogged meal.

Example links:

- [Early-warning scenario](http://localhost:8000/?patient=SYN-0039&start=151.833)
- [Missed-excursion scenario](http://localhost:8000/?patient=SYN-0019&start=253.667)

These links work only where the GlucoTwin application is running. Recheck the exact readings and replay behaviour before using the scenarios in a recorded demonstration.

## 11. Counterfactual simulation and limitations

The what-if meal simulation operates on a copy of the available observation history. It does not ingest the hypothetical meal into the original patient record, change the original twin history or make scenarios affect one another.

The interface distinguishes simulated outputs from observed and forecast values.

### Known counterfactual limitation

Testing has identified a simulator artifact in which a small hypothetical meal can produce a negative change in the +60-minute predicted glucose compared with the baseline. One previously observed larger negative change did not reproduce at its original replay point in a subsequent investigation; the broader small-meal inconsistency remains a known limitation.

The exact physiological validity of these counterfactual outputs has not been established. Do not interpret them as reliable predictions of how a real person would respond to a meal.

The engine is kept frozen under the current sprint guardrails. Potential remediation is documented in [the project backlog](docs/BACKLOG.md), item B-22.

### Temporal integrity

The project includes tests for replay behaviour, leakage prevention and scenario isolation. The twin should only use observations that have arrived by the current replay time. Historical and simulated outputs must remain explicitly labelled.

## 12. Repository structure

| Path | Contents |
|---|---|
| `src/glucotwin/contracts.py` and `config.py` | Shared Pydantic contracts and frozen configuration constants. |
| `src/glucotwin/synth/` | Synthetic patient and sensor-stream generation. |
| `src/glucotwin/labels.py`, `features.py`, `dataset.py` | Targets, feature construction, datasets and patient-level splits. |
| `src/glucotwin/models/` | Model implementations and related components. |
| `src/glucotwin/evaluation/` | Training and evaluation pipeline, metrics and intervals. |
| `src/glucotwin/twin/engine.py` | Patient-state engine and observation/forecast processing. |
| `src/glucotwin/service.py` and `api/app.py` | Service layer, replay sessions and FastAPI routes. |
| `frontend/` | React, TypeScript and Recharts dashboard. |
| `tests/` | Python tests for API behaviour, temporal leakage, replay and scenario isolation. |
| `frontend/tests/` | Frontend formatter regression tests. |
| `scripts/` | Demo-moment discovery, presentation building and PDF export utilities. |
| `docs/submission/` | Architecture and presentation artefacts and their source files. |
| `docs/` | Architecture, contracts, ML plan, feasibility, QA/security, decisions, backlog and competition notes. |
| `reports/` | Generated evaluation and audit reports, where present. |

## 13. Testing and reproducibility

The project uses automated checks to reduce regressions and support reproducibility.

### Standard verification

```bash
make check
```

The configured checks include:

- Ruff linting.
- Python tests.
- Frontend tooltip formatter tests.
- TypeScript checks.
- Vite production build.

### Latest reported verification

According to the Arena engineering report for commit `04a0170`, the following checks completed successfully:

- 67 Python tests passed.
- 4 frontend formatter tests passed.
- Ruff checks passed.
- TypeScript and Vite production build passed.
- `make check` exited with code 0.

The tooltip formatter regression test covers the unexpected timestamp entry, glucose-value formatting, interval bands, meal carbohydrate values and invalid or unknown entries.

**Verification caveat:** These results are reported from the development environment. Browser-based visual QA was not available in that environment. The tooltip's rendered appearance, narrow-screen table overflow, browser console errors and keyboard interaction still require direct browser inspection. Check the latest GitHub Actions run before relying on the results for the submitted commit.

## 14. Submission artefacts

This section maps the challenge submission requirements to the repository.

| Required item | Location or status |
|---|---|
| Public GitHub repository | [GlucoTwin repository](https://github.com/mohnishshanmugavadivel1-dotcom/digital-twin-healthcare-agent) |
| Project title and problem statement | This README |
| Healthcare use case | This README |
| Technical stack | This README |
| AI/ML model and evaluation details | This README and linked model documentation |
| Architecture diagram in PDF format | [GlucoTwin Architecture PDF](docs/submission/GlucoTwin_Architecture.pdf) |
| Project presentation in PDF format | [GlucoTwin Presentation PDF](docs/submission/GlucoTwin_Presentation.pdf) |
| Demo video | **TODO: Add final unlisted YouTube link after upload.** |
| Open-source licence | `LICENSE` — confirm final copyright-holder details. |
| Team and institution | This README; verify against Unstop registration. |
| Public accessibility | **TODO: Verify all files and links while logged out.** |

### Demo video

**Video link:** `TODO — ADD FINAL UNLISTED YOUTUBE URL`

The Unstop form screenshot requests a 15–20-minute demonstration. The existing README previously specified a minimum of 20 minutes. Confirm the applicable official challenge requirement and use a consistent duration before recording.

Suggested demonstration structure:

1. Project motivation and problem statement.
2. Architecture and technical stack.
3. Synthetic patient selection and chronological replay.
4. Glucose forecast and uncertainty intervals.
5. Excursion-risk panel and data-quality evidence.
6. Multisensor timeline.
7. Counterfactual scenario lab.
8. Evaluation metrics and model-selection protocol.
9. Known limitations and medical safety boundaries.
10. Reproducibility, repository structure and future work.

Do not replace the video placeholder until the recording is uploaded and the link has been tested.

## 15. Team and institution

| Field | Details |
|---|---|
| Team name | team mono |
| Institution | Amrita Vishwa Vidyapeetham, Chennai |
| Team size | 1 |
| Team member | Mohnish Shanmugavadivel |
| Role | Solo student developer |
| Team leader contact | TODO — confirm the preferred public contact detail. |

Confirm all team information against the Unstop registration before submitting. Avoid publishing personal contact details unless required and intentionally approved for public disclosure.

## 16. Open-source licence

The repository contains an MIT licence file at `LICENSE`.

**Current status:** The existing project notes state that the copyright-holder text is not final and remains `GlucoTwin contributors` pending confirmation of the applicable institutional intellectual-property policy.

Before submission:

1. Inspect the actual `LICENSE` file.
2. Confirm the copyright holder and permission to publish under the MIT licence.
3. Confirm the applicable institutional IP policy.
4. Make the README and licence file consistent.

Do not claim that the licence is finalized until this has been verified.

The project's synthetic data are generated by the repository's code. Do not claim that third-party patient datasets are included unless that is independently verified.

## 17. Limitations and future work

### Current limitations

- All patient records and observations are synthetic.
- Synthetic simulator dynamics may be easier to predict than real physiology.
- The held-out test cohort is small and does not establish generalization to real patients.
- The event-risk and trajectory results are not clinical validation.
- The counterfactual simulator has a documented small-meal inconsistency.
- Browser-based visual, responsive and accessibility QA remains to be completed.
- The application does not claim real wearable integration or a sleep-data stream.
- The dashboard is a research prototype and is not suitable for clinical decision-making.

### Future work

- Evaluate against appropriately governed real-world datasets.
- Establish external and prospective validation before making clinical claims.
- Improve counterfactual consistency and test additional meal-response edge cases.
- Complete responsive, accessibility and browser-interaction testing.
- Investigate additional sensor streams only when suitable data and validated models are available.
- Continue improving the traceability of observations, predictions, model versions and evaluation results.

## 18. Submission compliance checklist

The challenge submission form requires the README to cover all listed items and the submitted files and links to be publicly accessible without additional permissions.

Before submitting, verify each requirement:

- [ ] Team details are included and match the Unstop registration.
- [ ] College/incubator information is included and correct.
- [ ] Project title is included.
- [ ] Problem statement is included.
- [ ] Healthcare use case is included.
- [ ] Technical stack is included.
- [ ] AI/ML model and framework details are included.
- [ ] The demo video has been uploaded as an unlisted YouTube video and its link is included in the README.
- [ ] Open-source licence details and copyright-holder information are verified.
- [ ] The architecture diagram PDF exists and opens publicly.
- [ ] The presentation PDF exists and opens publicly.
- [ ] The repository and every required file/link are publicly accessible without extra permissions.

### Final disclaimer

GlucoTwin is an experimental digital-twin research prototype that operates on synthetic patient data. Its predictions, risk estimates, feature attributions and counterfactual scenarios are not clinically validated and must not be used to guide medical care.
