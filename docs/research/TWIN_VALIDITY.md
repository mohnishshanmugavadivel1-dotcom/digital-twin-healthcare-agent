# Twin-validity research: personalisation and What-If against simulator ground truth

**Status:** research analysis on the **synthetic** cohort only (2026-10-23). The production engine, model weights, benchmark definitions and headline metrics are frozen; nothing here changes what the dashboard serves. Negative and null results are reported as measured.

| Item | Location |
|---|---|
| Pre-registered protocol (written before any result was computed) | [`experiments/twin_validity/protocol.json`](../../experiments/twin_validity/protocol.json) |
| Analysis script (about 11 min) | [`scripts/twin_validity_analysis.py`](../../scripts/twin_validity_analysis.py) |
| Raw aggregates | [`reports/research/twin_validity.json`](../../reports/research/twin_validity.json) |
| Paired-simulation helpers and their tests | `src/glucotwin/twin_validity_research.py`, `tests/test_twin_validity_research.py` (research only; not imported by the service) |

```bash
make setup && make train      # frozen bundle (deterministic, seed 20261017)
.venv/bin/python scripts/twin_validity_analysis.py
```

**Design.** Cohort of 60 patients × 14 days (seed 20261017), patient-level split 36 train / 12 validation / 12 test, and the frozen served models (HGB trajectory, logistic-regression events). Uncertainty comes from a patient-cluster bootstrap: 2000 resamples of the 12 test patients, seed 20261023, 95% percentile intervals.

