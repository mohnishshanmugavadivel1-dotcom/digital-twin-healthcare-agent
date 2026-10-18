"""Independent robustness audit of the v0.1 evaluation (``glucotwin audit``).

Everything here is *additional* to ``pipeline.py``; it never changes the served model. It answers:

1. Consistency: re-implementing the protocol reproduces the pipeline's headline numbers.
2. Baseline fairness: the trend-rule threshold is re-chosen over data-driven (quantile) candidates,
   because the fixed 0.05-0.95 grid clipped it at its lowest value.
3. Stricter alert metrics: false alerts per *monitored* day; "sustained" warnings (alert still on at the last
   eligible prediction before onset); warnings with >= 30 min lead.
4. Uncertainty: patient-level bootstrap 95 % CIs (only 12 test patients).
5. Feature ablation: the synthetic HbA1c is derived from the same 14-day window that is evaluated
   (corr ~0.95 with that window's mean CGM), so we measure how much record features matter.
6. Seed robustness: the whole protocol on independently generated cohorts.
7. Stress test: harder observation realism (fewer, later, noisier meal logs; noisier CGM).

All results describe the synthetic simulator only.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from glucotwin.config import CGM_INTERVAL_MIN, EVENT_HORIZON_MIN, FORECAST_HORIZONS_MIN
from glucotwin.dataset import build_cohort_table
from glucotwin.evaluation.metrics import choose_threshold, event_metrics
from glucotwin.features import FEATURE_NAMES, split_streams
from glucotwin.labels import excursion_onsets, to_grid
from glucotwin.models.forecasting import (
    GradientBoostingEventModel,
    GradientBoostingForecaster,
    LogisticEventModel,
    PersistenceForecaster,
    TrendRuleScorer,
)
from glucotwin.synth.generator import DEFAULT_REALISM, DEFAULT_SEED, Realism, generate_cohort

log = logging.getLogger(__name__)

EHR_FEATURES = ["age_years", "bmi", "hba1c_percent", "fasting_glucose_mg_dl", "diabetes_duration_years", "egfr",
                "med_sulfonylurea", "med_basal_insulin", "med_biguanide", "med_dpp4_inhibitor"]
MEAL_FEATURES = ["carbs_30", "carbs_60", "carbs_120", "carbs_on_board", "minutes_since_meal",
                 "expected_meal_rise", "carb_sensitivity"]
STRESS_REALISM = Realism(meal_log_prob=0.6, carb_log_sigma=0.5, meal_log_delay_max_min=45, cgm_noise_sd=7.0)
EPISODE_GAP = pd.Timedelta(minutes=10)


def choose_threshold_quantile(y: np.ndarray, p: np.ndarray) -> float:
    """Max-F1 threshold over data-driven candidates (validation score quantiles), works for any score scale."""
    cands = np.unique(np.quantile(p, np.linspace(0.0, 0.995, 400)))
    best_t, best_f1 = float(cands[0]), -1.0
    for t in cands:
        pred = p >= t
        tp = np.sum(pred & (y == 1))
        f1 = 2 * tp / max(np.sum(pred) + np.sum(y == 1), 1)  # = 2TP / (2TP + FP + FN)
        if f1 > best_f1:
            best_t, best_f1 = float(t), f1
    return best_t


def per_patient_alert_stats(frame: pd.DataFrame, alert: np.ndarray, onsets: dict, monitored_days: dict) -> pd.DataFrame:
    """Per test patient: onsets with an eligible prediction, warned (any alert in 120 min), warned >= 30 min ahead,
    sustained warning (alert on at the last eligible prediction before onset, which is <= 30 min before onset),
    leads, and false-alert episodes. Columns allow exact patient-bootstrap of ratios."""
    horizon = pd.Timedelta(minutes=EVENT_HORIZON_MIN)
    rows = []
    df = frame.assign(alert=alert)
    for pid, sub in df.groupby("patient_id"):
        sub = sub.sort_values("timestamp")
        ts = pd.DatetimeIndex(sub["timestamp"])
        al = sub["alert"].to_numpy()
        ep_id = np.cumsum(np.r_[True, np.diff(ts.asi8) > EPISODE_GAP.value] | ~al)  # breaks on gaps or alert-off
        n_on = n_any = n_30 = n_sus = 0
        leads_any, leads_sus = [], []
        for onset in onsets.get(pid, pd.DatetimeIndex([])):
            win = (ts >= onset - horizon) & (ts < onset)
            if not win.any():
                continue
            n_on += 1
            a_win = win & al
            if a_win.any():
                n_any += 1
                lead = (onset - ts[a_win].min()).total_seconds() / 60
                leads_any.append(lead)
                n_30 += lead >= 30
            last = np.flatnonzero(win)[-1]
            if al[last] and (onset - ts[last]) <= pd.Timedelta(minutes=30):
                start = np.flatnonzero((ep_id == ep_id[last]) & al)[0]
                n_sus += 1
                leads_sus.append(min((onset - ts[start]).total_seconds() / 60, EVENT_HORIZON_MIN))
        a = sub[sub["alert"]]
        false_eps = 0
        if not a.empty:
            new_ep = a["timestamp"].diff().gt(EPISODE_GAP).cumsum()
            false_eps = int(sum((ep["y_event"] == 0).all() for _, ep in a.groupby(new_ep)))
        rows.append(dict(patient_id=pid, onsets=n_on, warned=n_any, warned_30=n_30, sustained=n_sus,
                         leads_any=leads_any, leads_sus=leads_sus, false_eps=false_eps,
                         monitored_days=monitored_days[pid], nominal_days=None))
    return pd.DataFrame(rows).set_index("patient_id")


def summarise_alert_stats(st: pd.DataFrame) -> dict:
    la = [x for v in st["leads_any"] for x in v]
    ls = [x for v in st["leads_sus"] for x in v]
    on = st["onsets"].sum()
    return {
        "onsets": int(on),
        "event_sensitivity_any_alert": float(st["warned"].sum() / on) if on else None,
        "event_sensitivity_lead_ge_30min": float(st["warned_30"].sum() / on) if on else None,
        "event_sensitivity_sustained": float(st["sustained"].sum() / on) if on else None,
        "median_lead_any_alert_min": float(np.median(la)) if la else None,
        "median_lead_sustained_min": float(np.median(ls)) if ls else None,
        "false_alert_episodes_per_monitored_day": float(st["false_eps"].sum() / st["monitored_days"].sum()),
    }


def _fit_eval(cohort, table: pd.DataFrame, seed: int, features: list[str] | None = None, traj: bool = True,
              days: int = 14) -> dict:
    """Protocol of pipeline.py (fit on train, choose on validation, evaluate once on test)."""
    features = features or FEATURE_NAMES
    tr, va, te = (table[table["split"] == s] for s in ("train", "validation", "test"))
    out: dict = {"n_test_patients": int(te["patient_id"].nunique())}
    test_ids = sorted(te["patient_id"].unique())
    onsets = {pid: excursion_onsets(to_grid(split_streams(cohort.patient_observations(pid))["cgm"])) for pid in test_ids}
    span = te.groupby("patient_id")["timestamp"].agg(lambda s: (s.max() - s.min()).total_seconds() / 86400)
    monitored = span.to_dict()
    out["monitored_days_total"] = float(span.sum())
    out["nominal_days_total"] = float(len(test_ids) * days)
    tr_e, va_e, te_e = (d.dropna(subset=["y_event"]) for d in (tr, va, te))
    out["test_prevalence"] = float(te_e["y_event"].mean())
    ev = {}
    for m in (TrendRuleScorer(), LogisticEventModel(), GradientBoostingEventModel(seed=seed)):
        m.fit(tr_e[features], tr_e["y_event"].to_numpy().astype(int))
        pv = m.predict_proba(va_e[features])
        yv = va_e["y_event"].to_numpy().astype(int)
        pt = m.predict_proba(te_e[features])
        yt = te_e["y_event"].to_numpy().astype(int)
        frame = te_e[["patient_id", "timestamp", "y_event"]].assign(score=pt)
        res = {"auroc": float(roc_auc_score(yt, pt))}
        for tname, thr in (("grid", choose_threshold(yv, pv)), ("quantile", choose_threshold_quantile(yv, pv))):
            orig = event_metrics(frame, "score", thr, onsets, out["nominal_days_total"], is_probability=False)
            st = per_patient_alert_stats(frame, pt >= thr, onsets, monitored)
            res[tname] = {"threshold": thr, "sensitivity": orig["sensitivity"], "specificity": orig["specificity"],
                          "ppv": orig["ppv"], "v01_event_sensitivity": orig["event_sensitivity"],
                          "v01_median_lead_min": orig["median_lead_time_min"],
                          "v01_false_alerts_per_nominal_day": orig["false_alert_episodes_per_patient_day"],
                          **summarise_alert_stats(st)}
            res[tname]["_stats"] = st
        res["_frame"] = frame
        ev[m.name] = res
    out["event"] = ev
    if traj:
        tm = {}
        for m in (PersistenceForecaster(), GradientBoostingForecaster(seed=seed)):
            m.fit(tr[features], tr)
            pred = m.predict(te[features])
            per = {}
            for h in FORECAST_HORIZONS_MIN:
                y = te[f"y_glucose_{h}"].to_numpy()
                ok = ~np.isnan(y)
                e2 = (pred[h].to_numpy() - y) ** 2
                per[h] = pd.DataFrame({"pid": te["patient_id"].to_numpy()[ok], "e2": e2[ok]})
            tm[m.name] = {"rmse": {h: float(np.sqrt(per[h]["e2"].mean())) for h in FORECAST_HORIZONS_MIN},
                          "_per": per}
        out["trajectory"] = tm
    return out


def _bootstrap(res: dict, n_boot: int, seed: int) -> dict:
    rng = np.random.default_rng(seed)
    pids = sorted(res["event"]["logistic_regression"]["_frame"]["patient_id"].unique())
    groups = {}
    for name, r in res["event"].items():
        f = r["_frame"]
        groups[name] = {p: (g["y_event"].to_numpy().astype(int), g["score"].to_numpy()) for p, g in f.groupby("patient_id")}
    draws = {k: [] for k in ("auroc_logistic", "auroc_hgb", "auroc_trend", "rmse30_hgb", "rmse120_hgb",
                             "rmse30_persistence", "evsens_any_logistic", "evsens_sustained_logistic",
                             "fa_per_monitored_day_logistic")}
    tr = res["trajectory"]
    sse = {(m, h): tr[m]["_per"][h].groupby("pid")["e2"].agg(["sum", "count"]) for m in tr for h in (30, 120)}
    st = res["event"]["logistic_regression"]["grid"]["_stats"]  # served configuration (threshold from pipeline)
    for _ in range(n_boot):
        s = rng.choice(pids, size=len(pids), replace=True)
        for key, name in (("auroc_logistic", "logistic_regression"), ("auroc_hgb", "hist_gradient_boosting"),
                          ("auroc_trend", "trend_rule")):
            y = np.concatenate([groups[name][p][0] for p in s])
            sc = np.concatenate([groups[name][p][1] for p in s])
            draws[key].append(roc_auc_score(y, sc) if len(np.unique(y)) == 2 else np.nan)
        for key, m, h in (("rmse30_hgb", "hist_gradient_boosting", 30), ("rmse120_hgb", "hist_gradient_boosting", 120),
                          ("rmse30_persistence", "persistence", 30)):
            t = sse[(m, h)].loc[s]
            draws[key].append(np.sqrt(t["sum"].sum() / t["count"].sum()))
        b = st.loc[s]
        draws["evsens_any_logistic"].append(b["warned"].sum() / max(b["onsets"].sum(), 1))
        draws["evsens_sustained_logistic"].append(b["sustained"].sum() / max(b["onsets"].sum(), 1))
        draws["fa_per_monitored_day_logistic"].append(b["false_eps"].sum() / b["monitored_days"].sum())
    return {k: [float(np.nanpercentile(v, 2.5)), float(np.nanpercentile(v, 97.5))] for k, v in draws.items()}


def _headline(res: dict) -> dict:
    ev = res["event"]
    h = {"test_prevalence": res["test_prevalence"]}
    for name, r in ev.items():
        h[f"auroc_{name}"] = r["auroc"]
    if "trajectory" in res:
        for m, r in res["trajectory"].items():
            h[f"rmse30_{m}"] = r["rmse"][30]
            h[f"rmse120_{m}"] = r["rmse"][120]
    q = ev["logistic_regression"]["grid"]  # served configuration
    for k in ("event_sensitivity_any_alert", "event_sensitivity_sustained", "event_sensitivity_lead_ge_30min",
              "median_lead_sustained_min", "false_alert_episodes_per_monitored_day"):
        h[f"logistic_{k}"] = q[k]
    return h


def _strip(obj):
    if isinstance(obj, dict):
        return {str(k): _strip(v) for k, v in obj.items() if not str(k).startswith("_")}
    return obj


def run_audit(seed: int = DEFAULT_SEED, extra_seeds=(1, 2, 3), n_boot: int = 1000, n_patients: int = 60,
              days: int = 14, out_path: Path | None = Path("reports/audit_report.json"),
              pipeline_report: Path | None = Path("reports/evaluation_report.json")) -> dict:
    t0 = time.time()
    report: dict = {"schema": "glucotwin-audit/1", "seed": seed, "is_synthetic": True,
                    "disclaimer": "Synthetic-simulator results only; not clinical validation.",
                    "stress_realism": asdict(STRESS_REALISM), "default_realism": asdict(DEFAULT_REALISM)}

    cohort = generate_cohort(n_patients, days, seed)
    table = build_cohort_table(cohort)
    main = _fit_eval(cohort, table, seed, days=days)
    log.info("main protocol re-run done (%.0fs)", time.time() - t0)

    # 1. consistency with the committed pipeline report
    if pipeline_report and Path(pipeline_report).exists():
        rep = json.loads(Path(pipeline_report).read_text())
        chk = {}
        for e in rep["event"]:
            mine = main["event"][e["model"]]
            chk[e["model"]] = {"auroc_match": bool(abs(mine["auroc"] - e["auroc"]) < 1e-9),
                               "threshold_match": bool(mine["grid"]["threshold"] == e["threshold"]),
                               "event_sens_match": bool(mine["grid"]["v01_event_sensitivity"] == e["event_sensitivity"])}
        for t in rep["trajectory"]:
            if t["model"] in main["trajectory"] and t["horizon_min"] in (30, 120):
                chk[f"rmse_{t['model']}_{t['horizon_min']}_match"] = bool(
                    abs(main["trajectory"][t["model"]]["rmse"][t["horizon_min"]] - t["rmse_mg_dl"]) < 1e-9)
        report["consistency_with_pipeline_report"] = chk

    report["main"] = _strip(main)
    report["bootstrap_95ci_patient_level"] = _bootstrap(main, n_boot, seed)
    log.info("bootstrap done (%.0fs)", time.time() - t0)

    # 5. ablations (event models only + HGB trajectory is costly; event-level is what matters for HbA1c)
    abl = {}
    for name, drop in (("no_record_features", EHR_FEATURES), ("no_hba1c_fpg", ["hba1c_percent", "fasting_glucose_mg_dl"]),
                       ("no_meal_features", MEAL_FEATURES)):
        feats = [f for f in FEATURE_NAMES if f not in drop]
        r = _fit_eval(cohort, table, seed, features=feats, traj=False, days=days)
        abl[name] = {"dropped": drop, **{f"auroc_{k}": v["auroc"] for k, v in r["event"].items()},
                     "logistic_event_sensitivity_sustained": r["event"]["logistic_regression"]["quantile"]["event_sensitivity_sustained"]}
    report["ablation"] = abl
    log.info("ablations done (%.0fs)", time.time() - t0)

    # 6. seed robustness
    seeds = {}
    for s in extra_seeds:
        c = generate_cohort(n_patients, days, s)
        seeds[str(s)] = _headline(_fit_eval(c, build_cohort_table(c), s, days=days))
        log.info("seed %s done (%.0fs)", s, time.time() - t0)
    report["seed_robustness"] = {"main_seed": _headline(main), "other_seeds": seeds}

    # 7. stress test
    c = generate_cohort(n_patients, days, seed, realism=STRESS_REALISM)
    report["stress_test"] = _headline(_fit_eval(c, build_cohort_table(c), seed, days=days))
    report["runtime_s"] = round(time.time() - t0, 1)
    log.info("audit finished in %.0fs", report["runtime_s"])
    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2, default=float))
    return report


__all__ = ["run_audit", "choose_threshold_quantile", "per_patient_alert_stats", "STRESS_REALISM", "CGM_INTERVAL_MIN"]
