"""B-07 analysis: post-hoc probability calibration of the event models (research only).

Refits the logistic-regression (served default) and HistGradientBoosting (opt-in, never served)
event models exactly as ``evaluation/pipeline.py`` does, verifies that they reproduce the
committed test AUROC/Brier, then fits Platt and isotonic calibrators on VALIDATION patients only
and evaluates uncalibrated vs calibrated probabilities once on the untouched TEST patients.

Nothing protected is modified: no model artifact, no committed report, no served behaviour.
Writes new files only:
    reports/research/b07_calibration.json
    reports/research/b07_reliability_logistic_regression.svg
    reports/research/b07_reliability_hist_gradient_boosting.svg

    .venv/bin/python scripts/b07_calibration_analysis.py [--table-cache PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from glucotwin.dataset import build_cohort_table  # noqa: E402
from glucotwin.evaluation.metrics import choose_threshold  # noqa: E402
from glucotwin.features import FEATURE_NAMES  # noqa: E402
from glucotwin.labels import EVENT_DEFINITION  # noqa: E402
from glucotwin.models.forecasting import GradientBoostingEventModel, LogisticEventModel  # noqa: E402
from glucotwin.synth.generator import DEFAULT_SEED, generate_cohort  # noqa: E402

SEED = 20261021
B_BOOT = 2000
N_BINS = 15
EPS = 1e-6


# ----------------------------------------------------------------------------- calibrators
class Platt:
    """Logistic recalibration on logit(p): p' = sigmoid(a * logit(p) + b). Effectively unregularized."""

    name = "platt"

    def fit(self, p, y):
        self.m = LogisticRegression(C=1e6, max_iter=1000).fit(_logit(p)[:, None], y)
        return self

    def predict(self, p):
        return self.m.predict_proba(_logit(p)[:, None])[:, 1]

    def params(self):
        return {"slope_a": float(self.m.coef_[0, 0]), "intercept_b": float(self.m.intercept_[0])}


class Isotonic:
    name = "isotonic"

    def fit(self, p, y):
        self.m = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip").fit(p, y)
        return self

    def predict(self, p):
        return self.m.predict(p)

    def params(self):
        return {"n_steps": int(len(self.m.X_thresholds_))}


def _logit(p):
    p = np.clip(np.asarray(p, float), EPS, 1 - EPS)
    return np.log(p / (1 - p))


# ----------------------------------------------------------------------------- metrics
def ece(y, p, n_bins=N_BINS, strategy="uniform"):
    """Expected calibration error: sum_b (n_b / n) * |mean(p_b) - mean(y_b)|.

    uniform: equal-width bins on [0, 1] (right-closed, first bin includes 0);
    quantile: equal-mass bins on the predicted probabilities (ties may merge bins).
    """
    y, p = np.asarray(y, float), np.asarray(p, float)
    if strategy == "uniform":
        edges = np.linspace(0, 1, n_bins + 1)
    else:
        edges = np.unique(np.quantile(p, np.linspace(0, 1, n_bins + 1)))
    idx = np.clip(np.searchsorted(edges, p, side="left") - 1, 0, len(edges) - 2)
    total, mce = 0.0, 0.0
    for b in range(len(edges) - 1):
        m = idx == b
        if m.any():
            gap = abs(p[m].mean() - y[m].mean())
            total += m.mean() * gap
            mce = max(mce, gap)
    return float(total), float(mce)


def reliability_table(y, p, n_bins=N_BINS):
    edges = np.linspace(0, 1, n_bins + 1)
    idx = np.clip(np.searchsorted(edges, p, side="left") - 1, 0, n_bins - 1)
    rows = []
    for b in range(n_bins):
        m = idx == b
        if m.any():
            rows.append({"bin": [round(edges[b], 4), round(edges[b + 1], 4)], "n": int(m.sum()),
                         "mean_predicted": round(float(p[m].mean()), 4), "observed_rate": round(float(y[m].mean()), 4)})
    return rows


def cal_slope_intercept(y, p):
    """Descriptive calibration slope/intercept on the evaluation set (logistic fit of y on logit p)."""
    m = LogisticRegression(C=1e6, max_iter=1000).fit(_logit(p)[:, None], y)
    return float(m.coef_[0, 0]), float(m.intercept_[0])


