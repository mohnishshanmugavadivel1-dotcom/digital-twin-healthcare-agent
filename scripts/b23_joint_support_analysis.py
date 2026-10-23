"""B-23 analysis: joint training support for what-if meal scenarios.

Reproducible, read-only with respect to protected artifacts: it loads the served model bundle,
regenerates the bundle's cohort, rebuilds the feature table and writes ONE new file
(default ``reports/research/b23_joint_support.json``) holding the evidence and the fitted
joint-support model. Fitting uses train-patient rows only; thresholds use validation-patient
rows only; test-patient rows are used only to measure false-warning rates and for a descriptive
error association (never for fitting or threshold choice).

    .venv/bin/python scripts/b23_joint_support_analysis.py [--bundle artifacts/model_bundle.pkl]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.neighbors import NearestNeighbors

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from glucotwin.dataset import build_cohort_table  # noqa: E402
from glucotwin.joint_support import (  # noqa: E402
    COORDS,
    JOINT_FEATURES,
    REASON_COORDS,
    apply_meal_now,
    cohort_meal_event_rows,
    coords_frame,
    fit_joint_support,
)
from glucotwin.joint_support_research import conformal_threshold, mahalanobis, stable_precision, stat_coords  # noqa: E402
from glucotwin.models.bundle import ModelBundle  # noqa: E402
from glucotwin.synth.generator import generate_cohort  # noqa: E402

ALPHAS = (0.01, 0.05)
MEAL_GRID = (10, 20, 30, 45, 60, 90, 120, 150, 180, 240, 300)
B_BOOT = 2000
B_REFIT = 200
KNN_K = 10
SEED = 20261021


def q(s, ps=(0, 1, 5, 25, 50, 75, 95, 99, 100)) -> dict:
    s = np.asarray(s, float)
    return {f"p{p}": round(float(np.percentile(s, p)), 3) for p in ps} | {
        "mean": round(float(s.mean()), 3), "sd": round(float(s.std(ddof=1)), 3), "n": int(s.size)}


def whatif(base: pd.DataFrame, g: float) -> pd.DataFrame:
    """Analytic meal-now scenario at each baseline row (verified against the engine in tests)."""
    return apply_meal_now(base, g).assign(patient_id=base["patient_id"])


def cluster_boot_rate(flags: np.ndarray, pids: np.ndarray, rng, b=B_BOOT) -> dict:
    ids = np.unique(pids)
    by = {p: flags[pids == p] for p in ids}
    sums = np.array([by[p].sum() for p in ids], float)
    ns = np.array([by[p].size for p in ids], float)
    rates = []
    for _ in range(b):
        k = rng.integers(0, ids.size, ids.size)
        rates.append(sums[k].sum() / ns[k].sum())
    per_patient = sums / ns
    return {"rate": round(float(flags.mean()), 4), "n_rows": int(flags.size), "n_patients": int(ids.size),
            "ci95_patient_bootstrap": [round(float(np.percentile(rates, 2.5)), 4), round(float(np.percentile(rates, 97.5)), 4)],
            "per_patient_rate_max": round(float(per_patient.max()), 4),
            "patients_with_any_flag": int((sums > 0).sum())}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", default=str(REPO / "artifacts/model_bundle.pkl"))
    ap.add_argument("--out", default=str(REPO / "reports/research/b23_joint_support.json"))
    ap.add_argument("--table-cache", default=None, help="optional pickle of the cohort table (speed only)")
    args = ap.parse_args()
    t_start = time.time()
    rng = np.random.default_rng(SEED)

    bundle = ModelBundle.load(Path(args.bundle))
    cache = Path(args.table_cache) if args.table_cache else None
    cohort = generate_cohort(**bundle.cohort_params)
    if cache and cache.exists():
        table = pd.read_pickle(cache)
    else:
        table = build_cohort_table(cohort)
    n_train_all = int((table.split == "train").sum())
    fp_ok = bundle.training_data.endswith(f"{n_train_all} train rows")
    if not fp_ok:
        raise SystemExit(f"table does not match bundle training data ({bundle.training_data!r})")
    split = {s: table[table.split == s] for s in ("train", "validation", "test")}
    fresh = {s: cohort_meal_event_rows(cohort, s) for s in split}
    n_events = {s: int((cohort.observations.kind == "meal")[cohort.observations.patient_id.isin(
        [r.patient_id for r in cohort.records if r.split == s])].sum()) for s in split}
    tr, va, te = fresh["train"], fresh["validation"], fresh["test"]
    R: dict = {
        "artifact": "B-23 joint training-support analysis",
        "status": "research artifact; synthetic data; not a clinical or OOD guarantee",
        "bundle": {"model_version": bundle.model_version, "training_data": bundle.training_data,
                   "cohort_params": bundle.cohort_params},
        "reference_population": "every logged meal of the split, with the joint inputs evaluated at the instant "
                                "it was logged (glucotwin.joint_support.meal_event_rows; same formulas as "
                                "features.py). Every what-if scenario is a meal-now situation. Format 2 used feature "
                                "rows < 5 min after a meal and silently dropped meals followed by a CGM dropout.",
        "logged_meal_events": n_events,
        "features": list(JOINT_FEATURES),
        "identity_checked": {},
    }
    # identity: expected_meal_rise == carb_sensitivity * carbs_on_board
    all_rows = table[table.carbs_on_board > 0]
    resid = (all_rows.expected_meal_rise - all_rows.carb_sensitivity * all_rows.carbs_on_board).abs()
    R["identity_checked"]["expected_meal_rise_equals_sensitivity_x_cob_max_abs_error"] = float(resid.max())

    # ---------------------------------------------------------------- descriptive
    R["fresh_meal_rows"] = {s: {"n_rows": len(d), "n_patients": int(d.patient_id.nunique()),
                                "missing_or_nonfinite": int((~np.isfinite(d[list(JOINT_FEATURES)].to_numpy(float))).sum())}
                            for s, d in fresh.items()}
    sens_tr = tr.expected_meal_rise / tr.carbs_on_board
    R["train_marginals"] = {c: q(tr[c]) for c in JOINT_FEATURES} | {"carb_sensitivity": q(sens_tr)}
    R["constraints"] = {}
    for s, d in fresh.items():
        R["constraints"][s] = {
            "share_carbs_60_eq_carbs_30": round(float(np.isclose(d.carbs_60, d.carbs_30).mean()), 4),
            "share_carbs_120_eq_carbs_30": round(float(np.isclose(d.carbs_120, d.carbs_30).mean()), 4),
            "rows_prior_carbs_30_60_gt0": int(((d.carbs_60 - d.carbs_30) > 0.5).sum()),
            "rows_prior_carbs_60_120_gt0": int(((d.carbs_120 - d.carbs_60) > 0.5).sum()),
            "older_carbs_on_board": q(d.carbs_on_board - d.carbs_30),
        }
    X5 = tr[list(JOINT_FEATURES)].to_numpy(float)
    corr5 = np.corrcoef(X5.T)
    ev = np.linalg.eigvalsh(np.cov(X5.T))
    evs = np.linalg.eigvalsh(np.corrcoef(X5.T))
    z_tr = stat_coords(tr)
    R["conditioning"] = {
        "raw5_correlation": {f"{a}|{b}": round(float(corr5[i, j]), 4) for i, a in enumerate(JOINT_FEATURES)
                             for j, b in enumerate(JOINT_FEATURES) if j > i},
        "raw5_cov_eigenvalues": [float(f"{x:.4g}") for x in ev],
        "raw5_standardized_eigenvalues": [float(f"{x:.4g}") for x in evs],
        "raw5_condition_number": float(f"{abs(ev.max() / ev.min()) if ev.min() != 0 else float('inf'):.4g}"),
        "stat2_correlation": {s: round(float(np.corrcoef(stat_coords(d).T)[0, 1]), 4) for s, d in fresh.items()},
        "stat2_condition_number": round(float(np.linalg.cond(np.cov(z_tr.T))), 3),
    }

    # what-if sweep baselines: test-patient rows every 30 min with finite inputs
    te_all = split["test"]
    base = te_all[pd.to_datetime(te_all["timestamp"]).dt.minute.isin((0, 30)).to_numpy()]
    base = base[np.isfinite(base[list(JOINT_FEATURES) + ["carb_sensitivity"]].to_numpy(float)).all(axis=1)]
    sweeps = {g: whatif(base, g) for g in MEAL_GRID}

    # ---------------------------------------------------------------- rejected: raw 5-D ridge Mahalanobis
    mu5, C5 = X5.mean(0), np.cov(X5.T)
    Xv5 = va[list(JOINT_FEATURES)].to_numpy(float)
    W60 = sweeps[60][list(JOINT_FEATURES)].to_numpy(float)
    ridge = []
    for lam in (1e-8, 1e-6, 1e-4, 1e-2, 1e-1, 1.0):
        P = np.linalg.inv(C5 + lam * np.trace(C5) / 5 * np.eye(5))

        def md(X, P=P):
            d = X - mu5
            return np.sqrt(np.einsum("ij,jk,ik->i", d, P, d))
        thr = conformal_threshold(md(Xv5), 0.01)
        ridge.append({"ridge_lambda": lam, "threshold": round(thr, 3), "share_60g_whatifs_flagged": round(float((md(W60) > thr).mean()), 4)})
    R["rejected_raw5_ridge_mahalanobis"] = {
        "note": "threshold = split-conformal alpha=0.01 on validation fresh-meal rows; verdicts depend on the arbitrary ridge constant",
        "sweep": ridge}

    # ---------------------------------------------------------------- shipped: exact training envelope
    model = fit_joint_support(tr, bundle.training_data)
    pid_te = te.patient_id.to_numpy()
    f_va, f_te = model.flags(coords_frame(va)), model.flags(coords_frame(te))
    R["shipped_envelope"] = {
        "method": "a scenario is 'no training analogue' when any decorrelated coordinate lies outside the range "
                  "observed on meal-now training rows (+ small tolerance); no tuned threshold",
        "coordinates": list(COORDS),
        "reason_coordinates": list(REASON_COORDS),
        "design_change_disclosure": "carb_sensitivity was initially also a reason (outside training [min, max]). After "
                                    "seeing that it flagged one TEST patient whose sensitivity (0.846) is 0.002 below the "
                                    "training minimum (0.848), it was removed as a reason because a what-if meal does not "
                                    "change it (patient-level, not scenario-level). This choice was informed by test data, "
                                    "so the test flag rates below are not fully untouched evidence.",
        "rule_selection_disclosure": [
            "The bounds are fitted on training meals only and no threshold was tuned on test outcomes, but the rule "
            "design was not chosen blind to held-out data:",
            "the calibrated 2-D Mahalanobis/kNN alternative was rejected partly because of its false-warning rate on "
            "TEST patients;",
            "carb_sensitivity was removed as a reason after a TEST boundary flag was seen (see above);",
            "the raw 5-D Mahalanobis demonstration used VALIDATION rows;",
            "the reference set changed from CGM feature rows (format 2, which silently missed 25 training meals) to every "
            "logged training meal event (format 3) after the format-2 validation/test rates had been seen. The change "
            "was prompted by a code review of training-data coverage, not by outcomes, and the coordinates and "
            "tolerances were not changed.",
            "Therefore the validation/test flag rates are not untouched held-out estimates of the final rule.",
        ],
        "timing_behaviour": "The check is non-monotonic in time since the last logged meal: a meal < 30 min after "
                            "another merges into 'meal now' (carbs_30), so it is flagged only if the combined grams or "
                            "expected rise exceed training; 30-60 min after a meal it is always flagged (no training "
                            "meal had a meal 30-60 min before it, prior_carbs_30_60 max = 0, reflecting the synthetic "
                            "generator's meal schedule); 60-120 min after, it depends on the earlier meal's size. "
                            "This is accurate about training support but says nothing specific about forecast error.",
        "training_range": {k: [round(model.lo[k], 3), round(model.hi[k], 3)] for k in COORDS},
        "sparse_above_p99": {k: round(v, 3) for k, v in model.sparse_above.items()},
        "expected_exceedance_if_exchangeable": "for one coordinate, a new exchangeable row exceeds the training max "
                                               f"with probability 1/(n+1) = {1 / (len(tr) + 1):.5f}; rows are clustered "
                                               "by patient, so measured rates on new patients are the relevant evidence",
        "validation_real_meals_flag_rate": cluster_boot_rate(f_va.any(axis=1).to_numpy(), va.patient_id.to_numpy(), rng),
        "test_real_meals_flag_rate": cluster_boot_rate(f_te.any(axis=1).to_numpy(), pid_te, rng),
        "test_real_meals_by_reason": {k: int(v) for k, v in f_te.sum().items()},
        "validation_real_meals_by_reason": {k: int(v) for k, v in f_va.sum().items()},
    }
    # stability of the envelope: refit on bootstrap resamples of TRAIN patients
    tr_ids = tr.patient_id.unique()
    tr_g = dict(tuple(tr.groupby("patient_id")))
    Wc = {g: coords_frame(sweeps[g]) for g in (30, 60, 120)}
    ref = {g: model.flags(Wc[g]).any(axis=1).to_numpy() for g in Wc}
    flips = []
    for _ in range(B_REFIT):
        bm = fit_joint_support(pd.concat([tr_g[p] for p in rng.choice(tr_ids, tr_ids.size)]), bundle.training_data)
        flips.append(np.mean([(bm.flags(Wc[g]).any(axis=1).to_numpy() != ref[g]).mean() for g in Wc]))
    R["shipped_envelope"]["stability_train_patient_bootstrap"] = {
        "n_refits": B_REFIT, "mean_verdict_flip_rate_on_whatifs": round(float(np.mean(flips)), 4),
        "p95_verdict_flip_rate": round(float(np.percentile(flips, 95)), 4), "whatif_sizes_used": list(Wc)}

    # ---------------------------------------------------------------- evaluated, not shipped: calibrated 2-D distance
    z_tr, zv, zt = stat_coords(tr), stat_coords(va), stat_coords(te)
    mean, prec, shrink, cond = stable_precision(z_tr)
    sd = z_tr.std(0, ddof=1)
    nn = NearestNeighbors(n_neighbors=KNN_K).fit(z_tr / sd)

    def knn_score(z, nn=nn, sd=sd):
        return nn.kneighbors(z / sd)[0][:, -1]

    stat = {"coordinates": ["log carbs_30", "log(expected_meal_rise / carbs_on_board)"],
            "ledoit_wolf_shrinkage": round(shrink, 5), "condition_number": round(cond, 3),
            "patient_level_calibration": {
                "n_validation_patients": int(va.patient_id.nunique()),
                "note": "carb sensitivity is a per-patient trait, so rows of a new patient are not exchangeable with "
                        "calibration rows. Patient-level split conformal at alpha needs ceil((m+1)(1-alpha)) <= m "
                        "patients: with m=12 the smallest feasible alpha is 1/13 = 0.077."}}
    for alpha in ALPHAS:
        mt = conformal_threshold(mahalanobis(zv, mean, prec), alpha)
        kt = conformal_threshold(knn_score(zv), alpha)
        m_te, k_te = mahalanobis(zt, mean, prec) > mt, knn_score(zt) > kt
        per_pat = (pd.DataFrame({"pid": pid_te, "flag": m_te,
                                 "sens": coords_frame(te).carb_sensitivity.to_numpy()})
                   .groupby("pid").agg(flag_rate=("flag", "mean"), median_sens=("sens", "median"), n=("flag", "size")))
        # stability under patient-bootstrap refits of train AND validation
        va_ids = va.patient_id.unique()
        va_g = dict(tuple(va.groupby("patient_id")))
        W = {g: stat_coords(sweeps[g]) for g in (30, 60, 120)}
        ref_m = {g: mahalanobis(W[g], mean, prec) > mt for g in W}
        ref_k = {g: knn_score(W[g]) > kt for g in W}
        thr_m, thr_k, flip_m, flip_k = [], [], [], []
        for _ in range(B_REFIT):
            btr = pd.concat([tr_g[p] for p in rng.choice(tr_ids, tr_ids.size)])
            bva = pd.concat([va_g[p] for p in rng.choice(va_ids, va_ids.size)])
            zb = stat_coords(btr)
            bmean, bprec, _, _ = stable_precision(zb)
            bmt = conformal_threshold(mahalanobis(stat_coords(bva), bmean, bprec), alpha)
            sdb = zb.std(0, ddof=1)
            nnb = NearestNeighbors(n_neighbors=KNN_K).fit(zb / sdb)
            bkt = conformal_threshold(nnb.kneighbors(stat_coords(bva) / sdb)[0][:, -1], alpha)
            thr_m.append(bmt)
            thr_k.append(bkt)
            flip_m.append(np.mean([((mahalanobis(W[g], bmean, bprec) > bmt) != ref_m[g]).mean() for g in W]))
            flip_k.append(np.mean([((nnb.kneighbors(W[g] / sdb)[0][:, -1] > bkt) != ref_k[g]).mean() for g in W]))
        stat[f"alpha_{alpha}"] = {
            "mahalanobis_threshold": round(mt, 4), f"knn_k{KNN_K}_threshold": round(kt, 4),
            "validation_flag_rate_mahalanobis": round(float((mahalanobis(zv, mean, prec) > mt).mean()), 4),
            "test_flag_rate_mahalanobis": cluster_boot_rate(m_te, pid_te, rng),
            f"test_flag_rate_knn_k{KNN_K}": cluster_boot_rate(k_te, pid_te, rng),
            "test_per_patient_mahalanobis": [{"flag_rate": round(float(r.flag_rate), 3),
                                              "median_sensitivity": round(float(r.median_sens), 3), "n": int(r.n)}
                                             for r in per_pat.sort_values("flag_rate", ascending=False).itertuples()],
            "stability_patient_bootstrap_refit": {
                "n_refits": B_REFIT,
                "mahalanobis_threshold_p5_p95": [round(float(np.percentile(thr_m, 5)), 3), round(float(np.percentile(thr_m, 95)), 3)],
                "knn_threshold_p5_p95": [round(float(np.percentile(thr_k, 5)), 3), round(float(np.percentile(thr_k, 95)), 3)],
                "mahalanobis_mean_verdict_flip_rate_on_whatifs": round(float(np.mean(flip_m)), 4),
                "knn_mean_verdict_flip_rate_on_whatifs": round(float(np.mean(flip_k)), 4)},
        }
    stat["training_patient_median_sensitivity_range"] = [
        round(float(v), 3) for v in coords_frame(tr).groupby(tr.patient_id.to_numpy()).carb_sensitivity.median().agg(["min", "max"])]
    R["evaluated_not_shipped_calibrated_2d_distance"] = stat

    # ---------------------------------------------------------------- what-if sweep with the shipped envelope
    sweep_out = {}
    for g, w in sweeps.items():
        f = model.flags(coords_frame(w))
        anyf = f.any(axis=1)
        joint_only = f[[c for c in f.columns if not c.startswith("meal_carbs")]].any(axis=1)
        marg = f[[c for c in f.columns if c.startswith("meal_carbs")]].any(axis=1)
        per_pat = anyf.groupby(w.patient_id.to_numpy()).mean()
        sweep_out[str(g)] = {"n": len(w), "flagged": round(float(anyf.mean()), 4),
                             "flagged_by_joint_coordinate_only": round(float((joint_only & ~marg).mean()), 4),
                             "by_reason": {k: round(float(v), 4) for k, v in f.mean().items() if v > 0},
                             "per_patient_flagged_min_max": [round(float(per_pat.min()), 3), round(float(per_pat.max()), 3)]}
    R["whatif_sweep_test_patients"] = {
        "baselines": "test-patient feature rows at :00 and :30 with finite inputs; analytic meal-now transform "
                     "(carbs_30/60/120 and COB + g; expected_meal_rise = carb_sensitivity x new COB), verified "
                     "against the engine in tests/test_joint_support.py",
        "n_baselines": len(base), "by_meal_grams": sweep_out}

    # ---------------------------------------------------------------- constructed cases (synthetic rows)
    med = float(coords_frame(tr).carb_sensitivity.median())
    cases = [("typical: 60 g meal now, median sensitivity", dict(c30=60, c60=60, c120=60, cob=60, s=med)),
             ("each input in range, jointly unusual: 60 g now after a 40 g meal 45 min ago", dict(c30=60, c60=100, c120=100, cob=100 - 40 * 45 / 180, s=med)),
             ("meal size and sensitivity each in training range, product (expected_meal_rise) above max: 190 g at sensitivity 2.1", dict(c30=190, c60=190, c120=190, cob=190, s=2.1)),
             ("each input in range, jointly unusual: 50 g now with 45 g older carbs on board", dict(c30=50, c60=50, c120=95, cob=95, s=med)),
             ("marginally outside: 260 g", dict(c30=260, c60=260, c120=260, cob=260, s=med))]
    out_cases = []
    for label, c in cases:
        row = {"carbs_30": c["c30"], "carbs_60": c["c60"], "carbs_120": c["c120"], "carbs_on_board": c["cob"],
               "expected_meal_rise": c["s"] * c["cob"]}
        in_marg = {k: bool(tr[k].min() <= row[k] <= tr[k].max()) for k in JOINT_FEATURES}
        a = model.assess(row)
        out_cases.append({"case": label, "inputs": {k: round(float(v), 2) for k, v in row.items()},
                          "each_input_within_training_marginal_range": in_marg,
                          "status": a["status"], "reasons": a["reasons"]})
    R["constructed_cases"] = out_cases

    # ---------------------------------------------------------------- descriptive: flags vs served-model error
    # forecasts actually issued within 5 min after a logged meal (CGM rows; they carry targets). The reference
    # population above is meal events, which have no forecast of their own.
    te_rows = split["test"][(split["test"].minutes_since_meal < 5) & (split["test"].carbs_30 > 0)]
    pred = bundle.trajectory_model.predict(te_rows[bundle.feature_names])
    flag_te = model.flags(coords_frame(te_rows)).any(axis=1).to_numpy()
    dist_te = mahalanobis(stat_coords(te_rows), mean, prec)
    assoc = {}
    for h in (60, 120):
        y = te_rows[f"y_glucose_{h}"].to_numpy()
        ok = ~np.isnan(y)
        err = np.abs(pred[h].to_numpy()[ok] - y[ok])
        rho, p = spearmanr(dist_te[ok], err)
        assoc[str(h)] = {"n": int(ok.sum()), "n_flagged": int(flag_te[ok].sum()),
                         "mae_envelope_flagged": round(float(err[flag_te[ok]].mean()), 2) if flag_te[ok].any() else None,
                         "mae_envelope_not_flagged": round(float(err[~flag_te[ok]].mean()), 2),
                         "spearman_rho_2d_distance_vs_abs_error": round(float(rho), 3), "p_value": float(f"{p:.3g}")}
    R["descriptive_error_association_test_real_meals"] = {
        "rows": "test-patient forecasts issued < 5 min after a logged meal (minutes_since_meal < 5)",
        "note": "test labels used descriptively only, after every fitting/threshold choice; tiny flagged n; "
                "rows are patient-clustered, so p-values are optimistic",
        "by_horizon_min": assoc}

    R["model"] = model.to_dict()
    R["reproducibility"] = {"script": "scripts/b23_joint_support_analysis.py", "seed": SEED,
                            "bootstrap_reps": B_BOOT, "refit_reps": B_REFIT,
                            "model_sha256": hashlib.sha256(json.dumps(model.to_dict(), sort_keys=True).encode()).hexdigest()}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(R, indent=2) + "\n")
    print(f"wrote {out} in {time.time() - t_start:.1f}s")


if __name__ == "__main__":
    main()
