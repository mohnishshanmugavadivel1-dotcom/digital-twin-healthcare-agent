# Why removing the direct record features changes held-out AUROC (0.884 → 0.907) — and why we kept them

**Experiment:** `scripts/ablate_record_features.py` (deterministic, seed 20261017; run 2026-10-20 on `main`).
**Question:** the wave-2 audit reported that the event model discriminates *better* on held-out test patients
without the 10 direct `record`/EHR features (AUROC 0.884 → 0.907). Is that a real, selectable improvement —
and if so, which static feature causes it?

## Protocol (identical to `evaluation/pipeline.py`; no test-set tuning)

Patient-level split 36/12/12 (unchanged); `LogisticEventModel` (standardised logistic, C=0.5) fitted on train;
alert threshold chosen on **validation** (max F1); **test scored once per variant**; 1,000 patient-level bootstrap
resamples for the AUROC difference. Validation AUROC is reported alongside test because **model selection must
be validation-driven**.

## Results

| Variant | Val AUROC | Test AUROC | Test AUPRC | Test Brier | Thr. | Sens / Spec |
|---|---|---|---|---|---|---|
| With record features (served) | **0.8881** | 0.8840 | 0.6676 | 0.0815 | 0.35 | 0.665 / 0.902 |
| Without record features | 0.8866 | **0.9075** | **0.7014** | **0.0739** | 0.29 | 0.702 / 0.907 |
| Δ (with − without), patient bootstrap | – | −0.022 (95% CI **−0.053, −0.001**) | – | – | – | – |

Standardised logistic coefficients of the static block (with-record model, test fit):

| Feature | std. coef | | Feature | std. coef |
|---|---|---|---|---|
| fasting_glucose_mg_dl | **−3.70** | | hba1c_percent | +0.19 |
| age_years | −1.13 | | med_sulfonylurea | −0.12 |
| bmi | −0.56 | | med_dpp4_inhibitor | +0.09 |
| diabetes_duration_years | −0.54 | | med_basal_insulin | −0.05 |
| egfr | −0.26 | | med_biguanide | −0.00 |

## Interpretation

1. **The effect is real on test but NOT selectable on validation.** Validation slightly *prefers* the served
   (with-record) model (0.8881 vs 0.8866). Under our frozen protocol — choose on validation, touch test once —
   **dropping the record block is not a justified change**, so the served model is unchanged. Selecting it
   because the test column looks better would be test-set selection.
2. **Mechanism:** `fasting_glucose_mg_dl` is a noisy *snapshot* of each patient's baseline, carrying a huge
   negative standardised weight (−3.7) that opposes the dynamic evidence (recent glucose, 24 h control) which
   already encodes current control. On test patients this pushes the linear model away from the dynamic signal
   (test Brier and AUPRC also degrade with the block present). With only 12 validation patients the effect is
   within validation noise, which is why validation cannot detect it.
3. **The record still contributes through the fusion pathway that matters:** the EHR prior for personal carb
   sensitivity (`1.40 + 0.10·(HbA1c−7)`, `features.py::carb_sensitivity_prior`) and grouped context/explanations.
   The ablation concerns only the 10 direct linear features of the event model, not EHR fusion itself.
4. **Status:** this is a documented limitation with a recommended post-submission iteration: re-select the event
   feature set across multiple cohort seeds on validation, and if it holds, retire the direct block (keeping the
   prior pathway), regenerating all reports and deck numbers in the same change. Tracked as B-19 in
   `docs/BACKLOG.md`.

## Reproduce

```bash
.venv/bin/python scripts/ablate_record_features.py            # default cohort/seed
.venv/bin/python scripts/ablate_record_features.py --seed 7   # different cohort (robustness of the finding)
```

All patients are synthetic; every number above describes our simulator and is an upper bound. Not clinical validation.
