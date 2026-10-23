# GlucoTwin — a living glucose digital twin for type 2 diabetes

**Happiest Health Digital Twin Challenge 2026 · Prototype & Code Submission · team mono**

GlucoTwin builds a personal, continuously updated model of a person with type 2 diabetes. It fuses their health record with CGM, meals, steps and heart rate. Every 5 minutes it forecasts glucose up to 2 hours ahead, warns when a hyperglycaemic excursion is coming, and lets a clinician ask *"what if they eat this meal now?"*. Each answer is shown with its evidence, uncertainty and data quality.

> **Status:** research prototype, not a medical device and not clinically validated. The dashboard runs on synthetic patients. Separately, we trained glucose-history forecasting models on 100 real people with type 2 diabetes (ShanghaiT2DM). The full GlucoTwin model has **not** been evaluated on real patients. Details: [Limitations and intended use](#limitations-and-intended-use).

![GlucoTwin clinician dashboard at 07:55 for synthetic patient SYN-0039: patient record, What-If table comparing 35 g, 120 g and 300 g meals against a zero-carb reference (300 g tagged outside training support), 12-hour CGM with a 2-hour forecast and 80% interval, excursion risk 22% with its drivers, evidence and data quality, all streams, risk history, and the personalised carb sensitivity of 1.70 learned from 20 meals](docs/screenshots/dashboard.png)

<sub>Synthetic patient SYN-0039 at 07:55 with three What-If meals. Captured on 2026-10-22 from the recorded static snapshot (current frontend; every response was recorded from the real API, model `gt-0.1.0-s20261017-202610211601`), served locally.</sub>

## Product overview

- **Designed for (research demo):** clinicians and care teams reviewing CGM data for people with type 2 diabetes.
- **What it does:**
  - forecasts glucose at +30/60/90/120 min with 80% intervals;
  - estimates the probability that an excursion (≥ 3 consecutive readings > 180 mg/dL) starts within 2 h, and explains the drivers;
  - compares hypothetical meals.
- **What it shows:** observed vs predicted glucose, earlier forecasts vs what actually happened, data freshness and gaps, and the patient's own learned carb sensitivity.
- **How it is built:** Python twin engine and ML pipeline, a FastAPI service and a React + TypeScript dashboard. It is reproducible from one seed with `make`.

## Why GlucoTwin is different

A glucose predictor takes a window of data and returns a number. GlucoTwin keeps a **patient state** that evolves over time:

- **It updates in time order.** Each observation is ingested as it "arrives". The state holds last glucose and trend, carbs on board, activity, data quality and a personalised parameter. A forecast at time *t* uses only data up to *t*. A test checks that replay never reveals future data, and the dashboard replays it chronologically.
- **It learns the individual.** Each patient's carb sensitivity starts from their health record and is updated from their own meal responses (see [How personalisation works](#how-personalisation-works)).
- **It answers "what if?" without touching the record.** A hypothetical meal is run on a copy of the history, never on the real record. It is compared against a zero-carb reference so that only the carbohydrate effect is isolated ([details](#what-the-comparison-means-backlog-b-22)).
- **It says when it is on thin ice.** Stale or missing CGM is flagged. Forecasts can return `insufficient_data` instead of guessing. A What-If meal unlike anything in training is tagged **outside training support** (API status `no_training_analogue`).
- **It shows its work.** Risk drivers are grouped, additive logistic-regression contributions (associations, not causes). Earlier 60-min forecasts can be overlaid on what really happened.

## Try the demo

**Recorded static snapshot.** No Python is needed, and every response was recorded from the real API ([docs/STATIC_DEMO.md](docs/STATIC_DEMO.md)).

```bash
cd frontend && npm ci && npm run build:static && npm run preview:static
# then open http://localhost:4173/
```

**Full live app:**

```bash
make setup && make train && make build-frontend && make serve
# then open http://localhost:8000/?patient=SYN-0039&start=151.833
```

**Public static snapshot:** [https://mohnishshanmugavadivel1-dotcom.github.io/digital-twin-healthcare-agent/](https://mohnishshanmugavadivel1-dotcom.github.io/digital-twin-healthcare-agent/). It is deployed by the manual GitHub Pages workflow ([`.github/workflows/pages-demo.yml`](.github/workflows/pages-demo.yml)), and the site was confirmed loading on 2026-10-23. The public site serves whichever snapshot was last deployed; its `demo/manifest.json` shows the commit and recording time. The snapshot in this repository was recorded on 2026-10-23 from clean commit a6c1d91 (model `gt-0.1.0-s20261017-202610230926`). It includes the FHIR panel with its RiskAssessment, the low-glucose watch (risk card and What-If column), the personalisation confidence line, the What-If research note and the 15-min preset grid. There is no demo video yet.

### 90-second judge walkthrough

All values below come from the recorded snapshot of synthetic patient SYN-0039 (times are patient-local, UTC+05:30).

| Time | Show | Say |
|---|---|---|
| 0:00–0:15 | Dashboard at **07:55** | "A twin of a person with type 2 diabetes: record, CGM, meals and activity. Glucose is 94 mg/dL; the twin forecasts 119 mg/dL at +60 min (80% interval 101–138) and a 22% excursion risk, so no alert." |
| 0:15–0:30 | *Personalised parameter* panel | "This patient's carb sensitivity started at 1.31 mg/dL per gram from their HbA1c. After 20 of their own meals it is 1.70: the twin has adapted to this person's meal responses." |
| 0:30–0:50 | What-If: *Idli with sambar* preset (≈ 35 g) | "Against a zero-carb meal, the predicted risk rises from 7% to 52%; 120 g gives > 99%. Try 300 g: it is tagged *outside training support*, so the twin flags that no comparable meal existed in training." |
| 0:50–1:05 | Press **+1 h** → 08:55 | "A 140 g breakfast was logged at 08:53. The alert fires at 08:55, 85 min before glucose first exceeds 180 mg/dL (10:20). Data quality: 97% CGM completeness, last reading 0 min ago." |
| 1:05–1:20 | *Model evaluation* tab, then the [real-data results](#results-at-a-glance) | "On held-out synthetic patients, forecast RMSE is 44–45% lower than persistence at every horizon. Separately, on 100 real people with type 2 diabetes, our glucose-history models beat persistence at every horizon." |
| 1:20–1:30 | [Limitations](#limitations-and-intended-use) | "It is not clinically validated, and the full twin has not been tested on real patients, because the public data lacks carb grams, steps and heart rate. That is our next step." |

Weakness case worth showing: **SYN-0019** has an unlogged meal. The alert fires only once glucose is already rising (14:50), 45 min before it exceeds 180 mg/dL. Full video script and shot list (not recorded yet): [docs/VIDEO_SCRIPT.md](docs/VIDEO_SCRIPT.md).

## Results at a glance

Three things are reported separately and must not be compared with each other.

### 1 · GlucoTwin on its synthetic benchmark (frozen served models)

12 held-out synthetic test patients × 14 days (patient split 36 / 12 / 12). Brackets are patient-level bootstrap 95% CIs.

| Glucose RMSE (mg/dL) | 30 min | 60 min | 120 min |
|---|---|---|---|
| Persistence (last reading) | 18.65 [16.44–21.08] | 31.42 | 46.58 |
| Ridge regression | 11.21 | 17.04 | 27.92 |
| **GlucoTwin (gradient boosting, served)** | **10.40** [9.81–11.01] | 17.21 | **25.90** [23.19–29.06] |

| Excursion warning (served logistic regression) | GlucoTwin | Trend-rule baseline |
|---|---|---|
| AUROC (40,789 test readings, 14.6% positive) | **0.884** [0.839–0.923] | 0.655 [0.583–0.736] |
| Onsets with an alert in the preceding 2 h | **272 / 298** (91.3%) | 298 / 298 |
| False-alert episodes over 168 patient-days | **229** (1.36 / day) | 1,055 (6.28 / day) |

Sources: [`reports/evaluation_report.json`](reports/evaluation_report.json) and [`reports/audit_report.json`](reports/audit_report.json). These are simulator results, not evidence about real patients. Full tables are in [§8](#8-evaluation-results).

### 2 · Real-data research: ShanghaiT2DM glucose-history models

**Evaluated:** persistence plus two models trained here on real CGM glucose history only (ridge and gradient boosting). **Not evaluated:** the full GlucoTwin model.

The cohort is 100 adults with type 2 diabetes (FreeStyle Libre, 15-min readings; 112,462 readings). The split is fixed per patient before windowing: 60 train / 20 validation / 20 test. Results are scored once on the **20 held-out test patients** (about 22,500 forecasts per horizon). RMSE is in mg/dL, with 95% patient-bootstrap CIs.

| Horizon | Persistence (baseline) | Ridge (glucose history) | Gradient boosting (glucose history) |
|---|---|---|---|
| 30 min | 16.10 [14.63–17.64] | 12.63 [11.78–13.51] | **12.32** [11.44–13.21] |
| 60 min | 26.94 [24.13–29.90] | 23.18 [21.45–25.05] | **22.39** [20.80–24.05] |
| 120 min | 40.79 [35.70–46.17] | 35.32 [31.64–39.27] | **33.62** [30.46–36.88] |

Gradient boosting has lower RMSE than persistence by 3.78, 4.55 and 7.16 mg/dL (paired 95% CIs [−4.72, −2.85], [−6.14, −2.93] and [−10.10, −4.19]). It beats persistence for 20/20, 19/20 and 15/20 test patients. Leakage checks found 0 patients and 0 sessions in more than one split. Re-running the analysis in a clean environment reproduced every metric.

<img src="reports/real_data/shanghai_t2dm/public/rmse_by_horizon.svg" alt="Bar chart of held-out test RMSE with 95% confidence intervals at 30, 60 and 120 minutes for persistence, ridge and gradient boosting trained on ShanghaiT2DM glucose history" width="100%">

Aggregate results: [public/SUMMARY.md](reports/real_data/shanghai_t2dm/public/SUMMARY.md) · [summary.json](reports/real_data/shanghai_t2dm/public/summary.json). Protocol and independent review: [ShanghaiT2DM experiment](docs/research/SHANGHAI_T2DM_EXPERIMENT.md).

Data: ShanghaiT2DM, from "diabetes_datasets.zip" version 5 by Qinpei Zhao, Jinhao Zhu, Congrong Wang and Weixiong Rao (figshare, 2022), [doi:10.6084/m9.figshare.21600933.v5](https://doi.org/10.6084/m9.figshare.21600933.v5), licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Descriptor: Zhao Q. et al., "Chinese diabetes datasets for data-driven machine learning", *Scientific Data* (2023), [doi:10.1038/s41597-023-01940-7](https://doi.org/10.1038/s41597-023-01940-7). Changes: only the Shanghai_T2DM CGM readings were used; they were cleaned, split into segments at gaps longer than 45 min and turned into forecasting windows. Only aggregate derived results are shown; no raw data are redistributed. The dataset authors have not reviewed or endorsed this work.

### 3 · Full GlucoTwin model on real patients: not yet evaluated

ShanghaiT2DM records food as free text, not carbohydrate grams, and has no steps or heart rate. Ten of GlucoTwin's 33 inputs would have to be invented, so we did not run it. Its sampling is also 15 min rather than GlucoTwin's 5 min. A real-data evaluation needs a dataset with logged carbohydrates and activity.

### 4 · Twin-validity research against simulator ground truth

A pre-registered analysis ([protocol](experiments/twin_validity/protocol.json), [write-up](docs/research/TWIN_VALIDITY.md), [aggregates](reports/research/twin_validity.json)) replays every What-If against the **true** response of the same simulated patient: identical hidden physiology, plus exactly that meal.

| Held-out test patients (12), 1,776 eligible preset-meal scenarios | +30 min | +60 min | +120 min |
|---|---|---|---|
| Mean true meal effect (mg/dL) | 8.7 | 35.8 | 49.0 |
| What-If error, MAE (mg/dL) | 3.9 | 11.1 | 29.0 |
| Cohort-average meal curve, MAE (mg/dL) | 2.3 | 9.3 | 12.8 |
| What-If − baseline [95% CI] | +1.6 [0.3, 2.8] | +1.9 [−1.7, 5.5] | **+16.1 [8.9, 23.0]** |

**Negative result, reported as measured:** a static cohort-average meal curve beats the What-If at +30 and +120 min and ties at +60 min. The What-If underestimates late meal effects (bias −28.9 mg/dL at +120 min). For example, for 35 g at the 07:55 demo moment it shows +10.7 mg/dL at +120 min, while the simulator's true effect is +65.4. Treat the What-If as a comparison of model associations, not a meal-effect estimate. Section A2 above shows the learned carb sensitivity does recover each simulated patient's gain; the trajectory model does not yet turn it into the right response shape.

**Post-hoc addendum** ([write-up](docs/research/TWIN_VALIDITY.md#addendum-v2-2026-10-23-post-hoc-and-exploratory), [aggregates](reports/research/twin_and_whatif_validation.json); synthetic only, 95% patient-bootstrap CIs):

- **Larger meals.** Across 20–120 g the negative result holds and grows with meal size: at +120 min the What-If MAE is 45.3 vs 20.8 for the cohort average (+24.5 [13.4, 34.8]).
- **Where the problem lies (exploratory, v2).** A post-hoc estimator, *grams × learned sensitivity × a response curve learned from observed CGM*, scored MAE 8.5 vs 16.8 for the cohort average at +120 min, but it was worse at +30 min.

**Pre-specified test of the personalised curve** ([addendum v3](docs/research/TWIN_VALIDITY.md#addendum-v3-2026-10-23-train-fitted-validation-selected-personalised-curve), [protocol](experiments/twin_validity/protocol_addendum_v3.json)):

- **How it was fitted.** The shape is fitted on the 36 training patients' observed CGM. One of four candidates (median or mean shape, with or without a per-horizon scale) is selected on the 12 validation patients. Each patient's sensitivity uses only meals completed before the forecast moment. The 12 test patients were scored once, on 2,953 scenarios with paired simulator ground truth and 1,000-sample paired patient-bootstrap 95% CIs.
- **Selected candidate.** The calibrated median shape, with validation MAE 5.43 vs 8.59 for v2's uncalibrated estimator. With a per-horizon scale, the median and mean shapes give identical predictions, so the tie went to the first in the listed order.

| Test, all meal sizes | +30 min | +60 min | +120 min |
|---|---|---|---|
| Personalised curve, MAE / RMSE (mg/dL) | **1.8** / 2.6 | **5.3** / 7.8 | **5.9** / 9.0 |
| Cohort-average curve (train only), MAE / RMSE | 3.1 / 4.1 | 12.5 / 16.1 | 16.8 / 22.5 |
| Served What-If, MAE / RMSE | 5.4 / 7.5 | 17.2 / 24.5 | 37.3 / 45.4 |
| Curve − cohort, MAE [95% CI] | −1.4 [−2.6, −0.2] | −7.2 [−11.4, −3.0] | **−10.9 [−15.4, −6.2]** |
| Curve − What-If, MAE [95% CI] | −3.7 [−4.9, −2.7] | −12.0 [−15.1, −9.2] | **−31.4 [−38.5, −25.3]** |
| Direction accuracy: curve / cohort / What-If | 100% / 100% / 95.9% | 100% / 100% / 99.5% | 100% / 100% / 90.9% |

- **On the 20–120 g subset behind "What-If 45.3".** At +120 min the curve scores 7.3 and the cohort average 20.8 (−13.5 [−19.4, −7.6]).
- **What this does and does not show.** The learned per-patient sensitivity carries the right information, and the served trajectory model is the bottleneck. Direction accuracy is uninformative because every true change is positive.
- **Caveats.** The simulator's near-linear, per-patient-gain meal response is exactly the structure this estimator assumes, so these errors are a best case. This is not real-data evidence, and the curve is **not served**: the What-If table still shows the frozen model's numbers.

## How personalisation works

Each patient has one learned parameter: carb sensitivity *s*, the glucose rise in mg/dL per gram of carbohydrate.

| Step | Rule (code: `carb_sensitivity_prior` and `personal_carb_sensitivity` in `features.py`) |
|---|---|
| Prior from the health record | *s₀* = clip(1.40 + 0.10 · (HbA1c − 7), 0.4, 3.0) |
| Evidence | Each eligible logged meal gives *r* = (max CGM in the next 120 min − pre-meal CGM) / carbs. A meal is eligible if it is ≥ 10 g, has no overlapping meal, a fresh pre-meal reading and ≥ 50% CGM coverage. |
| Update | *s* = (3 · *s₀* + Σ*r*) / (3 + *n*): shrinkage towards the prior with 3 pseudo-meals of weight, not a full Bayesian posterior |
| Use | Model features `carb_sensitivity` and expected meal rise = *s* × carbs on board |
| Example (SYN-0039) | *s₀* = 1.31 → *s* = 1.698 after 20 meals → 1.666 once the 120-min window of the 08:53 breakfast closes (10:55) |

The update only uses meal responses that are complete at the current replay time.

**How confident is the estimate?** The state panel shows a confidence line. For SYN-0039 at 07:55 it reads "Confidence: 87% from 20 observed meals; ± 0.16 sampling error (meal-to-meal SD 0.81)". It contains:

- the share of the estimate that comes from the patient's own meals, *n* / (3 + *n*);
- the SD of their observed meal responses;
- a sampling standard error, SD · √*n* / (3 + *n*). This treats the prior as fixed. It is **not** a Bayesian posterior SD.

These values are descriptive only (`glucotwin/twin/personal_uncertainty.py`) and are never used by a forecast.

**What a pre-registered experiment shows (synthetic cohort only; [details](docs/research/TWIN_VALIDITY.md)):**
- **The model uses it.** On the 12 test patients, replacing the learned sensitivity with the prior raises RMSE by 0.52 mg/dL at +30 min (95% CI 0.12–0.96) and 0.58 at +60 min (0.09–1.08). At +90/120 min and for event AUROC the change is within noise.
- **It matters most after meals.** In test rows with ≥ 10 g logged in the previous hour, the prior-only arm's +60-min RMSE is 2.44 mg/dL higher (20.52 vs 22.96; 95% CI 0.81–3.85). This is post-hoc ([addendum](docs/research/TWIN_VALIDITY.md#addendum-v2-2026-10-23-post-hoc-and-exploratory)); at +120 min the difference (+1.04) is borderline.
- **It recovers the simulator's hidden per-patient meal gain.** Correlation with the latent gain rises from r = 0.62 (prior only) to 0.95 after 3 days and 0.98–0.99 after 7–14 days. Mean absolute error falls less, from 0.243 to 0.171 mg/dL per g by day 14, because the observed estimate runs about 10% low (median ratio to the latent gain 0.90).

These are simulator results, not evidence about real patients.

## Research and architecture

| Document | What it covers |
|---|---|
| [Architecture PDF](docs/submission/GlucoTwin_Architecture.pdf) · [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Layers, data flow and contracts |
| [Presentation PDF](docs/submission/GlucoTwin_Presentation.pdf) | Submission deck |
| [ML plan](docs/ML_PLAN.md) · [model comparison](docs/MODEL_COMPARISON.md) · [independent audit](docs/AUDIT_WAVE2.md) | Validation protocol, model selection, bootstrap CIs, ablations |
| [ShanghaiT2DM experiment](docs/research/SHANGHAI_T2DM_EXPERIMENT.md) | Real-data protocol, results and independent review |
| [Counterfactual audit](reports/counterfactual_audit.json) · [§11](#11-counterfactual-simulation-and-limitations) | What-If comparisons over 2,934 scenarios |
| [API and data contracts](docs/API_CONTRACTS.md) | Schemas and event definition |

Team: **team mono**, Amrita Vishwa Vidyapeetham, Chennai (Mohnish Shanmugavadivel).

## Limitations and intended use

GlucoTwin is an educational research prototype. It is **not a medical device**, has **not been clinically validated**, and gives no diagnoses, alerts for real care, or treatment or dosing advice.

- **Synthetic benchmark.** The dashboard and the headline GlucoTwin metrics use simulated patients. A simulator may be easier to predict than real physiology, and the test cohort has 12 patients.
- **Real-data research is separate.** The ShanghaiT2DM results are for glucose-history-only models trained on that dataset, with 20 test patients from one region and one sensor type. They are not comparable with the synthetic benchmark. Retrospective accuracy is not clinical utility.
- **No real-data validation of the full twin.** The frozen GlucoTwin model has not been evaluated on any real patients.
- **What-If results are model associations, not physiology.** They are not a prediction of how a real person would respond. Meals under 30 g are flagged as unreliable ([§11](#11-counterfactual-simulation-and-limitations)).
- **Support tags are diagnostics.** *No training analogue* flags unusual inputs; it is not a guaranteed out-of-distribution detector, and "within support" does not make a forecast correct.
- **Personalisation is shown only in simulation.** On the synthetic cohort it measurably helps +30/60 min forecasts and recovers each patient's hidden meal gain ([research](docs/research/TWIN_VALIDITY.md)). This has not been tested on real patients.
- **What-If underestimates late meal effects.** Against simulator ground truth it is less accurate than a cohort-average meal curve at +30 and +120 min (mean bias −28.9 mg/dL at +120 min).
- **The simulator under-represents hypoglycaemia.** 0.37% of its CGM readings are below 70 mg/dL (876 / 238,103; 19 below 54), against a published comparator of 2.4% (docs/AUDIT_WAVE2.md F-18). The dashboard's *low-glucose watch* only reports that the 80% forecast lower bound is below 70 mg/dL. It is **not a probability** and not a validated hypoglycaemia predictor: on synthetic patients a low followed within 2 h at 33.5% of the moments it showed (test, 3,178 / 9,495) and 9.5% (validation, 208 / 2,186).
- **FHIR export is an interoperability prototype.** Its structure was checked against FHIR R4 4.0.1 model classes. It is not certified, not profiled against ABDM/NRCeS guides and not a compliance claim.
- **Other gaps.** Indian meal presets use approximate, editable carb values. There is no real wearable integration and no sleep data. Accessibility and keyboard testing have not been done. On phones the What-If table scrolls sideways; a swipe cue above it says so.

**Next research steps:**
- Evaluate the full twin on a governed real dataset with logged carbohydrates and activity.
- Repeat the personalisation ablation on real data with logged carbohydrates.
- Replace associational What-If with an intervention-capable model whose meal response has physiological timing, and re-test it against simulator ground truth with the same protocol.
- Carry out prospective validation before any clinical claim.

## Technical reference

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
- [17. Future work](#17-future-work)
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

The dashboard screenshot is at the [top of this README](#glucotwin--a-living-glucose-digital-twin-for-type-2-diabetes).

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

**Why India.** The ICMR-INDIAB national survey estimated that 101 million people in India had diabetes in 2021 (all types; 11.4% weighted prevalence), with a further 136 million living with prediabetes ([Anjana et al., *Lancet Diabetes Endocrinol* 2023;11(7):474–489](https://doi.org/10.1016/S2213-8587(23)00119-5)). GlucoTwin's design choices follow from that setting, without claiming compliance with any of them:

- Indian meal What-If presets with approximate, editable carbohydrate amounts.
- A FHIR R4 export, because India's national guide for ABDM health records ([NRCeS FHIR Implementation Guide for ABDM](https://nrces.in/ndhm/fhir/r4/)) is built on FHIR R4. GlucoTwin is **not** profiled against or certified for that guide.
- Synthetic data only. Real deployment would fall under the [Digital Personal Data Protection Act, 2023](https://www.indiacode.nic.in/handle/123456789/22037) (Act No. 22 of 2023), which this prototype does not address.

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

### 4.7 FHIR R4 export (interoperability prototype)

`GET /api/patients/{id}/fhir?hours=6` returns a deterministic FHIR R4 (4.0.1) `collection` Bundle of the synthetic patient. The dashboard shows it in a collapsible *FHIR R4 record (interoperability prototype)* panel with Download and Copy JSON buttons. Contents:

- the Patient (identifier in GlucoTwin's own namespace holding the synthetic `SYN-####` ID, never an ABHA-format number; name, gender; no invented birth date);
- Conditions coded in SNOMED CT (44054006, 59621000, 370992007);
- MedicationStatements coded in RxNorm (metformin 6809, glimepiride 25789, sitagliptin 593411, insulin glargine 274783, ramipril 35296, atorvastatin 83367);
- lab Observations: HbA1c LOINC 4548-4 and fasting glucose 1558-6. eGFR and LDL carry text only. The often-quoted eGFR code 33914-3 is marked *DISCOURAGED* on loinc.org and is specific to the MDRD formula, while the synthetic eGFR has no stated method, so a method-specific code would be a false claim;
- CGM Observations (LOINC 99504-3, UCUM mg/dL) from the last *hours* the twin has received. It never includes future replay data;
- one RiskAssessment for the twin's latest forecast. It holds the 2-hour excursion probability as `probabilityDecimal` (model output, synthetic data, not clinically calibrated). When the 80% lower bound falls below 70 mg/dL, it adds a qualitative *low-glucose watch* prediction with **no** probability field.

Every resource is tagged synthetic. Structure is checked with `scripts/validate_fhir_export.py` (fhir.resources 6.4.0, R4 4.0.1 model classes, run in a separate environment); codes and determinism are checked in `tests/test_fhir_export.py`. This is not certified and not profiled against ABDM/NRCeS implementation guides.

### 4.8 Low-glucose watch (lower-bound indicator)

When any 80% forecast lower bound at +30–120 min is below 70 mg/dL, the risk card says so, gives the lowest bound, and lists record medications that can cause hypoglycaemia (sulfonylurea, insulin). It is labelled as the edge of a prediction interval, **not a probability**. The What-If table applies the same rule to each scenario forecast in a *Low watch* column (for example "<70 from +90m · SU/insulin"). Its measured behaviour on synthetic patients, and the simulator's low rate of hypoglycaemia (0.37% of CGM readings below 70 mg/dL), are in [docs/research/TWIN_VALIDITY.md](docs/research/TWIN_VALIDITY.md) (sections D and E).

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

For the supported environment, use Python 3.11+ and Node.js 22.6+ (the frontend tests use `node --experimental-strip-types`; CI uses Node 22). Consult the repository's lockfiles and configuration for exact dependency versions.

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

**All results in this section refer to synthetic patients. They are not clinical validation.** The simulator may be easier for a model to learn than real-world physiology, and the held-out cohort is limited. The separate real-data experiment (ShanghaiT2DM, glucose-history models only) is summarised in [Results at a glance](#results-at-a-glance).

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
- Node.js 22.6 or later (required by the frontend test runner's `--experimental-strip-types`; declared in `frontend/package.json` `engines`).
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
9. Enter a hypothetical meal in the scenario lab and inspect the resulting simulated forecast. The table's primary columns compare the meal with a zero-carb meal logged at the same time (isolating the carbs); the grey columns compare with no meal (see §11).
10. Compare scenarios and clear them when finished. Meals under 30 g are flagged as unreliable, and risk changes are greyed when the starting risk is above 95%.
11. Open the model-evaluation view to inspect the documented metrics.

### Reproducible demonstration scenarios

The README's existing demonstration notes identify the following deep links:

- `/?patient=SYN-0039&start=151.833` — documented as an example of an early warning before an excursion.
- `/?patient=SYN-0019&start=253.667`: a weakness case. Glucose rises with no logged meal, and the alert fires only once the rise has begun (14:50, 45 min before the first reading above 180 mg/dL). Earlier versions called this a "missed excursion"; that was an artefact of stepping in 1-hour jumps (corrected 2026-10-21, see [DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md) Scene 6).

Example links:

- [Early-warning scenario](http://localhost:8000/?patient=SYN-0039&start=151.833)
- [Unlogged-meal scenario](http://localhost:8000/?patient=SYN-0019&start=253.667)

These links work only where the GlucoTwin application is running. Recheck the exact readings and replay behaviour before using the scenarios in a recorded demonstration.

## 11. Counterfactual simulation and limitations

The what-if meal simulation operates on a copy of the available observation history. It does not ingest the hypothetical meal into the original patient record, change the original twin history or make scenarios affect one another.

The interface distinguishes simulated outputs from observed and forecast values.

**Ground-truth check (2026-10-23):** against paired simulator runs, the What-If is less accurate than a cohort-average meal curve at +30 and +120 min, and underestimates late effects. See [Results §4](#4--twin-validity-research-against-simulator-ground-truth).

### What the comparison means (backlog B-22)

Each what-if runs the **same served forecasting models** three times at the current replay time. The physiological simulator is not involved:

| Leg | History used | Role |
|---|---|---|
| Baseline | Observed history, no hypothetical meal | Equals the live forecast |
| Reference | Plus a **zero-carb meal** logged now | Resets the model's "minutes since last meal" input without adding carbohydrate |
| Scenario | Plus the hypothetical meal of *X* g logged now | — |

- **Primary comparison: scenario − reference.** It isolates the carbohydrate content.
- **Secondary comparison: scenario − baseline** (grey in the dashboard). It also contains the models' **learned meal-timing expectation**: after a long gap since the last logged meal, the models have learned that a meal, and an excursion, often follows. Logging any meal removes that anticipated meal. At the 07:55 demo point a zero-carb meal alone lowers the risk from 22% to 7%.

Both comparisons are **learned associations of models trained on synthetic data, not causal physiological effects**. Do not interpret them as how a real person would respond to a meal.

**Why this changed.** B-22 was previously described as a "simulator artifact" caused by meal-response window collisions. Neither part held up:
- The what-if uses the ML models, not the simulator.
- The hypothetical meal never changes the learned carb sensitivity.
- The originally recorded case (−12.0 vs +41.1 mg/dL) did not reproduce.

The negative changes came from the reset of "minutes since last meal". [`scripts/counterfactual_audit.py`](scripts/counterfactual_audit.py) writes [`reports/counterfactual_audit.json`](reports/counterfactual_audit.json). It covers 12 held-out test patients × 326 replay points × 9 meal sizes (2,934 scenarios) and found 0 feature-vector violations.

Share of scenarios with a materially negative change:

| Meal | vs no meal: Δ+60 < −2 mg/dL | vs no meal: Δrisk < −0.01 | vs zero-carb: Δ+60 < −2 mg/dL | vs zero-carb: Δrisk < −0.01 |
|---|---|---|---|---|
| 5 g | 15.3% | 29.8% | 1.8% | 0% |
| 20 g | 9.8% | 9.5% | 0.6% | 0% |
| 30 g | 4.0% | 4.3% | 0% | 0% |
| 60 g | 2.8% | 0.6% | 0% | 0% |
| 120 g | 0.9% | 0% | 0% | 0% |

**Qualifiers shown in the dashboard and API:**
- **Meals under 30 g are flagged as unreliable.** Only 12.9% of training meals are below 30 g, the median small-meal effect is 0.0 mg/dL for 5–10 g, and up to 5.8% of 20 g scenarios still show a materially negative +120-min change.
- **Risk changes are greyed when the starting risk is above 95%.** The risk cannot rise meaningfully from there.

**Remaining limitations:**
- **The reference is outside the training data.** No training meal is zero-carb; the smallest is 6 g. The reference row is internally consistent (only the meal clock differs from the baseline), but it is not something the models were trained on.
- **A 1 g meal is not an exact substitute.** The audit shows it differs from the zero-carb reference by up to 4.7 mg/dL and 0.021 in risk.
- **The reference cannot fix the shape across meal sizes.** It is the same for every meal size. +60-min changes increase with meal size (2 mg/dL tolerance) at 294 of 326 points, and risk changes at 326 of 326.

The forecasting models, trained artefacts and reported evaluation metrics are unchanged by this comparison change.

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
- Frontend formatter tests (tooltip, scenario table, API errors).
- TypeScript checks.
- Vite production build.

### Verification commands

| Command | What it checks |
|---|---|
| `make check` | Ruff on `src`, `tests` and `scripts`; pytest; TypeScript + Vite production build; frontend unit tests |
| `.venv/bin/glucotwin train` | Regenerates the cohort, models and `reports/evaluation_report.json` deterministically (seed 20261017) |
| `.venv/bin/glucotwin audit` | Regenerates `reports/audit_report.json` (bootstrap CIs, robustness) |
| `.venv/bin/python scripts/counterfactual_audit.py` | Regenerates `reports/counterfactual_audit.json` (what-if comparisons, B-22; about 15 min) |

GitHub Actions (`.github/workflows/ci.yml`) runs the same lint, Python test, build and frontend-test steps on every push and pull request.

**Results recorded on 2026-10-23 for commit a6c1d91** (the snapshot commit then adds only the re-recorded snapshot, this README section and the rebuilt deck):
- `make check` exit 0:
  - Ruff passed;
  - 151 Python tests passed (1 third-party deprecation warning from the FastAPI/Starlette test client). Two Shanghai loader tests skip unless `requirements-realdata.lock` is installed; with it installed, all 151 ran;
  - the TypeScript check and production build succeeded (Vite reports its standard large-chunk size warning);
  - 34/34 frontend tests passed, 0 skipped.
- `scripts/export_static_demo.py` exit 0 with its built-in faithfulness checks; `npm run build:static` exit 0. Every frame, forecast and What-If is identical to the previous snapshot. The only additions are the descriptive confidence fields and the FHIR RiskAssessment (volatile IDs and the model-version label excluded).
- `scripts/twin_validity_analysis.py` exit 0, with all three self-checks passing. `scripts/validate_twin_and_whatif.py` exit 0 (1,005 s), with exact simulator reconstruction and v1 eligibility reproduced (1,776 / 2,304) ([write-up](docs/research/TWIN_VALIDITY.md)).
- `scripts/validate_fhir_export.py` (fhir.resources 6.4.0, FHIR R4 4.0.1): OK for both recorded exports (82 resources each, including a RiskAssessment) and for a SYN-0019 export at 16:45 that contains the low-glucose-watch prediction (81 resources).
- Reproducibility: rebuilding the bundle with `run_pipeline` matched `reports/evaluation_report.json` apart from `generated_at` and `model_version`.

Check the latest GitHub Actions run for the submitted commit before relying on these results.

**Browser checks:**
- On 2026-10-21, the script `docs/qa/browser_smoke.mjs` ran in headless Chromium at 1440 px. It passed 14/14 checks against the live app (`make serve` + `npm run preview`) and 14/14 against the static snapshot served from a sub-path, with no console errors or failed requests. The checks covered the banner, replay, the meal preset, recorded and unrecorded what-ifs, the training-support tag, stepping, the end of the replay and the evaluation tab.
- On 2026-10-22, the same script passed 14/14 again against the static snapshot served locally under `/digital-twin-healthcare-agent/`, the sub-path a GitHub Pages project site would use. This was a local rehearsal, not a public deployment.
- On 2026-10-22, a 390 px phone check (mobile emulation) covered 07:55, a preset What-If, 08:55 and the evaluation tab. It found the meal-preset dropdown widening the page to 443 px, fixed with one CSS rule in `frontend/src/styles.css`. After the fix all four views fit 390 px, with no console errors. On phones the What-If table scrolls sideways; a swipe cue was added on 2026-10-23.
- On 2026-10-23, against the rebuilt static snapshot served locally under `/digital-twin-healthcare-agent/`:
  - `docs/qa/browser_smoke.mjs` passed 14/14;
  - `docs/qa/browser_new_features.mjs` passed 11/11 (390 px swipe cue and no page overflow, FHIR panel, presets on the 15-min grid vs an off-grid moment, and the low-glucose note for SYN-0019 at 16:45).
  - This run found the open FHIR panel widening a 390 px page to 748 px; one CSS rule fixed it before the final run.
- Later on 2026-10-23, against the snapshot recorded from a6c1d91 and served locally under `/digital-twin-healthcare-agent/`:
  - `browser_smoke.mjs` passed 14/14;
  - `browser_new_features.mjs` passed 15/15. Four checks were new: banner headline and provenance, the personalisation confidence line, the What-If *Low watch* column, and the FHIR RiskAssessment (probability for the excursion only).
  - There were no console errors or failed requests.
- Accessibility and keyboard-interaction testing have not been done.

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
| Demo video | **Not recorded yet; no link.** The rules state both "minimum 20 minutes" and "15–20 minutes", so the length must be confirmed with the organisers. Script and shot list with two cuts (18:30 and 23:00): [docs/VIDEO_SCRIPT.md](docs/VIDEO_SCRIPT.md). |
| Real-data research results (aggregate only) | [public/SUMMARY.md](reports/real_data/shanghai_t2dm/public/SUMMARY.md) · protocol: [docs/research/SHANGHAI_T2DM_EXPERIMENT.md](docs/research/SHANGHAI_T2DM_EXPERIMENT.md) |
| Static demo (recorded snapshot) | Build instructions: [docs/STATIC_DEMO.md](docs/STATIC_DEMO.md). Not published. |
| Open-source licence | MIT, [`LICENSE`](LICENSE). See §16 for the copyright line. |


## 15. Team and institution

| Field | Details |
|---|---|
| Team name | team mono |
| Institution | Amrita Vishwa Vidyapeetham, Chennai |
| Team size | 1 |
| Team member | Mohnish Shanmugavadivel |
| Role | Solo student developer |
| Team leader contact | Provided to the organisers on the Unstop platform (not published here) |

## 16. Open-source licence

The repository contains an MIT licence file at `LICENSE`.

Copyright (c) 2026 Mohnish Shanmugavadivel, under the MIT licence terms in `LICENSE`.

## 17. Future work

Current limitations are collected in one place: [Limitations and intended use](#limitations-and-intended-use).

- Evaluate the full twin on an appropriately governed real-world dataset that records carbohydrate grams and activity. ShanghaiT2DM does not, so only glucose-history models were evaluated ([Results at a glance](#results-at-a-glance)).
- Establish external and prospective validation before making clinical claims.
- Isolate whether personalised carb sensitivity reduces forecast error, with a leakage-free sequential evaluation.
- Replace associational what-if comparisons with a model designed for interventions (for example, per-patient mechanistic fitting), then validate it.
- Complete accessibility and keyboard-interaction testing.
- Investigate additional sensor streams only when suitable data and validated models are available.

## 18. Submission compliance checklist

Status of the official submission items (rules in [COMPETITION_COMPLIANCE.md](docs/COMPETITION_COMPLIANCE.md)). "Unverified" means it cannot be confirmed from this repository.

| Requirement | Status |
|---|---|
| Public GitHub repository | Done (public) |
| README: team, institution, title, problem, use case, tech stack, ML details | Done |
| Architecture diagram (PDF) | Done: [docs/submission/GlucoTwin_Architecture.pdf](docs/submission/GlucoTwin_Architecture.pdf) |
| Presentation (PDF) | Done: [docs/submission/GlucoTwin_Presentation.pdf](docs/submission/GlucoTwin_Presentation.pdf) |
| Open-source licence | Done: MIT (`LICENSE`), copyright Mohnish Shanmugavadivel (§16) |
| Demo video (rules say both "minimum 20 minutes" and "15–20 minutes"; confirm with the organisers) | **Not done.** No video and no link yet. Script in [docs/VIDEO_SCRIPT.md](docs/VIDEO_SCRIPT.md). |
| Submission on the Unstop platform by the team leader | **Unverified.** It cannot be confirmed from this repository. |
