"""ShanghaiT2DM real-data experiment: audit -> patient split -> windows -> selection (train/val) -> one test pass.

Isolation: reads only the given zip; writes only to the given results / artifact directories. It never imports the
production bundle or writes to artifacts/model_bundle.pkl or the committed synthetic reports.
"""

from __future__ import annotations

import hashlib
import json
import pickle
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import sklearn

from glucotwin.realdata import compat, models, plots, shanghai
from glucotwin.realdata.split import SPLITS, assert_disjoint, assign, patient_split
from glucotwin.realdata.windows import FEATURES, add_features, build_windows

MODEL_NAMES = {"persistence": "persistence (last reading)", "ridge": "ridge (glucose history only)",
               "hgb": "gradient boosting (glucose history only)"}
MODELS_SUBTITLE = ("Models trained on ShanghaiT2DM CGM history only. The full GlucoTwin model was NOT evaluated "
                   "(inputs unavailable).")


def _sha256(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def _rel(p: Path) -> str:
    p = Path(p).resolve()
    try:
        return str(p.relative_to(Path.cwd().resolve()))
    except ValueError:
        return p.name


def config_hash(cfg: dict) -> str:
    return hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()


def audit_archive(zip_path: Path, cfg: dict) -> tuple[pd.DataFrame, list[dict], dict]:
    """(regular CGM series of all parseable sessions, per-session audit records, archive-level audit)."""
    rules = cfg["cleaning"]
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        sessions, summary_member, ignored = shanghai.list_members(names, cfg["data"]["folder"])
        series, records, headers = [], [], set()
        for member in sessions:
            rec: dict = {"member": member}
            try:
                sid = shanghai.parse_member_name(member)
                raw = shanghai.read_workbook(zf, member)
                headers.update(map(str, raw.columns))
                cols = shanghai.detect_columns(list(raw.columns))
                s, rec = shanghai.clean_cgm(raw, cols, sid, rules)
                rec["optional_fields"] = shanghai.optional_field_counts(raw, cols)
                rec["status"] = "parsed"
                series.append(s)
            except (shanghai.SchemaError, ValueError, KeyError) as e:
                rec.update({"status": "excluded", "reason": f"{type(e).__name__}: {e}"})
            records.append(rec)
        summary = None
        if summary_member:
            try:
                sdf = shanghai.read_workbook(zf, summary_member)
                summary = shanghai.summary_overview(sdf, [r.get("session_id") for r in records if r.get("session_id")])
                summary["member"] = summary_member
            except (shanghai.SchemaError, ValueError) as e:
                summary = {"member": summary_member, "error": f"{type(e).__name__}: {e}"}
    other_folder = sum(1 for n in names if "Shanghai_T1DM" in n and not n.endswith("/"))
    archive = {"n_members": len(names), "n_session_workbooks": len(sessions), "n_ignored_members": len(ignored),
               "n_members_in_T1DM_folder_or_summary (excluded population)": other_folder,
               "summary_sheet": summary,
               "frozen_model_recheck": compat.recheck_with_inspected_columns(sorted(headers)),
               "all_headers_seen": sorted(headers)}
    cols = ["patient_id", "session_id", "timestamp", "glucose", "segment"]
    return (pd.concat(series, ignore_index=True) if series else pd.DataFrame(columns=cols)), records, archive


def run_experiment(zip_path: Path, out_dir: Path, artifact_dir: Path, cfg: dict, data_label: str,
                   provenance: dict | None) -> dict:
    t_start = datetime.now(UTC)
    out_dir.mkdir(parents=True, exist_ok=True)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    series, records, archive = audit_archive(zip_path, cfg)
    H, lags, tol = cfg["windows"]["horizons_min"], cfg["windows"]["lags_min"], cfg["windows"]["tolerance_min"]
    seed = cfg["seed"]

    # Patient split is fixed from the parsed patient IDs alone, BEFORE any window exists.
    parsed_patients = sorted({r["patient_id"] for r in records if r.get("status") == "parsed"})
    split_all = patient_split(parsed_patients, seed, tuple(cfg["split"]["fractions"]))
    assert_disjoint(split_all)

    w = add_features(build_windows(series, lags, H, tol)) if len(series) else pd.DataFrame()
    usable_any = w["has_inputs"] & w[[f"y_{h}" for h in H]].notna().any(axis=1) if len(w) else pd.Series(dtype=bool)
    for rec in records:
        if rec.get("status") != "parsed":
            continue
        m = (w["session_id"] == rec["session_id"]) if len(w) else []
        rec["usable_windows_any_horizon"] = int(usable_any[m].sum()) if len(w) else 0
        rec["usable_windows_by_horizon"] = {str(h): int((w.loc[m, "has_inputs"] & w.loc[m, f"y_{h}"].notna()).sum())
                                            for h in H} if len(w) else {}
    min_w = cfg["inclusion"]["min_usable_windows_per_patient"]
    per_patient_windows = (w[usable_any].groupby("patient_id").size() if len(w) else pd.Series(dtype=int))
    included = sorted(per_patient_windows[per_patient_windows >= min_w].index.astype(str))
    sessions_per_patient = pd.Series([r["patient_id"] for r in records if r.get("status") == "parsed"]).value_counts()
    # inclusion (>= min usable windows) is applied WITHIN the pre-fixed split; excluded patients are reported
    split = {k: [p for p in v if p in set(included)] for k, v in split_all.items()}
    assert_disjoint(split)
    w = w[w["patient_id"].isin(included)].copy()
    w["split"] = assign(w["patient_id"], split)
    leak = {"patients_in_more_than_one_split": int(w.groupby("patient_id")["split"].nunique().gt(1).sum()),
            "sessions_in_more_than_one_split": int(w.groupby("session_id")["split"].nunique().gt(1).sum())}

    # ---- model selection: train + validation only, per horizon ----
    selection, chosen = {}, {}
    frames = {}
    for h in H:
        f = w[w["has_inputs"] & w[f"y_{h}"].notna()]
        frames[h] = {s: f[f["split"] == s] for s in SPLITS}
        tr, va = frames[h]["train"], frames[h]["validation"]
        ridge = models.select([(f"alpha={a}", models.make_ridge(a)) for a in cfg["models"]["ridge_alphas"]], tr, va, h)
        hgb = models.select([(json.dumps(p, sort_keys=True), models.make_hgb(p, seed)) for p in cfg["models"]["hgb_grid"]],
                            tr, va, h)
        chosen[h] = {"ridge": ridge["model"], "hgb": hgb["model"]}
        selection[str(h)] = {"ridge": {k: v for k, v in ridge.items() if k != "model"},
                             "hgb": {k: v for k, v in hgb.items() if k != "model"},
                             "n_windows": {s: int(len(frames[h][s])) for s in SPLITS},
                             "n_patients": {s: int(frames[h][s]["patient_id"].nunique()) for s in SPLITS}}

    # ---- the single test pass (all decisions above are fixed) ----
    results, failure_cases, bars = {}, {}, []
    test_pred_frames: list[pd.DataFrame] = []
    for h in H:
        te = frames[h]["test"].reset_index(drop=True)
        y = te[f"y_{h}"].to_numpy(float)
        preds = {"persistence": models.persistence(te), "ridge": models.predict_delta(chosen[h]["ridge"], te),
                 "hgb": models.predict_delta(chosen[h]["hgb"], te)}
        errs = {m: p - y for m, p in preds.items()}
        test_pred_frames.append(pd.DataFrame({"horizon_min": h, "patient_id": te["patient_id"], "session_id": te["session_id"],
                                              "anchor_time": te["anchor_time"], "target": y, **preds}))
        boot = models.patient_bootstrap(te, errs, "persistence", cfg["bootstrap"]["n_boot"], seed)
        results[str(h)] = {
            "n_windows": int(len(te)), "n_patients": int(te["patient_id"].nunique()),
            "mean_abs_target_offset_min": round(float(np.nanmean(np.abs(te[f"offset_{h}"]))), 3),
            "metrics": {m: {"mae": round(models.mae(e), 3), "rmse": round(models.rmse(e), 3)} for m, e in errs.items()},
            "bootstrap": boot,
            "per_patient": {m: models.per_patient(te, e) for m, e in errs.items()},
        }
        pp = results[str(h)]["per_patient"]
        worse = sorted(p for p in pp["ridge"] if pp["ridge"][p]["rmse"] > pp["persistence"][p]["rmse"])
        top = np.argsort(-np.abs(errs["ridge"]))[:5]
        failure_cases[str(h)] = {
            "test_patients_where_ridge_rmse_exceeds_persistence": worse,
            "largest_ridge_errors": [{"session_id": te.loc[i, "session_id"], "anchor_time": str(te.loc[i, "anchor_time"]),
                                      "g0": round(float(te.loc[i, "g0"]), 1), "actual": round(float(y[i]), 1),
                                      "ridge": round(float(preds["ridge"][i]), 1),
                                      "persistence": round(float(preds["persistence"][i]), 1)} for i in top]}
        for m in preds:
            ci = boot["ci95"][m]["rmse"]
            bars.append({"label": f"{h} min", "model": m, "value": results[str(h)]["metrics"][m]["rmse"],
                         "lo": ci[0], "hi": ci[1]})

    # common subset: test anchors with targets at EVERY horizon (comparable across horizons)
    common = w[(w["split"] == "test") & w["has_inputs"] & w[[f"y_{h}" for h in H]].notna().all(axis=1)]
    common_res = {"n_windows": int(len(common)), "n_patients": int(common["patient_id"].nunique()), "by_horizon": {}}
    for h in H:
        if len(common):
            y = common[f"y_{h}"].to_numpy(float)
            common_res["by_horizon"][str(h)] = {
                m: {"mae": round(models.mae(p - y), 3), "rmse": round(models.rmse(p - y), 3)}
                for m, p in (("persistence", models.persistence(common)),
                             ("ridge", models.predict_delta(chosen[h]["ridge"], common)),
                             ("hgb", models.predict_delta(chosen[h]["hgb"], common)))}

    # ---- plots ----
    plot_files = []
    (out_dir / "plots").mkdir(exist_ok=True)
    (out_dir / "plots" / "rmse_by_horizon.svg").write_text(
        plots.bars_svg(f"Held-out test RMSE by horizon, 95% patient-bootstrap CI [{data_label}]", bars,
                       names=MODEL_NAMES, subtitle=MODELS_SUBTITLE))
    plot_files.append("plots/rmse_by_horizon.svg")
    h_plot = cfg["plots"]["horizon_min"]
    te = frames[h_plot]["test"].reset_index(drop=True)
    if len(te):
        e_p = models.persistence(te) - te[f"y_{h_plot}"].to_numpy(float)
        sess = te.assign(e=e_p).groupby("session_id").agg(n=("e", "size"), rmse=("e", lambda x: float(np.sqrt(np.mean(x ** 2)))))
        sess = sess[sess["n"] >= cfg["plots"]["min_windows"]].sort_values(["rmse", "n"])
        picks = {}
        if len(sess):
            picks = {"lowest persistence error": sess.index[0], "median persistence error": sess.index[len(sess) // 2],
                     "highest persistence error": sess.index[-1]}
        plotted: set[str] = set()
        for label, sid in picks.items():
            if sid in plotted:  # few eligible test sessions: never plot the same one twice
                continue
            plotted.add(sid)
            part = te[te["session_id"] == sid]
            hours = cfg["plots"]["max_hours"]
            t_end = part["anchor_time"].min() + pd.Timedelta(hours=hours)
            part = part[part["anchor_time"] <= t_end]
            actual = series[(series["session_id"] == sid) & (series["timestamp"] <= t_end + pd.Timedelta(minutes=h_plot))]
            tt = part["anchor_time"] + pd.Timedelta(minutes=h_plot)
            pr = {"persistence": pd.DataFrame({"target_time": tt, "pred": models.persistence(part)}),
                  "ridge": pd.DataFrame({"target_time": tt, "pred": models.predict_delta(chosen[h_plot]["ridge"], part)})}
            fn = f"plots/trajectory_{sid}.svg"
            (out_dir / fn).write_text(plots.trajectory_svg(
                f"{sid} (test) - {h_plot}-min-ahead forecasts, first {hours} h - {label} [{data_label}]", actual[["timestamp", "glucose"]], pr))
            plot_files.append(fn)

    # ---- artifact (separate from the production bundle) ----
    artifact = {"kind": "glucotwin-realdata-shanghai-t2dm", "config_sha256": config_hash(cfg), "features": FEATURES,
                "horizons_min": H, "models": chosen, "data_label": data_label}
    versions = {"python": sys.version.split()[0], "numpy": np.__version__, "pandas": pd.__version__,
                "scikit-learn": sklearn.__version__}
    artifact["software"] = versions
    artifact["data_sha256"] = (provenance or {}).get("verified", {}).get("sha256")
    art_path = artifact_dir / "models.pkl"
    with open(art_path, "wb") as fh:
        pickle.dump(artifact, fh)
    pred_path = artifact_dir / "test_predictions.csv"
    pd.concat(test_pred_frames, ignore_index=True).to_csv(pred_path, index=False, float_format="%.4f")

    out = {
        "schema": "glucotwin-realdata-results/1",
        "data_label": data_label,
        "generated_at": t_start.isoformat(),
        "config": cfg, "config_sha256": config_hash(cfg),
        "provenance": provenance,
        "archive_audit": archive,
        "sessions": records,
        "counts": {
            "session_workbooks": archive["n_session_workbooks"],
            "sessions_parsed": sum(r.get("status") == "parsed" for r in records),
            "sessions_excluded": sum(r.get("status") != "parsed" for r in records),
            "unique_patients_parsed": len(parsed_patients),
            "patients_with_multiple_sessions": {str(k): int(v) for k, v in sessions_per_patient[sessions_per_patient > 1].items()},
            "regular_cgm_readings": int(len(series)),
            "patients_included": len(included),
            "patients_excluded_too_few_windows": sorted(set(parsed_patients) - set(included)),
        },
        "split": {**split, "unit": "patient (all sessions of a patient in one split)", "seed": seed,
                  "fixed_before_windowing": True},
        "leakage_checks": leak,
        "frozen_model": compat.frozen_model_compatibility(),
        "selection": selection,
        "test_results": results,
        "test_results_common_subset": common_res,
        "failure_cases": failure_cases,
        "plots": plot_files,
        "artifact": {"models": _rel(art_path), "models_sha256": _sha256(art_path),
                     "test_predictions": _rel(pred_path), "test_predictions_sha256": _sha256(pred_path),
                     "software": versions, "note": "private, gitignored; regenerate with `scripts/shanghai_experiment.py run`"},
        "runtime_s": round((datetime.now(UTC) - t_start).total_seconds(), 1),
    }
    (out_dir / "results.json").write_text(json.dumps(out, indent=2, default=str) + "\n")
    return out
