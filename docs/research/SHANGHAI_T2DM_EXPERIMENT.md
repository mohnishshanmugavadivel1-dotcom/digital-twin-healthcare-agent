# ShanghaiT2DM real-CGM experiment — protocol and status

**Status (2026-10-22): RUN ON REAL DATA.** The official v5 archive arrived through the transfer repository
`mohnishshanmugavadivel1-dotcom/glucotwin-shanghai-data` (commit `ee4cb4c`; public when cloned). It was independently
verified before use: 3,738,354 bytes, md5 `4bfb61cfa506b48155fd9e841ee48e21`,
sha256 `59b5f5c4053a32bb6b7827844a0191597dc82228fe88ce332a189fdfc659c4cb`, `fetch_shanghai_t2dm.py` exit 0. The
pre-registered protocol then ran unchanged. Full results are in
`reports/real_data/shanghai_t2dm/REPORT_2026-10-22.md` and `results.json`; headline numbers are below.

### Real-data results (held-out test: 20 patients, scored once)

| horizon | test windows | persistence RMSE [95% CI] | ridge RMSE [95% CI] | gradient boosting RMSE [95% CI] |
|---|---|---|---|---|
| 30 min | 22,668 | 16.10 [14.63, 17.64] | 12.63 [11.78, 13.51] | 12.32 [11.44, 13.21] |
| 60 min | 22,624 | 26.94 [24.13, 29.90] | 23.18 [21.45, 25.05] | 22.39 [20.80, 24.05] |
| 120 min | 22,536 | 40.79 [35.70, 46.17] | 35.32 [31.64, 39.27] | 33.62 [30.46, 36.88] |

Values in mg/dL. CIs come from a 2,000-resample patient bootstrap. In every horizon the paired difference vs
persistence has a CI excluding 0 (see the report). The cohort is 100 patients and 109 sessions; 112,462 CGM
readings were kept and 0 sessions excluded. The split is 60/20/20 patients, and the leakage counters are 0, both
in the pipeline and in an independent re-check. A full rerun reproduced `results.json` exactly, apart from
`runtime_s`. The frozen production model was **not** evaluated (INCOMPATIBLE, confirmed against the real headers).
These numbers are not comparable with the synthetic benchmark and are not clinical validation.

Correction to the earlier version of this document: added readings and the device change **are** documented, in
`note.txt` inside the v5 archive (not in the paper or the Figshare description). The audit found exactly what it
describes: a 212-min gap and 13 empty CGM rows in the one session with a documented device change, which became separate segments.

Config hashes: the file sha256 `ecc71787…de6a5` is unchanged since registration. `results.json` stores
`config_sha256` `a8c0f3769ff1d3b01950f213bc3cab6dc109b9d5ce691119cd1a43ced2d0a0d2`, a hash of the canonical
(sorted-key) JSON of the same config.

Research experiment only. Not clinical validation; not a medical device.

## Dataset (from public metadata, verified 2026-10-22 via the Figshare API)

| | |
|---|---|
| Source | Figshare article 21600933 **version 5**, file 42966622 `diabetes_datasets.zip` |
| DOI | 10.6084/m9.figshare.21600933.v5 |
| Size / md5 | 3,738,354 bytes / `4bfb61cfa506b48155fd9e841ee48e21` |
| Licence | CC BY 4.0 |
| Citation | Zhao Q, Zhu J, Wang C, Rao W (2022). diabetes_datasets.zip. figshare. https://doi.org/10.6084/m9.figshare.21600933.v5 ; descriptor: Zhao et al., *Sci Data* 10, 2023, doi:10.1038/s41597-023-01940-7 |
| Excluded | older article 20444397 `data.zip` (md5 `ecadc819dd20aeb92d60ce41ceb16fd2`); versions are never combined |

Documented schema (descriptor paper; **checked against the files on 2026-10-22: it matches**. All 109 T2DM workbooks have Date and CGM columns, CGM in mg/dL (107 headers say so; in 2 the header has no unit and the unit was inferred from the values); 5 header variants, listed in `audit.json`): one Excel table per patient
recording period, named `<patientID>_<period>_<YYYYMMDD>`, in folder `Shanghai_T2DM` (T2DM IDs 2xxx); columns Date,
CGM (FreeStyle Libre H, every 15 min), CBG, blood ketone, dietary intake (weighed food, free text), insulin s.c./i.v.,
non-insulin agents, CSII bolus/basal; plus a `Shanghai_T2DM_Summary` sheet. The CGM unit is not stated. The paper's
own patient and period counts do not add up, so every count will be taken from the files. Neither the paper nor the
v5 description documents added readings or device-change gaps; they are documented in the archive's `note.txt` (see the status above). The pipeline detects and reports them empirically either way.

## Commands

Re-render the report from `results.json` without retraining: `.venv/bin/python scripts/shanghai_experiment.py report`.