def metrics(y, p):
    e_u, mce_u = ece(y, p, strategy="uniform")
    e_q, _ = ece(y, p, strategy="quantile")
    slope, intercept = cal_slope_intercept(y, p)
    return {"brier": float(brier_score_loss(y, p)), "log_loss": float(log_loss(y, np.clip(p, EPS, 1 - EPS))),
            "ece_uniform15": e_u, "ece_quantile15": e_q, "max_calibration_error_uniform15": mce_u,
            "auroc": float(roc_auc_score(y, p)), "mean_predicted": float(np.mean(p)), "observed_rate": float(np.mean(y)),
            "calibration_slope": slope, "calibration_intercept": intercept}


def boot_diffs(y, p_un, p_cal, pids, rng, b=B_BOOT):
    """Patient-cluster bootstrap of (calibrated - uncalibrated) for Brier, log loss and ECE."""
    ids = np.unique(pids)
    groups = [np.flatnonzero(pids == i) for i in ids]
    out = {"brier": [], "log_loss": [], "ece_uniform15": []}
    for _ in range(b):
        idx = np.concatenate([groups[k] for k in rng.integers(0, ids.size, ids.size)])
        yy = y[idx]
        if yy.min() == yy.max():
            continue
        pu, pc = p_un[idx], p_cal[idx]
        out["brier"].append(brier_score_loss(yy, pc) - brier_score_loss(yy, pu))
        out["log_loss"].append(log_loss(yy, np.clip(pc, EPS, 1 - EPS), labels=[0, 1])
                               - log_loss(yy, np.clip(pu, EPS, 1 - EPS), labels=[0, 1]))
        out["ece_uniform15"].append(ece(yy, pc)[0] - ece(yy, pu)[0])
    res = {}
    for k, v in out.items():
        v = np.asarray(v)
        res[k] = {"ci95": [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))],
                  "share_of_resamples_improved": float((v < 0).mean()), "n_resamples": int(v.size)}
    return res


def per_patient(y, p_un, p_cal, pids):
    rows = []
    for i in np.unique(pids):
        m = pids == i
        rows.append({"n": int(m.sum()), "prevalence": round(float(y[m].mean()), 4),
                     "brier_uncalibrated": round(float(brier_score_loss(y[m], p_un[m])), 5),
                     "brier_calibrated": round(float(brier_score_loss(y[m], p_cal[m])), 5),
                     "mean_pred_uncalibrated": round(float(p_un[m].mean()), 4),
                     "mean_pred_calibrated": round(float(p_cal[m].mean()), 4)})
    better = sum(r["brier_calibrated"] < r["brier_uncalibrated"] for r in rows)
    return {"patients_improved_brier": better, "n_patients": len(rows), "rows": rows}


def within_validation_cv(y, p, pids, cal_cls):
    """Leave-one-validation-patient-out: does the calibrator help on held-out VALIDATION patients?"""
    oof = np.empty_like(p)
    for i in np.unique(pids):
        m = pids == i
        oof[m] = cal_cls().fit(p[~m], y[~m]).predict(p[m])
    return {"brier_uncalibrated": float(brier_score_loss(y, p)), "brier_oof_calibrated": float(brier_score_loss(y, oof)),
            "ece_uncalibrated": ece(y, p)[0], "ece_oof_calibrated": ece(y, oof)[0]}


