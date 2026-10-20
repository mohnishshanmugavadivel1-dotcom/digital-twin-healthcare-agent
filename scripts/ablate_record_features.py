"""WS1 experiment: why do direct historical-record (EHR) features hurt held-out AUROC?

Reproduces the wave-2 audit ablation (record features removed: event AUROC 0.884 -> 0.907)
on the SAME patient-level split with the SAME model class and protocol, and adds the
analysis the headline number lacked: standardized logistic coefficients, per-group
test discrimination, and a patient-bootstrap CI for the with-vs-without difference.

Protocol (identical to evaluation/pipeline.py; nothing here tunes on test):
  * features from build_cohort_table (leakage-safe, observations <= t only)
  * LogisticEventModel fitted on TRAIN rows (y_event)
  * alert threshold chosen on VALIDATION (max F1)
  * TEST evaluated exactly once per variant
  * 1000 patient-level bootstrap resamples for the AUROC difference CI

This script is evidence, not a model change: the served model is untouched unless a
reproducible validation improvement says otherwise (it does not; see the report).

Usage: .venv/bin/python scripts/ablate_record_features.py [--n 60] [--days 14] [--seed 20261017]
"""

from __future__ import annotations

import argparse
import json

import numpy as np
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

from glucotwin.dataset import build_cohort_table
from glucotwin.evaluation.metrics import choose_threshold
from glucotwin.features import EHR_FEATURES, FEATURE_NAMES
from glucotwin.models.forecasting import LogisticEventModel
from glucotwin.synth.generator import DEFAULT_SEED, generate_cohort

BOOTSTRAP = 1000


def fit_and_score(train, val, test, features: list[str]) -> dict:
    """Fit logistic on train, threshold on val (max F1), score test once."""
    tr_e, va_e, te_e = (d.dropna(subset=["y_event"]) for d in (train, val, test))
    model = LogisticEventModel()
    model.fit(tr_e[features], tr_e["y_event"].to_numpy().astype(int))
    thr = choose_threshold(va_e["y_event"].to_numpy().astype(int),
                           model.predict_proba(va_e[features]))
    score = model.predict_proba(te_e[features])
    y = te_e["y_event"].to_numpy().astype(int)
    val_auroc = float(roc_auc_score(va_e["y_event"].to_numpy().astype(int), model.predict_proba(va_e[features])))
    pred = (score >= thr).astype(int)
    tn = int(((pred == 0) & (y == 0)).sum())
    tp = int(((pred == 1) & (y == 1)).sum())
    fp = int(((pred == 1) & (y == 0)).sum())
    fn = int(((pred == 0) & (y == 1)).sum())
    return {
        "features": features,
        "threshold": round(float(thr), 4),
        "val_auroc": round(val_auroc, 4),
        "n_test_rows": int(len(te_e)),
        "auroc": round(float(roc_auc_score(y, score)), 4),
        "auprc": round(float(average_precision_score(y, score)), 4),
        "brier": round(float(brier_score_loss(y, score)), 4),
        "sensitivity": round(tp / (tp + fn), 4),
        "specificity": round(tn / (tn + fp), 4),
        "scores": score, "y": y, "pids": te_e["patient_id"].to_numpy(), "model": model,
    }


def patient_bootstrap_auc_delta(res_with: dict, res_without: dict, rng: np.ndarray) -> dict:
    """95% CI for AUROC(with) - AUROC(without) over patient-level resamples of the TEST rows."""
    pids = res_with["pids"]
    assert (pids == res_without["pids"]).all(), "test rows must be aligned between variants"
    uniq = np.unique(pids)
    y, sw, so = res_with["y"], res_with["scores"], res_without["scores"]
    deltas, aw, ao = [], [], []
    for _ in range(BOOTSTRAP):
        take = rng.choice(uniq, size=uniq.size, replace=True)
        idx = np.concatenate([np.flatnonzero(pids == p) for p in take])
        aw.append(roc_auc_score(y[idx], sw[idx]))
        ao.append(roc_auc_score(y[idx], so[idx]))
        deltas.append(aw[-1] - ao[-1])
    q = np.quantile
    return {
        "auroc_with_mean": round(float(np.mean(aw)), 4),
        "auroc_without_mean": round(float(np.mean(ao)), 4),
        "delta_mean": round(float(np.mean(deltas)), 4),
        "delta_ci95": [round(float(q(deltas, 0.025)), 4), round(float(q(deltas, 0.975)), 4)],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = ap.parse_args()

    cohort = generate_cohort(n_patients=args.n, days=args.days, seed=args.seed)
    table = build_cohort_table(cohort)
    train = table[table["split"] == "train"]
    val = table[table["split"] == "validation"]
    test = table[table["split"] == "test"]
    dyn = [f for f in FEATURE_NAMES if f not in EHR_FEATURES]

    res_with = fit_and_score(train, val, test, list(FEATURE_NAMES))
    res_without = fit_and_score(train, val, test, dyn)
    rng = np.random.default_rng(args.seed)
    boot = patient_bootstrap_auc_delta(res_with, res_without, rng)

    # Standardized coefficients of the with-record model: which static features carry weight?
    mdl = res_with["model"]
    coefs = mdl.model_.coef_  # logistic coefficients on standardized features
    sd = np.sqrt(mdl.scaler_.var_)
    order = np.argsort(-np.abs(coefs[0] * sd))
    coef_table = [{"feature": FEATURE_NAMES[i], "std_coef": round(float(coefs[0][i] * sd[i]), 4)}
                  for i in order if FEATURE_NAMES[i] in EHR_FEATURES]

    out = {
        "seed": args.seed, "n_patients": args.n, "days": args.days,
        "protocol": "patient-level split; logistic fitted on train; threshold (max F1) on validation; test scored once",
        "with_record_features": {k: v for k, v in res_with.items() if k not in ("scores", "y", "pids", "model")},
        "without_record_features": {k: v for k, v in res_without.items() if k not in ("scores", "y", "pids", "model")},
        "patient_bootstrap": boot,
        "record_feature_std_coefs": coef_table,
    }
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