```bash
# 1. once the archive is reachable (private transfer repo, shallow clone over github.com)
git clone --depth 1 https://github.com/<owner>/<transfer-repo> /tmp/shanghai_in
python3 scripts/fetch_shanghai_t2dm.py --archive /tmp/shanghai_in/diabetes_datasets.zip
#    -> data/real/shanghai/{diabetes_datasets.zip, members.txt, provenance.json}  (gitignored; md5/size verified)
# 2. optional readers for .xlsx/.xls (hash-pinned; not used by production or CI)
.venv/bin/pip install --require-hashes -r requirements-realdata.lock
# 3. stages
.venv/bin/python scripts/shanghai_experiment.py compat   # frozen-model compatibility (no data needed)
.venv/bin/python scripts/shanghai_experiment.py audit    # per-session audit only -> audit.json
.venv/bin/python scripts/shanghai_experiment.py run      # full protocol, single test pass, report
```

`audit` and `run` exit 2 (`BLOCKED`/`REJECTED`) unless the archive's size and md5 match v5 and `provenance.json` is
present. They refuse output paths that contain production files (exit 4).

| Output | Path |
|---|---|
| **Public, aggregate-only** | `reports/real_data/shanghai_t2dm/public/{SUMMARY.md, summary.json, rmse_by_horizon.svg}` (`publish` stage) |
| Results JSON (private, gitignored) | `reports/real_data/shanghai_t2dm/results.json` |
| Dated report (private, gitignored) | `reports/real_data/shanghai_t2dm/REPORT_<date>.md` (rendered from the JSON) |
| Plots (private, gitignored) | `reports/real_data/shanghai_t2dm/plots/*.svg` (trajectories show individual readings) |
| Model artifact + test predictions (gitignored) | `artifacts/real_data/shanghai_t2dm/{models.pkl, test_predictions.csv}`; sha256 and software versions recorded in `results.json` → `artifact` |
| Frozen-model check | `reports/real_data/shanghai_t2dm/frozen_model_compatibility.json` (generated) |

Code: `src/glucotwin/realdata/` (`shanghai.py` ingestion/audit, `windows.py`, `split.py`, `models.py`,
`compat.py`, `pipeline.py`, `report.py`, `plots.py`). Tests: `tests/test_realdata_shanghai.py`.

## Frozen production model: INCOMPATIBLE (documented schema only)

The served models consume all 33 `FEATURE_NAMES`. Ten have no documented source in ShanghaiT2DM: seven meal
features need carbohydrate grams (the dataset records weighed food as free text), and `steps_30`, `steps_60` and
`hr_rel_30` need activity and heart-rate data, which are not recorded. Running the model would mean fabricating
0 g / 0 steps, so **it will not be evaluated**.

The CGM-derived features would also be out of distribution: 15-min sampling against 5-min training data. After
ingestion, `recheck_with_inspected_columns` repeats the check against the real headers and records the result in
`results.json`.

## Pre-registered protocol

`experiments/shanghai_t2dm/config.json`: protocol `shanghai-t2dm-cgm-forecasting/1`, registered 2026-10-22 before
data access, sha256 `ecc71787f1059635b7d0d1bf1da8999989b3a341e644659a37cea5fbc80de6a5`, seed 20261022.
The report embeds the hash so any later change is visible.

- **Scope:** `Shanghai_T2DM` workbooks only. T1DM files are counted, then excluded. Files whose names don't
  parse are excluded, with the reason recorded.
- **Columns:** exactly one date column and one CGM column, otherwise the session is excluded (SchemaError).
  Optional fields are counted (non-empty and numeric), never assumed complete, and not used as model inputs.
- **Units:** a header unit is accepted only if the median value agrees with it. With no header unit, the unit
  is inferred from the median (mmol/L 2–25, mg/dL 40–450). Ambiguous cases are excluded. mmol/L × 18.016.
- **Cleaning** (counted per session, raw files never modified):
  - parse timestamps and sort (out-of-order rows counted);
  - identical duplicates are merged; conflicting duplicates are dropped entirely;
  - text values such as LO/HI are counted and excluded;
  - values outside 20–600 mg/dL are dropped; values at 40 or 500 mg/dL are flagged;
  - extra readings (strictly between two readings 15 ± 2 min apart, or < 5 min after the previous kept reading)
    are excluded;
  - gaps > 45 min start a new segment. **No interpolation, no imputation, no synthetic observations.**
- **Windows:** one anchor per recorded reading. Inputs are the readings nearest to −15/−30/−45/−60 min (±5 min)
  and targets the readings nearest to +30/+60/+120 min (±5 min), both within the same segment. All four inputs
  must be present. Features: g0, delta_15/30/60, accel_15, mean_60, std_60 and time of day.
- **Split:** by patient, **before** windowing. Seeded permutation of the sorted IDs, 60/20/20. All sessions of a
  patient go to the same split, and multi-session patients are listed. Leakage counters (patients or sessions in
  more than one split) must be 0.