# ----------------------------------------------------------------------------- SVG reliability diagram
def reliability_svg(title, curves, path: Path):
    W, H, L, B, T, R = 460, 420, 56, 50, 34, 16
    pw, ph = W - L - R, H - T - B

    def xy(px, py):
        return L + px * pw, T + (1 - py) * ph

    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
             'font-family="sans-serif" font-size="11">', f'<rect width="{W}" height="{H}" fill="white"/>',
             f'<text x="{W / 2}" y="18" text-anchor="middle" font-size="13">{title}</text>']
    for t in np.linspace(0, 1, 6):
        x0, y0 = xy(t, 0)
        x1, y1 = xy(0, t)
        parts += [f'<line x1="{x0:.1f}" y1="{T}" x2="{x0:.1f}" y2="{T + ph}" stroke="#eee"/>',
                  f'<line x1="{L}" y1="{y1:.1f}" x2="{L + pw}" y2="{y1:.1f}" stroke="#eee"/>',
                  f'<text x="{x0:.1f}" y="{T + ph + 14}" text-anchor="middle">{t:.1f}</text>',
                  f'<text x="{L - 6}" y="{y1 + 4:.1f}" text-anchor="end">{t:.1f}</text>']
    a, b = xy(0, 0), xy(1, 1)
    parts.append(f'<line x1="{a[0]}" y1="{a[1]}" x2="{b[0]}" y2="{b[1]}" stroke="#999" stroke-dasharray="4 3"/>')
    colors = {"uncalibrated": "#c0392b", "platt": "#2471a3", "isotonic": "#1e8449"}
    for i, (name, rows) in enumerate(curves.items()):
        pts = [xy(r["mean_predicted"], r["observed_rate"]) for r in rows]
        c = colors.get(name, "#333")
        parts.append('<polyline fill="none" stroke="{}" stroke-width="1.6" points="{}"/>'.format(
            c, " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)))
        for (x, y), r in zip(pts, rows, strict=True):
            rad = 2 + 3 * min(1.0, (r["n"] / 2000) ** 0.5)
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{rad:.1f}" fill="{c}" fill-opacity="0.7"/>')
        parts.append(f'<rect x="{L + 10}" y="{T + 8 + 16 * i}" width="10" height="10" fill="{c}"/>'
                     f'<text x="{L + 26}" y="{T + 17 + 16 * i}">{name}</text>')
    parts += [f'<text x="{L + pw / 2}" y="{H - 12}" text-anchor="middle">mean predicted probability (15 equal-width bins)</text>',
              f'<text transform="translate(14 {T + ph / 2}) rotate(-90)" text-anchor="middle">observed event rate</text>',
              f'<text x="{W - R - 4}" y="{T + ph - 6}" text-anchor="end" fill="#666" font-size="9.5">test patients; synthetic data; marker area ~ bin n</text>',
              "</svg>"]
    path.write_text("\n".join(parts) + "\n")


# ----------------------------------------------------------------------------- main
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--table-cache", default=None)
    ap.add_argument("--out-dir", default=str(REPO / "reports/research"))
    args = ap.parse_args()
    t0 = time.time()
    rng = np.random.default_rng(SEED)
    committed = json.loads((REPO / "reports/evaluation_report.json").read_text())
    params = {"n_patients": committed["dataset"]["n_patients"], "days": committed["dataset"]["days_per_patient"],
              "seed": committed["dataset"]["seed"]}
    assert params["seed"] == DEFAULT_SEED
    cache = Path(args.table_cache) if args.table_cache else None
    table = pd.read_pickle(cache) if cache and cache.exists() else build_cohort_table(generate_cohort(**params))

    split = {s: table[table.split == s] for s in ("train", "validation", "test")}
    ids = {s: set(d.patient_id) for s, d in split.items()}
    R: dict = {"artifact": "B-07 event-model calibration analysis",
               "status": "research artifact; synthetic data; no clinical calibration claim; production unchanged",
               "event_definition": EVENT_DEFINITION, "cohort_params": params}
    R["splits"] = {
        "patient_disjoint": all(not (ids[a] & ids[b]) for a, b in (("train", "validation"), ("train", "test"), ("validation", "test"))),
        "matches_committed_report": {s: len(split[s]) == committed["dataset"]["split_samples"][s]
                                     and len(ids[s]) == committed["dataset"]["split_patients"][s] for s in split},
    }
    ev = {s: d.dropna(subset=["y_event"]) for s, d in split.items()}
    R["splits"]["event_rows"] = {s: {"n": len(d), "patients": int(d.patient_id.nunique()), "events": int(d.y_event.sum()),
                                     "prevalence": round(float(d.y_event.mean()), 5)} for s, d in ev.items()}
    ytr = ev["train"].y_event.to_numpy().astype(int)
    yva = ev["validation"].y_event.to_numpy().astype(int)
    yte = ev["test"].y_event.to_numpy().astype(int)
    pid_va, pid_te = ev["validation"].patient_id.to_numpy(), ev["test"].patient_id.to_numpy()
    per_pat_events = ev["validation"].groupby("patient_id").y_event.agg(["sum", "size"])
    R["validation_adequacy"] = {
        "n_rows": int(len(yva)), "n_events": int(yva.sum()), "n_patients": int(per_pat_events.shape[0]),
        "events_per_patient_min_median_max": [int(per_pat_events["sum"].min()), float(per_pat_events["sum"].median()),
                                              int(per_pat_events["sum"].max())],
        "note": "Platt has 2 parameters: ample. Isotonic is flexible; rows are autocorrelated (5-min steps) and "
                "clustered in 12 patients, so its effective sample size is far below the row count. Checked with "
                "leave-one-validation-patient-out below (validation labels only).",
    }

    committed_ev = {m["model"]: m for m in committed["event"]}
    out_models = {}
    for M in (LogisticEventModel, GradientBoostingEventModel):
        model = M() if M is LogisticEventModel else M(seed=params["seed"])
        model.fit(ev["train"][FEATURE_NAMES], ytr)
        pva = model.predict_proba(ev["validation"][FEATURE_NAMES])
        pte = model.predict_proba(ev["test"][FEATURE_NAMES])
        c = committed_ev[model.name]
        repro = {"auroc": float(roc_auc_score(yte, pte)), "brier": float(brier_score_loss(yte, pte)),
                 "threshold_validation_max_f1": choose_threshold(yva, pva)}
        repro_ok = (abs(repro["auroc"] - c["auroc"]) < 1e-9 and abs(repro["brier"] - c["brier"]) < 1e-9
                    and repro["threshold_validation_max_f1"] == c["threshold"])
        entry = {"served": model.name == "logistic_regression",
                 "reproduces_committed": {"ok": repro_ok, "refit": repro,
                                          "committed": {"auroc": c["auroc"], "brier": c["brier"], "threshold": c["threshold"]}}}
        if not repro_ok:
            raise SystemExit(f"{model.name}: refit does not reproduce the committed report: {entry}")
        cal_out = {"uncalibrated": {"test": metrics(yte, pte), "validation": metrics(yva, pva)}}
        curves = {"uncalibrated": reliability_table(yte, pte)}
        for C in (Platt, Isotonic):
            cal = C().fit(pva, yva)  # VALIDATION ONLY
            pc = cal.predict(pte)
            thr_u = c["threshold"]
            # alert decisions: a monotone calibrator maps the validation-chosen threshold, so alerts are unchanged
            # if the threshold is mapped; report the agreement explicitly
            mapped = float(cal.predict(np.array([thr_u]))[0])
            agree = float(((pte >= thr_u) == (pc >= mapped)).mean())
            cal_out[C.name] = {
                "params": cal.params(),
                "test": metrics(yte, pc),
                "test_minus_uncalibrated_patient_bootstrap": boot_diffs(yte, pte, pc, pid_te, rng),
                "per_test_patient": per_patient(yte, pte, pc, pid_te),
                "within_validation_leave_one_patient_out": within_validation_cv(yva, pva, pid_va, C),
                "alert_threshold_mapping": {"uncalibrated_threshold": thr_u, "mapped_threshold": mapped,
                                            "test_alert_decision_agreement": agree},
            }
            curves[C.name] = reliability_table(yte, pc)
        cal_out["reliability_tables_test_uniform15"] = curves
        svg = Path(args.out_dir) / f"b07_reliability_{model.name}.svg"
        svg.parent.mkdir(parents=True, exist_ok=True)
        reliability_svg(f"Reliability on test patients: {model.name}", curves, svg)
        entry["calibration"] = cal_out
        # repo-relative when written inside the repository (default); absolute otherwise (e.g. a scratch rerun)
        entry["reliability_diagram"] = str(svg.relative_to(REPO)) if svg.resolve().is_relative_to(REPO) else str(svg)
        out_models[model.name] = entry
    R["models"] = out_models
    R["methods"] = {
        "calibrators_fitted_on": "validation patients only (labels of test patients never used for fitting or selection)",
        "platt": "logistic regression of y on logit(p), C=1e6 (effectively unregularized)",
        "isotonic": "sklearn IsotonicRegression(out_of_bounds='clip'), y in [0, 1]",
        "ece": f"{N_BINS} equal-width bins on [0,1] (primary) and {N_BINS} equal-mass bins (secondary); weighted mean |mean p - observed rate|",
        "uncertainty": f"patient-cluster bootstrap over the 12 test patients, {B_BOOT} resamples, seed {SEED}",
        "calibration_slope_intercept": "descriptive logistic fit on the evaluation set (ideal slope 1, intercept 0)",
    }
    R["reproducibility"] = {"script": "scripts/b07_calibration_analysis.py", "seed": SEED, "bootstrap_reps": B_BOOT}
    out = Path(args.out_dir) / "b07_calibration.json"
    out.write_text(json.dumps(R, indent=2) + "\n")
    print(f"wrote {out} in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
