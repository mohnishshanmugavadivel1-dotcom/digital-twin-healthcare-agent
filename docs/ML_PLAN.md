# ML baseline and validation plan (Agent C)

> **Note (Historical Sprint Record):** This document is preserved as an engineering development log from earlier waves. For final release metrics (161 Python tests, 50 frontend tests, 83 browser checks, and validated twin-curve / real-data benchmarks), see the root [README.md](../README.md).

## Task definitions

| Task | Definition | Where |
|---|---|---|
| Event (primary) | P(onset of 3 or more consecutive CGM readings above 180 mg/dL within (t, t+120 min]), asked only when CGM(t) ≤ 180 | `labels.event_labels` |
| Trajectory | CGM at t+30, t+60, t+90 and t+120 minutes, predicted as a change from CGM(t) | `labels.trajectory_targets` |

Edge rules: a missing reading breaks a run; labels are NaN (excluded) if less than 50% of the future window is observed and no onset
was seen. This includes the end of each record, so the last 2 hours are never silently labelled negative. Rows where CGM(t) is above 180 are not
eligible for the event task.

## Features (33, all computed from data at or before t)

| Group | Features |
|---|---|
| Glucose level | current, mean and SD over 60 min, max and min over 180 min |
| Glucose trend | change over 15/30/60 min, 15-min acceleration (lag values interpolated over ≤ 3 missing readings, using only readings ≤ t) |
| 24 h control | mean over 24 h, fraction above 180 over 24 h |
| Meals | logged carbs in the last 30/60/120 min, carbs on board (3 h linear decay), minutes since meal, **personal carb sensitivity**, expected meal rise |
| Activity | steps over 30 and 60 min, HR over 30 min relative to the 24 h median |
| Time of day | sin and cos of patient-local minute of day |
| Record | age, BMI, HbA1c, FPG, duration, eGFR, sulfonylurea, basal insulin, metformin, DPP-4 inhibitor |

**Personal carb sensitivity (the twin's learned parameter).** For each logged meal of at least 10 g with no other meal in the following
120 minutes, the ratio is (peak CGM in (tm, tm+120] minus pre-meal CGM) / carbs. It becomes usable only at tm+120. The estimate is
`(prior·3 + Σ ratios) / (3 + n)`, a running mean shrunk towards an EHR prior of `1.40 + 0.10·(HbA1c − 7)` mg/dL per gram.
The prior constants were fitted on the **training split only** (mean training ratio 1.40, slope 0.10 per HbA1c point).

## Models

| Role | Model | Notes |
|---|---|---|
| Baseline | Persistence | Glucose stays constant |
| Baseline | Damped trend | 30-min slope, exponential damping with τ = 30 min |
| Baseline (event) | Trend rule | Logistic map of the damped-trend 2 h maximum against 180 |
| Candidate | Ridge (per horizon) | Median impute, standardise |
| Candidate | Logistic regression (event) | Standardised, C = 0.5; **served** for transparent grouped explanations |
| Candidate | HistGradientBoosting (regressor/classifier) | 300 iterations; trajectory model served when it wins on validation |

## Split and leakage safeguards

1. **Patient-level split** 60/20/20 (36/12/12 patients) from a seeded permutation. No patient appears in two splits (tested).
2. Features use observations at or before t, and labels use (t, t+120] (tested: truncating the future never changes past features; a
   mutation that leaked 30 minutes of future data was caught by two tests).
3. Hidden simulator parameters are never features (tested). The EHR is a *noisy* derivative of hidden physiology.
4. Imputers and scalers are fitted inside model pipelines on training data only.
5. Threshold (max F1), split-conformal interval widths and the served trajectory model are chosen on **validation**. Test is evaluated once.
6. The demo exposes only test patients; the service regenerates the training cohort from `bundle.cohort_params`.
7. Labels come from the *noisy CGM* (what a clinician sees), not the noiseless simulated glucose.

**Planned addition (B-08).** A within-patient chronological evaluation with a 120-minute embargo, to quantify personalisation
(first k days for adaptation, later days for evaluation).

## Metrics

* Trajectory: MAE, RMSE, MARD, Clarke error grid zone A and A+B (standard published boundaries), and 80% interval coverage.
* Event, at point level: AUROC, AUPRC (with prevalence), Brier score, sensitivity, specificity and PPV at the frozen threshold.
* Event, at event level: the fraction of excursion onsets with at least one alert in the 120 minutes before (only onsets that had an eligible
  prediction point), median lead time (earliest alert in the window, capped at 120 by definition), and false-alert episodes per
  patient-day (consecutive alerts no more than 10 minutes apart, all with label 0).

## Results of the actual run (seed 20261017, 60 patients × 14 days, 12 test patients)

Reproduce with `glucotwin train`; full numbers are in `reports/evaluation_report.json`. Two consecutive runs gave identical metrics.

| Trajectory (test) | RMSE 30 min | RMSE 60 | RMSE 90 | RMSE 120 | Clarke A at 120 |
|---|---|---|---|---|---|
| Persistence | 18.7 | 31.4 | 40.7 | 46.6 | 45.2% |
| Damped trend | 17.4 | 31.1 | 42.5 | 50.4 | 44.1% |
| Ridge | 11.2 | 17.0 | 23.6 | 27.9 | 66.8% |
| **HGB (served)** | **10.4** | 17.2 | **22.9** | **25.9** | **73.8%** |

The 80% conformal interval coverage on test is 0.78 / 0.76 / 0.78 / 0.80, close to nominal.

| Excursion onset ≤ 120 min (test, prevalence 14.6%) | AUROC | AUPRC | Brier | Sensitivity | Specificity | Onsets warned | Median lead | False alert episodes per day |
|---|---|---|---|---|---|---|---|---|
| Trend rule | 0.655 | 0.324 | – | 44% | 74% | 100%* | 60 min | 6.28 |
| **Logistic regression (served)** | 0.884 | 0.668 | 0.082 | 67% | 90% | 91% | 95 min | 1.36 |
| HGB | **0.936** | **0.756** | **0.069** | 78% | 90% | 96% | 120 min | 1.07 |

\*The trend rule's validation-optimal threshold was 0.05, so it alerts almost constantly. Its 100% onset coverage is paid for with
6.3 false-alert episodes per day. This is why the onset metric is always reported next to the false-alert rate.

**Interpretation.**
* Learned models beat the baselines by a wide margin on held-out patients. HGB is better than logistic regression for the event task
  (AUROC 0.936 vs 0.884). We currently serve logistic regression to get exact additive explanations. Backlog B-07 evaluates
  serving HGB with TreeSHAP group attributions instead.
* Prevalence differs across splits (train 24.6%, validation 27.2%, test 14.6%) because each split has only 12 patients.
  Confidence intervals by patient bootstrap are backlog item B-09.
* Absolute numbers are optimistic. See the feasibility report: the simulator is more predictable than real data.

## Wave-2 robustness audit (2026-10-17)

`glucotwin audit` (`src/glucotwin/evaluation/audit.py`) independently re-implements the protocol, verifies that it reproduces
`evaluation_report.json` exactly, and adds patient-bootstrap 95% CIs, a **sustained** warning metric (the alert must still be on at the last
eligible prediction before onset), ablations (no record / no HbA1c+FPG / no meal features), three extra cohort seeds, and a stress test with
harder observation realism (`Realism(meal_log_prob=0.6, carb_log_sigma=0.5, meal_log_delay_max_min=45, cgm_noise_sd=7.0)`).
Results and findings: [AUDIT_WAVE2.md](AUDIT_WAVE2.md). The served model and headline report are unchanged.
