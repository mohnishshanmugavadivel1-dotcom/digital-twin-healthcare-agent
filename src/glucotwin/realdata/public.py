"""Aggregate-only public summary of a ShanghaiT2DM run (derived from results.json; no raw data).

Excluded on purpose: patient and session identifiers, recording dates and timestamps, per-patient metrics, failure-case
glucose readings and individual trajectories. Those stay in the private results.json / artifacts.
"""

from __future__ import annotations

import numpy as np

MODEL_NAMES = {"persistence": "persistence (last reading)", "ridge": "ridge (glucose history only)",
               "hgb": "gradient boosting (glucose history only)"}

ATTRIBUTION = (
    "Data: ShanghaiT2DM, from \"diabetes_datasets.zip\" version 5 by Qinpei Zhao, Jinhao Zhu, Congrong Wang and "
    "Weixiong Rao (figshare, 2022), https://doi.org/10.6084/m9.figshare.21600933.v5, licensed under CC BY 4.0 "
    "(https://creativecommons.org/licenses/by/4.0/). Dataset descriptor: Zhao Q. et al., \"Chinese diabetes datasets "
    "for data-driven machine learning\", Scientific Data (2023), https://doi.org/10.1038/s41597-023-01940-7. "
    "Changes: only the Shanghai_T2DM CGM readings were used; they were cleaned, split into segments at gaps longer "
    "than 45 min and turned into forecasting windows, and only aggregate derived results are shown. No raw data are "
    "redistributed here. The dataset authors have not reviewed or endorsed this work.")

SCOPE = (
    "These are models trained here on ShanghaiT2DM glucose history only (persistence, ridge, gradient boosting). "
    "They are NOT the GlucoTwin model: the full GlucoTwin model was not evaluated on ShanghaiT2DM because 10 of its "
    "33 inputs (meal carbohydrate grams, steps, heart rate) are not recorded in the dataset. Research experiment on "
    "retrospective data; not clinical validation; not a medical device.")


def public_summary(r: dict) -> dict:
    parsed = [s for s in r["sessions"] if s.get("status") == "parsed"]
    ms = [s["missing_share"] for s in parsed]
    tests = {}
    for h, t in r["test_results"].items():
        pp = t["per_patient"]
        n_pat = len(pp["persistence"])
        tests[h] = {
            "test_windows": t["n_windows"], "test_patients": t["n_patients"],
            "metrics_mg_dl": {MODEL_NAMES[m]: v for m, v in t["metrics"].items()},
            "rmse_ci95": {MODEL_NAMES[m]: v["rmse"] for m, v in t["bootstrap"]["ci95"].items()},
            "mae_ci95": {MODEL_NAMES[m]: v["mae"] for m, v in t["bootstrap"]["ci95"].items()},
            "rmse_difference_vs_persistence": {
                MODEL_NAMES[m]: {"point": round(t["metrics"][m]["rmse"] - t["metrics"]["persistence"]["rmse"], 3),
                                 "ci95": d["rmse"]}
                for m, d in t["bootstrap"]["difference_vs_persistence_ci95"].items()},
            "test_patients_with_lower_rmse_than_persistence": {
                MODEL_NAMES[m]: f"{sum(pp[m][p]['rmse'] < pp['persistence'][p]['rmse'] for p in pp[m])}/{n_pat}"
                for m in ("ridge", "hgb")},
            "patient_averaged_rmse": {MODEL_NAMES[m]: round(float(np.mean([v["rmse"] for v in pp[m].values()])), 2)
                                      for m in pp},
        }
    c, sp = r["counts"], r["split"]
    low = r.get("post_hoc_observations", {}).get("readings_at_lowest_recorded_value")
    return {
        "schema": "glucotwin-realdata-public-summary/1",
        "generated_from": "results.json of the run below (aggregates only)",
        "run_date": r["generated_at"][:10],
        "scope": SCOPE,
        "attribution": ATTRIBUTION,
        "dataset": {"doi": "10.6084/m9.figshare.21600933.v5", "licence": "CC BY 4.0",
                    "archive_md5": r["config"]["data"]["archive_md5"],
                    "archive_size_bytes": r["config"]["data"]["archive_size_bytes"]},
        "protocol": {"id": r["config"]["protocol"], "registered_on": r["config"]["registered_on"],
                     "config_sha256_canonical": r["config_sha256"], "seed": r["config"]["seed"],
                     "horizons_min": r["config"]["windows"]["horizons_min"],
                     "features": ["latest reading", "changes over 15/30/60 min", "15-min acceleration",
                                  "mean and SD of the last 5 readings (60 min)", "time of day"],
                     "target_matching": "recorded reading exactly at anchor + horizon (tolerance 5 min, same gap-free "
                                        "segment); no interpolation"},
        "counts": {"session_files": c["session_workbooks"], "sessions_excluded": c["sessions_excluded"],
                   "unique_patients": c["unique_patients_parsed"], "patients_included": c["patients_included"],
                   "patients_with_more_than_one_session": len(c["patients_with_multiple_sessions"]),
                   "cgm_readings_used": c["regular_cgm_readings"],
                   "sessions_with_any_missing_15min_slot": sum(m > 0 for m in ms),
                   "max_session_missing_share": max(ms) if ms else None,
                   "gaps_over_45_min": sum(s["n_gaps_over_max"] for s in parsed),
                   "readings_at_lowest_recorded_value_39_6": low["n_readings"] if low else None},
        "split": {"unit": "patient", "fixed_before_windowing": bool(sp.get("fixed_before_windowing")),
                  "patients": {k: len(sp[k]) for k in ("train", "validation", "test")},
                  "leakage_checks": r["leakage_checks"]},
        "frozen_glucotwin_model": {"evaluated": False, "verdict": r["frozen_model"]["verdict"],
                                   "not_recorded_inputs": len(r["frozen_model"]["not_recorded_features"]),
                                   "of_inputs": r["frozen_model"]["production_model_features"],
                                   "confirmed_against_inspected_headers": {
                                       "verdict": r["archive_audit"]["frozen_model_recheck"]["verdict"],
                                       "inputs_found": r["archive_audit"]["frozen_model_recheck"]["decisive_inputs_found"],
                                       "session_files_inspected": r["counts"]["sessions_parsed"]}},
        "held_out_test": tests,
        "uncertainty": "95% percentile intervals from 2,000 bootstrap resamples of test patients; pooled metrics weight "
                       "patients by their number of windows (consecutive windows overlap and are correlated, which the "
                       "patient-level resampling accounts for).",
    }