- **Models:** persistence is the primary baseline. Ridge (scaler fitted on training rows) comes first, then a
  small gradient-boosting grid, both predicting the change from g0. Hyperparameters are chosen per horizon on
  validation-patient RMSE; models are fitted on training patients; **the test set is scored once**. At each
  horizon all models are scored on the identical test windows, and a common subset (targets at all horizons)
  is also reported.
- **Reporting:** MAE and RMSE; valid-window and patient counts; per-patient metrics; 95% patient-bootstrap CIs
  (2,000 resamples) and paired differences vs persistence; mean target-time offset; failure cases; plots.
- Real-data results are **not comparable** with the synthetic benchmark (different sampling, inputs, population).

## Verified so far (fixture tests only)

`tests/test_realdata_shanghai.py` (17 tests) uses generated UNIT-TEST FIXTURE frames and workbooks. Their header
strings are guesses, used only to exercise the parser. The tests cover name parsing, column detection, units,
chronology, duplicates, extra readings, gaps, the no-interpolation property, window matching, split determinism
and leakage, training-only scaling, bootstrap determinism, the compatibility verdict and the CLI guards.

The end-to-end fixture test needs `openpyxl` and is skipped when the optional lock isn't installed. Passing these
tests says nothing about the real files: they may use different headers or units, which the parser then rejects
explicitly rather than guessing.

## Independent review (2026-10-22)

The review recomputed everything with code separate from the pipeline: its own xlsx/xls reading, `merge_asof`
target matching and a fresh bootstrap. Only the pickled models were reused, to obtain predictions. Scripts:
`/tmp/review/independent.py`, `future_leak.py` (not committed).

**Verified (no change to any metric):**
- MAE, RMSE, improvement over persistence, both sets of 95% patient-bootstrap CIs, and all 180 per-patient RMSEs match
  `results.json` (0 mismatches). The 67,828 saved test predictions reproduce all 9 MAE/RMSE values.
- Changing the bootstrap seed (5 other seeds) moves the upper bound of every difference-vs-persistence RMSE CI
  by at most 0.084 mg/dL; all of them stay below 0 (the least negative is −2.548).
- Every usable target is the recorded reading at **exactly** anchor + 30/60/120 min (one unique offset per
  horizon). No feature input is at or after its anchor. In a future-corruption test (329,822 anchors; future
  readings replaced by noise or deleted), 0 feature vectors changed and 668 targets changed, which confirms the
  test was sensitive.
- 0 patients and 0 sessions in more than one split. All 8 multi-session patients sit in one split each (2 of them
  in test). Gaps > 45 min (2) split segments; 30/45-min gaps (9) leave the missing readings missing. Windows
  overlap; the patient-level bootstrap accounts for that dependence.
- Models are fitted on training patients only: the ridge scaler mean equals the training-row mean, not train+val.
- Two clean reruns after a full environment reset reproduce `results.json` (only timestamps and runtime differ),
  the SVGs byte for byte, and a bit-identical `models.pkl`.
- Sensitivity, excluding the 169–176 test windows that touch the 39.6 mg/dL floor, gives 60-min RMSE: persistence
  27.01, ridge 23.16, gradient boosting 22.40.

**Defects found and fixed (metrics unchanged; verified by identical rerun output):**
1. The split was computed after windows had been built, from the patients with ≥ 1 usable window. It is now fixed
   from the parsed patient IDs **before** windowing. The split is identical (100 of 100 patients included).
2. The run saved no window-level predictions and no artifact hash, and recorded an absolute artifact path. Now
   `test_predictions.csv`, sha256 values, relative paths and software versions are saved.
3. Reports and plots did not say that the models are glucose-history-only and **not** GlucoTwin. A scope
   statement was added to the report, the public summary and the bar chart.
4. The CC BY 4.0 notice lacked the licence URL, the descriptor paper and a statement of changes. All three
   were added.
5. A stale fetch-time note ("Schema not yet inspected") was presented as current provenance. It is now labelled
   `fetch_time_note`.
6. The private outputs hold dataset patient/session IDs, recording timestamps, per-patient metrics, failure-case
   readings and individual trajectories. They are now gitignored, and a separate aggregate-only `public/`
   summary was added.
7. The bar chart had no y-axis and used model jargon. It now has a labelled axis and plain model names.

**Safe to publish (aggregate only):** `reports/real_data/shanghai_t2dm/public/SUMMARY.md`, `public/summary.json`,
`public/rmse_by_horizon.svg`, this document, `experiments/shanghai_t2dm/config.json`, the code in
`src/glucotwin/realdata/`, `scripts/shanghai_experiment.py`, `tests/test_realdata_shanghai.py` and
`requirements-realdata.lock`. `frozen_model_compatibility.json` contains no data, but it records the pre-inspection
basis; publish it only alongside the summary, which carries the real-header confirmation.
