# ShanghaiT2DM glucose-history forecasting — aggregate results (2026-10-22)

**Scope.** These are models trained here on ShanghaiT2DM glucose history only (persistence, ridge, gradient boosting). They are NOT the GlucoTwin model: the full GlucoTwin model was not evaluated on ShanghaiT2DM because 10 of its 33 inputs (meal carbohydrate grams, steps, heart rate) are not recorded in the dataset. Research experiment on retrospective data; not clinical validation; not a medical device.

**Attribution.** Data: ShanghaiT2DM, from "diabetes_datasets.zip" version 5 by Qinpei Zhao, Jinhao Zhu, Congrong Wang and Weixiong Rao (figshare, 2022), https://doi.org/10.6084/m9.figshare.21600933.v5, licensed under CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/). Dataset descriptor: Zhao Q. et al., "Chinese diabetes datasets for data-driven machine learning", Scientific Data (2023), https://doi.org/10.1038/s41597-023-01940-7. Changes: only the Shanghai_T2DM CGM readings were used; they were cleaned, split into segments at gaps longer than 45 min and turned into forecasting windows, and only aggregate derived results are shown. No raw data are redistributed here. The dataset authors have not reviewed or endorsed this work.

## Cohort and split
- 109 session files from 100 patients (8 with more than one session); 0 excluded; 112,462 CGM readings used.
- Missing 15-min slots: 6 sessions affected (max share 0.0154); gaps > 45 min: 2 (segments split, nothing interpolated).
- 329 readings sit at 39.6 mg/dL, the lowest recorded value (likely the sensor floor); kept as recorded, so low glucose is censored.
- Patient-level split fixed before windowing: 60 train / 20 validation / 20 test patients; 0 patients and 0 sessions in more than one split.
- Full GlucoTwin model: not evaluated (10 of 33 inputs not recorded; confirmed against the headers of all 109 session files).

## Held-out test results (mg/dL)

| horizon | windows | patients | model | MAE | RMSE [95% CI] | RMSE − persistence [95% CI] | patients better than persistence |
|---|---|---|---|---|---|---|---|
| 30 min | 22,668 | 20 | persistence (last reading) | 10.99 | 16.10 [14.63, 17.64] | — | — |
| 30 min | 22,668 | 20 | ridge (glucose history only) | 9.05 | 12.63 [11.78, 13.51] | -3.47 [-4.27, -2.68] | 20/20 |
| 30 min | 22,668 | 20 | gradient boosting (glucose history only) | 8.73 | 12.32 [11.44, 13.21] | -3.78 [-4.72, -2.85] | 20/20 |
| 60 min | 22,624 | 20 | persistence (last reading) | 18.59 | 26.94 [24.13, 29.90] | — | — |
| 60 min | 22,624 | 20 | ridge (glucose history only) | 16.61 | 23.18 [21.45, 25.05] | -3.77 [-4.93, -2.58] | 17/20 |
| 60 min | 22,624 | 20 | gradient boosting (glucose history only) | 15.94 | 22.39 [20.80, 24.05] | -4.55 [-6.14, -2.93] | 19/20 |
| 120 min | 22,536 | 20 | persistence (last reading) | 29.01 | 40.79 [35.70, 46.17] | — | — |
| 120 min | 22,536 | 20 | ridge (glucose history only) | 26.15 | 35.32 [31.64, 39.27] | -5.47 [-7.20, -3.50] | 16/20 |
| 120 min | 22,536 | 20 | gradient boosting (glucose history only) | 24.68 | 33.62 [30.46, 36.88] | -7.16 [-10.10, -4.19] | 15/20 |

Uncertainty: 95% percentile intervals from 2,000 bootstrap resamples of test patients; pooled metrics weight patients by their number of windows (consecutive windows overlap and are correlated, which the patient-level resampling accounts for).

## Limitations
- 20 test patients from one cohort, one region and one sensor type (FreeStyle Libre, 15-min readings).
- Glucose history only: diet, insulin and medication fields were not used; no meal or activity information.
- Low readings are censored at the sensor floor; text values such as LO/HI were not present.
- Not comparable with GlucoTwin's synthetic benchmark (different sampling, inputs and population).
- Retrospective accuracy does not establish clinical utility or safety.