def public_markdown(s: dict) -> str:
    L = [f"# ShanghaiT2DM glucose-history forecasting — aggregate results ({s['run_date']})", "",
         f"**Scope.** {s['scope']}", "", f"**Attribution.** {s['attribution']}", "",
         "## Cohort and split",
         f"- {s['counts']['session_files']} session files from {s['counts']['unique_patients']} patients "
         f"({s['counts']['patients_with_more_than_one_session']} with more than one session); "
         f"{s['counts']['sessions_excluded']} excluded; {s['counts']['cgm_readings_used']:,} CGM readings used.",
         f"- Missing 15-min slots: {s['counts']['sessions_with_any_missing_15min_slot']} sessions affected "
         f"(max share {s['counts']['max_session_missing_share']}); gaps > 45 min: {s['counts']['gaps_over_45_min']} "
         "(segments split, nothing interpolated).",
         f"- {s['counts']['readings_at_lowest_recorded_value_39_6']} readings sit at 39.6 mg/dL, the lowest recorded "
         "value (likely the sensor floor); kept as recorded, so low glucose is censored.",
         f"- Patient-level split fixed before windowing: {s['split']['patients']['train']} train / "
         f"{s['split']['patients']['validation']} validation / {s['split']['patients']['test']} test patients; "
         f"{s['split']['leakage_checks']['patients_in_more_than_one_split']} patients and "
         f"{s['split']['leakage_checks']['sessions_in_more_than_one_split']} sessions in more than one split.",
         f"- Full GlucoTwin model: not evaluated ({s['frozen_glucotwin_model']['not_recorded_inputs']} of "
         f"{s['frozen_glucotwin_model']['of_inputs']} inputs not recorded; confirmed against the headers of all "
         f"{s['frozen_glucotwin_model']['confirmed_against_inspected_headers']['session_files_inspected']} session files).", "",
         "## Held-out test results (mg/dL)", "",
         "| horizon | windows | patients | model | MAE | RMSE [95% CI] | RMSE − persistence [95% CI] | patients better than persistence |",
         "|---|---|---|---|---|---|---|---|"]
    for h, t in s["held_out_test"].items():
        for m, met in t["metrics_mg_dl"].items():
            ci = t["rmse_ci95"][m]
            d = t["rmse_difference_vs_persistence"].get(m)
            dtxt = f"{d['point']:+.2f} [{d['ci95'][0]:.2f}, {d['ci95'][1]:.2f}]" if d else "—"
            better = t["test_patients_with_lower_rmse_than_persistence"].get(m, "—")
            L.append(f"| {h} min | {t['test_windows']:,} | {t['test_patients']} | {m} | {met['mae']:.2f} | "
                     f"{met['rmse']:.2f} [{ci[0]:.2f}, {ci[1]:.2f}] | {dtxt} | {better} |")
    L += ["", f"Uncertainty: {s['uncertainty']}", "",
          "## Limitations",
          "- 20 test patients from one cohort, one region and one sensor type (FreeStyle Libre, 15-min readings).",
          "- Glucose history only: diet, insulin and medication fields were not used; no meal or activity information.",
          "- Low readings are censored at the sensor floor; text values such as LO/HI were not present.",
          "- Not comparable with GlucoTwin's synthetic benchmark (different sampling, inputs and population).",
          "- Retrospective accuracy does not establish clinical utility or safety.", ""]
    return "\n".join(L)
