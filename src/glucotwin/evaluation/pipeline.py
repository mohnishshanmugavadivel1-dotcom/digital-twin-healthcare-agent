"""End-to-end, reproducible train/evaluate pipeline.

Protocol (frozen in docs/ML_PLAN.md):
1. Generate the deterministic synthetic cohort (seed, n_patients, days).
2. Patient-level split 60/20/20 (no patient appears in two splits).
3. Fit every model on TRAIN only.
4. On VALIDATION only: pick the alert threshold (max F1), compute split-conformal
   interval half-widths, and choose the served trajectory model (lowest mean RMSE).
5. Evaluate everything once on TEST and write reports/evaluation_report.json.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from glucotwin.config import FORECAST_HORIZONS_MIN
from glucotwin.contracts import DatasetCard, EvaluationReport, EventMetrics, TrajectoryMetrics
from glucotwin.dataset import build_cohort_table
from glucotwin.evaluation.metrics import choose_threshold, event_metrics, trajectory_metrics
from glucotwin.features import FEATURE_NAMES, split_streams
from glucotwin.labels import EVENT_DEFINITION, excursion_onsets, to_grid
from glucotwin.models.bundle import ModelBundle
from glucotwin.models.forecasting import (
    DampedTrendForecaster,
    GradientBoostingEventModel,
    GradientBoostingForecaster,
    LogisticEventModel,
    PersistenceForecaster,
    RidgeForecaster,
    TrendRuleScorer,
)
from glucotwin.synth.generator import DATASET_NAME, DATASET_VERSION, DEFAULT_SEED, generate_cohort

log = logging.getLogger(__name__)
INTERVAL_LEVEL = 0.8

SPLIT_PROTOCOL = (
    "Patient-level split 60/20/20 (train/validation/test) by seeded permutation; no patient in two splits. "
    "Features use observations <= t only; labels use (t, t+120 min]. Threshold, conformal intervals and "
    "served-model choice are fitted on validation; test is evaluated once."
)


def _onsets(cohort, ids) -> dict[str, pd.DatetimeIndex]:
    return {pid: excursion_onsets(to_grid(split_streams(cohort.patient_observations(pid))["cgm"])) for pid in ids}


def run_pipeline(
    n_patients: int = 60,
    days: int = 14,
    seed: int = DEFAULT_SEED,
    report_path: Path | None = Path("reports/evaluation_report.json"),
    bundle_path: Path | None = Path("artifacts/model_bundle.pkl"),
) -> tuple[EvaluationReport, ModelBundle]:
    cohort = generate_cohort(n_patients=n_patients, days=days, seed=seed)
    table = build_cohort_table(cohort)
    tr, va, te = (table[table["split"] == s] for s in ("train", "validation", "test"))
    X = {k: d[FEATURE_NAMES] for k, d in (("train", tr), ("validation", va), ("test", te))}

    # ---------------- trajectory models
    traj_models = [PersistenceForecaster(), DampedTrendForecaster(), RidgeForecaster(),
                   GradientBoostingForecaster(seed=seed)]
    for m in traj_models:
        m.fit(X["train"], tr)
        log.info("fitted trajectory model %s", m.name)

    def rmse_on(m, frame, Xf):
        pred = m.predict(Xf)
        errs = []
        for h in FORECAST_HORIZONS_MIN:
            y = frame[f"y_glucose_{h}"].to_numpy()
            ok = ~np.isnan(y)
            errs.append(np.sqrt(np.mean((pred[h].to_numpy()[ok] - y[ok]) ** 2)))
        return float(np.mean(errs))

    val_rmse = {m.name: rmse_on(m, va, X["validation"]) for m in traj_models}
    served_traj = min((m for m in traj_models if m.name not in ("persistence",)), key=lambda m: val_rmse[m.name])
    # split-conformal half widths (validation residuals of the served model)
    vpred = served_traj.predict(X["validation"])
    half = {}
    for h in FORECAST_HORIZONS_MIN:
        y = va[f"y_glucose_{h}"].to_numpy()
        ok = ~np.isnan(y)
        res = np.abs(vpred[h].to_numpy()[ok] - y[ok])
        n = res.size
        half[h] = float(np.quantile(res, min(1.0, np.ceil((n + 1) * INTERVAL_LEVEL) / n)))

    traj_metrics = []
    for m in traj_models:
        pred = m.predict(X["test"])
        for h in FORECAST_HORIZONS_MIN:
            y = te[f"y_glucose_{h}"].to_numpy()
            ok = ~np.isnan(y)
            p = pred[h].to_numpy()[ok]
            lo = hi = None
            if m is served_traj:
                lo, hi = p - half[h], p + half[h]
            traj_metrics.append(TrajectoryMetrics(model=m.name, horizon_min=h,
                                                  **trajectory_metrics(y[ok], p, lo, hi)))

    # ---------------- event models
    tr_e, va_e, te_e = (d.dropna(subset=["y_event"]) for d in (tr, va, te))
    ev_models = [TrendRuleScorer(), LogisticEventModel(), GradientBoostingEventModel(seed=seed)]
    for m in ev_models:
        m.fit(tr_e[FEATURE_NAMES], tr_e["y_event"].to_numpy().astype(int))
        log.info("fitted event model %s", m.name)
    thresholds = {
        m.name: choose_threshold(va_e["y_event"].to_numpy().astype(int), m.predict_proba(va_e[FEATURE_NAMES]))
        for m in ev_models
    }
    test_ids = sorted(te["patient_id"].unique())
    onsets = _onsets(cohort, test_ids)
    patient_days = float(len(test_ids) * days)
    ev_metrics = []
    for m in ev_models:
        frame = te_e[["patient_id", "timestamp", "y_event"]].assign(score=m.predict_proba(te_e[FEATURE_NAMES]))
        ev_metrics.append(EventMetrics(model=m.name, **event_metrics(
            frame, "score", thresholds[m.name], onsets, patient_days, is_probability=(m.name != "trend_rule"))))

    served_event = next(m for m in ev_models if m.name == "logistic_regression")
    now = datetime.now(UTC)
    version = f"gt-{DATASET_VERSION}-s{seed}-{now:%Y%m%d%H%M}"
    training_data = f"{DATASET_NAME} v{DATASET_VERSION}, seed {seed}, {int((table.split == 'train').sum())} train rows"
    bundle = ModelBundle(
        model_version=version, trained_at=now, trajectory_model=served_traj, event_model=served_event,
        alert_threshold=thresholds[served_event.name], interval_half_width=half, interval_level=INTERVAL_LEVEL,
        training_data=training_data,
        cohort_params={"n_patients": n_patients, "days": days, "seed": seed},
    )
    split_counts = table.groupby("split")["patient_id"].nunique().to_dict()
    report = EvaluationReport(
        generated_at=now,
        model_version=version,
        dataset=DatasetCard(
            name=DATASET_NAME, version=DATASET_VERSION, seed=seed, is_synthetic=True, n_patients=n_patients,
            days_per_patient=days, split_patients={k: int(v) for k, v in split_counts.items()},
            split_samples={k: int(v) for k, v in table.groupby("split").size().items()},
        ),
        target_definition=EVENT_DEFINITION,
        split_protocol=SPLIT_PROTOCOL,
        trajectory=traj_metrics,
        event=ev_metrics,
        served_models={
            "trajectory": served_traj.name,
            "event": served_event.name,
            "trajectory_selection": f"lowest mean validation RMSE: {', '.join(f'{k}={v:.1f}' for k, v in val_rmse.items())}",
            "event_selection": "logistic regression served for transparent, grouped additive explanations; "
                               "alternatives reported for comparison",
        },
        notes=[
            "All patients are synthetic; metrics describe the simulator, not real-world performance.",
            "Glucose targets are the simulated CGM (with sensor noise), i.e. what a clinician would see.",
            f"Alert thresholds chosen on validation (max F1): {thresholds}.",
            f"Prediction intervals: split-conformal, nominal {INTERVAL_LEVEL:.0%}, fitted on validation residuals.",
        ],
    )
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report.model_dump_json(indent=2))
        log.info("wrote %s", report_path)
    if bundle_path:
        bundle.save(bundle_path)
    return report, bundle