The script checks itself before it reports anything:
- the reconstructed simulator reproduces the cohort's stored true glucose exactly;
- the served arm reproduces the committed headline metrics (RMSE 10.40 / 17.21 / 25.90; AUROC 0.884);
- the replay moments match the service (378/384; the other 6 fall in CGM gaps, and the ground truth always uses the service's own moment).

All three checks passed.

## A · Does the frozen model use personalisation? (inference-time ablation)

**Ablated arm:** `carb_sensitivity` is set to the patient's record-based prior, and `expected_meal_rise` to prior × carbs on board. Every other input, row and split is unchanged.

| Test metric (12 patients) | Served | Ablated | Ablated − served [95% CI] |
|---|---|---|---|
| RMSE +30 min (n = 47,105) | 10.40 | 10.92 | **+0.52 [0.12, 0.96]** |
| RMSE +60 min (n = 46,884) | 17.21 | 17.79 | **+0.58 [0.09, 1.08]** |
| RMSE +90 min (n = 46,705) | 22.86 | 23.81 | +0.95 [−0.06, 2.14] |
| RMSE +120 min (n = 46,560) | 25.90 | 26.76 | +0.86 [−0.20, 2.19] |
| Event AUROC (n = 40,789; 5,967 positive) | 0.884 | 0.877 | −0.007 [−0.019, 0.003] |

Replacing the learned sensitivity with the prior makes 30- and 60-min forecasts worse by about 0.5 mg/dL RMSE, with intervals that exclude zero. At 90 and 120 min and for event AUROC the intervals include zero. **Limitation:** this measures how much a model *trained with* the personalised inputs relies on them, not the value of a model retrained without them.

## A2 · Does the learned sensitivity recover the simulator's hidden one?

**Target:** the simulator's latent meal gain per patient. That is the mean peak rise in noiseless interstitial glucose within 120 min after adding exactly 40 g, divided by 40, from paired simulation at the eligible anchors.

**Estimate:** the engine's carb sensitivity at the end of each study day, computed with the served functions. Day 0 is the record-based prior.

Test patients (n = 12; latent range 0.85–2.23 mg/dL per g):

| End of day | Meals used (mean) | Pearson r [95% CI] | Spearman ρ | MAE (mg/dL per g) | Median estimate / latent |
|---|---|---|---|---|---|
| 0 (prior only) | 0 | 0.62 [0.29, 0.90] | 0.75 | 0.24 | 1.03 |
| 1 | 2.7 | 0.83 [0.68, 0.98] | 0.90 | 0.17 | 0.97 |
| 3 | 9.2 | 0.95 [0.89, 0.99] | 0.97 | 0.15 | 0.96 |
| 7 | 21.7 | 0.99 [0.96, 1.00] | 0.97 | 0.13 | 0.93 |
| 14 | 42.8 | 0.98 [0.94, 0.99] | 0.97 | 0.17 | 0.90 |

All 60 patients: r = 0.55 (day 0), 0.89 (day 7), 0.91 (day 14).

The online estimate tracks the hidden per-patient gain far better than the record-based prior within about 3 days of meals. **Limitations:**
- In this simulator the HbA1c-based prior already correlates with the gain.
- The engine measures the total observed rise per *logged* gram, so MAE includes logging error and background drift.
- From day 7 the estimate drifts slightly low (ratio 0.93 → 0.90).
- This is recovery in a simulator, not evidence about real people.

## B · What-If deltas against paired simulator ground truth (negative result)

**Scenarios:** 12 test patients × 32 replay moments (as in `scripts/counterfactual_audit.py`) × the 6 Indian-preset meal sizes (25/35/36/40/45/50 g), 2,304 in all. Exclusions:
- 348 because the latest CGM was above 180 mg/dL or missing;
- 0 because the forecast was withheld;
- 180 because the meal was outside training support (B-23).

That leaves **1,776 eligible** scenarios from 296 moments.

**Ground truth:** the same simulated patient with identical hidden parameters, schedule and stress draws, plus exactly *g* grams eaten at the moment. The difference is taken in noiseless interstitial glucose at +*h* min.

**Baseline:** for each meal size and horizon, the mean true delta over the 36 **training** patients at the same moments (863 training anchors). The same value is used for every test patient and moment.

| Horizon | Mean true Δ (range) | What-If primary (vs 0 g meal): MAE / bias / ρ | Secondary (vs no meal): MAE / bias / ρ | Cohort-average baseline: MAE / bias / ρ | MAE primary − baseline [95% CI] |
|---|---|---|---|---|---|
| +30 min | 8.7 (3.5–18.0) | 3.9 / −2.9 / 0.29 | 7.5 / +1.4 / 0.14 | 2.3 / +1.0 / 0.59 | **+1.55 [0.29, 2.83]** |
| +60 min | 35.8 (15.4–77.7) | 11.1 / −7.1 / 0.59 | 15.7 / +2.4 / 0.36 | 9.3 / +3.8 / 0.62 | +1.86 [−1.72, 5.53] |
| +120 min | 49.0 (18.2–111.6) | 29.0 / −28.9 / 0.62 | 22.2 / −13.6 / 0.32 | 12.8 / +4.9 / 0.59 | **+16.14 [8.92, 23.02]** |

Units are mg/dL. The 30-min horizon was pre-registered as secondary.

**Direction accuracy** (primary): 96.3% at +30 min, 99.9% at +60 min and 93.4% at +120 min. This is close to trivial here: every true delta is positive, and the baseline scores 100% by construction.

**Finding.** A static cohort-average meal response is **more accurate** than the What-If at +30 and +120 min. At +60 min the two cannot be distinguished. The What-If **underestimates the late meal effect**: at +120 min its mean bias is −28.9 mg/dL. Example at the demo moment (SYN-0039, 07:55, 35 g):

| | +30 | +60 | +90 | +120 min |
|---|---|---|---|---|
| What-If primary (dashboard) | +7.9 | +29.9 | +27.6 | +10.7 |
| Simulator truth | +9.1 | +40.9 | +62.6 | +65.4 (peak +66.4 at +109 min) |

The ground-truth scale is supported independently. The engine's carb sensitivity, measured from the simulated CGM alone, agrees with the paired-simulation gain (median ratio 0.90–1.03, section A2). The model's response, however, peaks around 60–90 min and fades by 120 min, while the simulator's keeps rising.

**What this does and does not mean:**
- It tests whether the What-If reflects the simulator's own meal physics under controlled conditions. It **does not** validate or refute real-world causal effects.
- The What-If's +120 min column should not be read as a meal-effect estimate.
- Next step: a model whose meal response is constrained to physiological timing, re-tested with this protocol.

## D · Low-glucose lower-bound rule (what the dashboard's "low-glucose watch" shows)

**Rule (fixed before analysis):** any served 80% lower bound at +30/60/90/120 min below 70 mg/dL. **Outcome:** any CGM reading below 70 mg/dL within the next 120 min.

| Split (12 patients each) | Fired / moments | Outcome base rate | PPV (true positives / fired) | Sensitivity |
|---|---|---|---|---|
| Validation | 2,186 / 47,679 (4.6%) | 0.8% | 9.5% (208 / 2,186) | 55% (208 / 378) |
| Test | 9,495 / 47,560 (20.0%) | 8.6% | 33.5% (3,178 / 9,495) | 78% (3,178 / 4,091) |

The served lower bound is `max(forecast − conformal half-width, 40)`. The half-width at +120 min is 29.85 mg/dL, so the rule fires whenever the +120 forecast is below about 100 mg/dL.

By record medication:
- **Sulfonylurea or basal insulin:** test 3,178 / 9,495 fired-and-followed; validation PPV 9.5%.
- **Neither:** no test outcomes at all (0 / 15,854 moments); validation 8 / 73.

This is a **lower edge of a prediction interval, not a probability of hypoglycaemia** and not a validated predictor. Its PPV differs threefold between splits of 12 patients, a sign of how few lows the simulator produces.

## E · Time below range in the simulator (missing limitation, now documented)

| Group (all 60 patients) | Readings | < 70 mg/dL | < 54 mg/dL |
|---|---|---|---|
| All | 238,103 | 876 (0.37%) | 19 |
| Sulfonylurea or basal insulin | 119,143 | 865 (0.73%) | 19 |
| Neither | 118,960 | 11 (0.01%) | 0 |

The repository's published comparator is 2.4% (docs/AUDIT_WAVE2.md F-18), so the simulator under-represents hypoglycaemia. Low-glucose results from this cohort should not be generalised.

## Addendum v2 (2026-10-23): post-hoc and exploratory

Protocol: [`experiments/twin_validity/protocol_addendum_v2.json`](../../experiments/twin_validity/protocol_addendum_v2.json). It was written after the v1 results above were known, so **everything in this section is post-hoc**.

- Script: `scripts/validate_twin_and_whatif.py` (EXIT 0, 1,005 s).
- Outputs: [`reports/research/twin_and_whatif_validation.json`](../../reports/research/twin_and_whatif_validation.json) and [TWIN_AND_WHATIF_VALIDATION.md](../../reports/research/TWIN_AND_WHATIF_VALIDATION.md).
- Model: identical data, seed and weights, rebuilt as `gt-0.1.0-s20261017-202610230821` after a sandbox reset. Its evaluation report matched the committed one apart from `generated_at` and the model-version label.
- Consistency check: the v1 preset grams give the same 1,776 / 2,304 eligible scenarios as v1.
- The simulator (`src/glucotwin/synth/generator.py`) is documented as an extended Bergman minimal model.

CIs are 95% from 1,000 paired patient-bootstrap resamples.

**A. Personalisation matters most just after meals.** These are test rows with at least 10 g logged in the previous 60 min.

| Horizon | Rows | RMSE with learned sensitivity | RMSE with prior only | Prior only minus learned [95% CI] |
|---|---|---|---|---|
| +60 min | 6,266 | 20.52 | 22.96 | +2.44 [+0.81, +3.85] |
| +120 min | 6,250 | 22.84 | 23.89 | +1.04 [−0.01, +2.37] |

- MAE at +60 min: +1.92 [+0.74, +3.20].
- At +60 min the effect is about 4× larger than over all rows (+0.58).
- At +120 min it is borderline: the CI touches 0.

**B. The served What-If across meal sizes (negative result, extended).** 1,473 eligible scenarios at 20/40/60/90/120 g on 12 test patients.

| Horizon | Mean true Δ | What-If MAE | Cohort-average MAE | Difference [95% CI] | Median AE difference [95% CI] |
|---|---|---|---|---|---|
| +30 min | 14.8 | 7.0 | 4.0 | +2.99 [+0.52, +5.43] | +1.78 [−0.34, +4.13] |
| +60 min | 61.1 | 23.1 | 15.8 | +7.38 [−0.31, +15.35] | +4.65 [−2.73, +11.90] |
| +120 min | 82.3 | 45.3 | 20.8 | +24.45 [+13.36, +34.80] | +21.51 [+8.62, +31.23] |

- The What-If's error grows with meal size. At +120 min its MAE is 25.0 at 20 g and 83.0 at 120 g, against 6.8 and 36.3 for the cohort average.
- Its bias is −45.3 mg/dL at +120 min: it underestimates large and late meal effects.
- Every true delta is positive, so direction accuracy (89.7% at +120 min) says nothing.

**C. Exploratory estimator, not served.** It is a personalised response curve built from **observed** CGM only:

- Shape c(h): from 1,494–1,506 isolated training-patient meals (depending on horizon), the median fraction of each meal's observed peak reached at +30/60/120 min (0.10 / 0.59 / 0.91).
- Scale: the patient's current learned sensitivity s.
- Estimate: grams × s × c(h).

| Horizon (2,953 scenarios, 10 meal sizes) | Personal curve | Same curve, cohort sensitivity | Served What-If | Cohort average fitted on simulator truth | Personal minus cohort average [95% CI] |
|---|---|---|---|---|---|
| +30 min | 5.5 | 4.8 | 5.4 | 3.1 | +2.32 [+0.54, +4.08] (worse) |
| +60 min | 10.7 | 10.5 | 17.2 | 12.5 | −1.72 [−6.82, +3.47] (tie) |
| +120 min | **8.5** | 14.6 | 37.3 | 16.8 | **−8.21 [−13.98, −2.89]** (better) |

**Interpretation, with caveats:**

- **The bottleneck is the trajectory model, not the personalised parameter.** Scaling a simple observed-data curve by the learned sensitivity beats a cohort average fitted on simulator truth at +120 min, and beats the same curve without personalisation (8.5 vs 14.6).
- **The result is favoured by the simulator.** Its meal effect is close to linear in grams (true +120-min effect 1.23–1.30 mg/dL per g across 20–120 g) and scales with a per-patient gain, which is the structure this estimator assumes. Real meals (fat, fibre, glycaemic index, insulin timing) would not be.
- **It loses at +30 min** and **ties at +60 min**.
- **It was designed after we saw that the served What-If underestimates late effects.** It is a candidate for a future pre-registered test, not a validated method, and it is not served.
