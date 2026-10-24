"""Twin and What-If validation, addendum v2 (post-hoc / exploratory).

Protocol: experiments/twin_validity/protocol_addendum_v2.json (written before this script was run).
Synthetic simulator cohort only; frozen served models; no change to served behaviour.

Outputs reports/research/twin_and_whatif_validation.json and reports/research/TWIN_AND_WHATIF_VALIDATION.md.
v1 results (reports/research/twin_validity.json) are collated unchanged.

    .venv/bin/python scripts/validate_twin_and_whatif.py [--cache /tmp/wi2.json]
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from glucotwin.dataset import build_patient_table
from glucotwin.features import (
    FEATURE_NAMES,
    carb_sensitivity_prior,
    meal_responses,
    personal_carb_sensitivity,
    split_streams,
)
from glucotwin.labels import to_grid
from glucotwin.models.bundle import ModelBundle
from glucotwin.service import TwinService
from glucotwin.synth.generator import generate_cohort
from glucotwin.twin_validity_research import paired_meal_delta, reconstruct

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("tv1", REPO / "scripts/twin_validity_analysis.py")
v1 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(v1)
r3, ci, minutes, OFFSETS_H = v1.r3, v1.ci, v1.minutes, v1.OFFSETS_H
# Bootstrap as registered in protocol_addendum_v2.json / v3: 1,000 patient resamples, seed 20261017.
# (Until 2026-10-23 this line imported v1's BOOT=2000 / SEED=20261023; see "deviations" in the report.)
SEED, BOOT = 20261017, 1000

GRAMS_B = (20, 40, 60, 90, 120)
GRAMS_PRESET = (25, 35, 36, 45, 50)
ALL_G = tuple(sorted(set(GRAMS_B) | set(GRAMS_PRESET)))
HORIZONS = (30, 60, 120)
POST_MEAL_H = (60, 120)
DIRECTION_MIN = 2.0
PROTOCOL = "experiments/twin_validity/protocol_addendum_v2.json"


def draws_for(ids: list[str]) -> list[np.ndarray]:
    rng = np.random.default_rng(SEED)
    return [rng.choice(ids, size=len(ids), replace=True) for _ in range(BOOT)]


# ----------------------------------------------------------------------------- A: post-meal ablation
def post_meal_ablation(bundle, tables) -> dict:
    te = pd.concat(tables.values(), ignore_index=True)
    te = te[te["carbs_60"] >= 10].reset_index(drop=True)
    X = te[FEATURE_NAMES]
    Xa = X.copy()
    p = te["prior"].to_numpy()
    Xa["carb_sensitivity"] = p
    Xa["expected_meal_rise"] = p * te["carbs_on_board"].to_numpy()
    pids = te["patient_id"].to_numpy()
    ids = sorted(set(pids))
    draws = draws_for(ids)
    pred = {"served": bundle.trajectory_model.predict(X), "ablated": bundle.trajectory_model.predict(Xa)}
    out = {
        "rows_definition": "test rows with carbs_60 >= 10 g and an observed target",
        "n_test_patients": len(ids),
        "by_horizon": {},
    }
    for h in POST_MEAL_H:
        y = te[f"y_glucose_{h}"].to_numpy()
        ok = ~np.isnan(y)
        err = {arm: pr[h].to_numpy()[ok] - y[ok] for arm, pr in pred.items()}
        df = pd.DataFrame(
            {
                "pid": pids[ok],
                "se_s": err["served"] ** 2,
                "se_a": err["ablated"] ** 2,
                "ae_s": np.abs(err["served"]),
                "ae_a": np.abs(err["ablated"]),
            }
        )
        agg = df.groupby("pid").agg(["sum", "count"])
        res = {"n_rows": int(ok.sum())}
        for name, s_col, a_col, f in (
            ("rmse", "se_s", "se_a", np.sqrt),
            ("mae", "ae_s", "ae_a", lambda x: x),
        ):
            served = float(f(df[s_col].mean()))
            abl = float(f(df[a_col].mean()))
            diffs = []
            for d in draws:
                sub = agg.loc[d]
                n = sub[(s_col, "count")].sum()
                diffs.append(f(sub[(a_col, "sum")].sum() / n) - f(sub[(s_col, "sum")].sum() / n))
            res[name] = {
                "served": r3(served),
                "ablated": r3(abl),
                "ablated_minus_served": r3(abl - served),
                "ci95_patient_bootstrap": ci(diffs),
            }
        out["by_horizon"][str(h)] = res
    return out


# ----------------------------------------------------------------------------- C: observed response curve
def observed_curve(cohort, train_ids: set[str]) -> dict:
    fr = {h: [] for h in HORIZONS}
    ratios = []
    for rec in cohort.records:
        if rec.patient_id not in train_ids:
            continue
        streams = split_streams(cohort.patient_observations(rec.patient_id))
        grid = to_grid(streams["cgm"])
        resp = meal_responses(grid, streams["meal"])
        ratios += list(resp["ratio"])
        for t, carbs, ratio in zip(resp["meal_time"], resp["carbs"], resp["ratio"], strict=True):
            peak = ratio * carbs
            if peak < 5:
                continue
            pre = grid.loc[:t].dropna()
            for h in HORIZONS:
                post = grid.loc[: t + pd.Timedelta(minutes=h)].dropna()
                if post.empty or (t + pd.Timedelta(minutes=h) - post.index[-1]) > pd.Timedelta(minutes=10):
                    continue
                fr[h].append((float(post.iloc[-1]) - float(pre.iloc[-1])) / peak)
    return {
        "c": {h: float(np.median(v)) for h, v in fr.items()},
        "c_mean": {h: float(np.mean(v)) for h, v in fr.items()},
        "n_meals": {h: len(v) for h, v in fr.items()},
        "S": float(np.median(ratios)),
        "n_ratio_meals": len(ratios),
    }


# ----------------------------------------------------------------------------- scoring
def score(df: pd.DataFrame, arms: tuple[str, ...], contrast: str, draws) -> dict:
    res = {
        "n_scenarios": int(len(df)),
        "n_patients": int(df["pid"].nunique()),
        "mean_true_delta": r3(df["true"].mean()),
        "true_delta_range": [r3(df["true"].min()), r3(df["true"].max())],
        "share_true_delta_positive": r3((df["true"] > 0).mean()),
    }
    big = df["true"].abs() >= DIRECTION_MIN
    for k in arms:
        err = df[k] - df["true"]
        res[k] = {
            "mae": r3(err.abs().mean()),
            "median_ae": r3(err.abs().median()),
            "bias": r3(err.mean()),
            "spearman_rho": r3(spearmanr(df[k], df["true"])[0]) if df[k].nunique() > 1 else None,
            "direction_accuracy": r3((np.sign(df.loc[big, k]) == np.sign(df.loc[big, "true"])).mean()),
            "direction_n": int(big.sum()),
        }
    by = {p: np.flatnonzero(df["pid"].to_numpy() == p) for p in df["pid"].unique()}
    ea = (df[contrast] - df["true"]).abs().to_numpy()
    eb = (df["baseline"] - df["true"]).abs().to_numpy()
    d_mae, d_med = [], []
    for d in draws:
        ix = np.concatenate([by[q] for q in d if q in by])
        if ix.size == 0:
            continue
        d_mae.append(ea[ix].mean() - eb[ix].mean())
        d_med.append(np.median(ea[ix]) - np.median(eb[ix]))
    res[f"mae_{contrast}_minus_baseline"] = r3(ea.mean() - eb.mean())
    res[f"mae_{contrast}_minus_baseline_ci95"] = ci(d_mae)
    res[f"median_ae_{contrast}_minus_baseline"] = r3(np.median(ea) - np.median(eb))
    res[f"median_ae_{contrast}_minus_baseline_ci95"] = ci(d_med)
    return res


def score_v3(df: pd.DataFrame, arm: str, comparators: tuple[str, ...], draws) -> dict:
    """Selected curve vs each comparator: per-arm MAE/RMSE/median AE/bias/direction, paired-bootstrap CIs."""
    res = {
        "n_scenarios": int(len(df)),
        "n_patients": int(df["pid"].nunique()),
        "mean_true_delta": r3(df["true"].mean()),
        "share_true_delta_positive": r3((df["true"] > 0).mean()),
    }
    big = (df["true"].abs() >= DIRECTION_MIN).to_numpy()
    true = df["true"].to_numpy()
    for k in (arm, *comparators):
        e = df[k].to_numpy() - true
        res[k] = {
            "mae": r3(np.abs(e).mean()),
            "rmse": r3(np.sqrt((e**2).mean())),
            "median_ae": r3(np.median(np.abs(e))),
            "bias": r3(e.mean()),
            "direction_accuracy": r3((np.sign(df[k].to_numpy()[big]) == np.sign(true[big])).mean()),
            "direction_n": int(big.sum()),
        }
    by = {p: np.flatnonzero(df["pid"].to_numpy() == p) for p in df["pid"].unique()}
    ea = df[arm].to_numpy() - true
    for c in comparators:
        ec = df[c].to_numpy() - true
        d_mae, d_rmse = [], []
        for d in draws:
            ix = np.concatenate([by[q] for q in d if q in by])
            d_mae.append(np.abs(ea[ix]).mean() - np.abs(ec[ix]).mean())
            d_rmse.append(np.sqrt((ea[ix] ** 2).mean()) - np.sqrt((ec[ix] ** 2).mean()))
        res[f"vs_{c}"] = {
            "mae_diff": r3(np.abs(ea).mean() - np.abs(ec).mean()),
            "mae_diff_ci95": ci(d_mae),
            "rmse_diff": r3(np.sqrt((ea**2).mean()) - np.sqrt((ec**2).mean())),
            "rmse_diff_ci95": ci(d_rmse),
        }
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", type=Path, default=REPO / "artifacts/model_bundle.pkl")
    ap.add_argument("--out", type=Path, default=REPO / "reports/research/twin_and_whatif_validation.json")
    ap.add_argument("--md", type=Path, default=REPO / "reports/research/TWIN_AND_WHATIF_VALIDATION.md")
    ap.add_argument("--cache", type=Path, default=None, help="optional cache of the served What-If stage")
    args = ap.parse_args()
    logging.getLogger("glucotwin").setLevel(logging.WARNING)
    t0 = time.time()
    bundle = ModelBundle.load(args.bundle)
    cp = bundle.cohort_params
    cohort = generate_cohort(**cp)
    start = pd.Timestamp(cohort.start_utc)
    inp, plasma = reconstruct(cp["n_patients"], cp["days"], cp["seed"])
    ids = [r.patient_id for r in cohort.records]
    pos = {p: i for i, p in enumerate(ids)}
    split = {r.patient_id: r.split for r in cohort.records}
    tg = (
        cohort.true_glucose.pivot(index="timestamp", columns="patient_id", values="glucose")[ids].to_numpy().T
    )
    idx5 = np.arange(0, plasma.shape[1], 5) + 4
    if not np.array_equal(np.round(plasma[:, idx5[idx5 < plasma.shape[1]]], 1), tg):
        raise SystemExit("simulator reconstruction does not reproduce the cohort; aborting")
    print(f"reconstruction exact; {time.time() - t0:.0f}s", flush=True)

    cgm = cohort.observations[cohort.observations["kind"] == "cgm"].dropna(subset=["value"])
    cgm_by = {
        p: (np.array([minutes(t, start) for t in g["timestamp"]]), g["value"].to_numpy(dtype=float))
        for p, g in cgm.groupby("patient_id")
    }
    first = {p: minutes(g["timestamp"].min(), start) for p, g in cohort.observations.groupby("patient_id")}

    def anchor(pid: str, off: float) -> tuple[int, float]:
        tm, v = cgm_by[pid]
        k = np.searchsorted(tm, first[pid] + off * 60, side="right") - 1
        return int(tm[k]), float(v[k])

    # ---- served What-If on test patients (same anchors as v1)
    svc = TwinService(
        bundle, report_path=None, joint_support_path=REPO / "reports/research/b23_joint_support.json"
    )
    test_ids = svc.demo_patient_ids()
    cached = json.loads(args.cache.read_text()) if args.cache and args.cache.exists() else None
    model, svc_anchor = [], {}
    if cached and cached["model_version"] == bundle.model_version:
        model = [
            {**m, "p": {int(k): v for k, v in m["p"].items()} if m["p"] else None} for m in cached["model"]
        ]
        svc_anchor = {(m["pid"], m["off"]): m["a"] for m in model}
    else:
        for pid in test_ids:
            for off in OFFSETS_H:
                svc.create_replay(pid, off)
                for g in ALL_G:
                    r = svc.counterfactual(pid, g)
                    a = minutes(r.as_of, start)
                    svc_anchor[(pid, off)] = a
                    model.append(
                        {
                            "pid": pid,
                            "off": off,
                            "g": g,
                            "a": a,
                            "cur": r.baseline.current_glucose_mg_dl,
                            "withheld": r.primary is None,
                            "support": r.joint_support.status if r.joint_support else "unavailable",
                            "p": {int(k): v for k, v in r.primary.delta_glucose_mg_dl.items()}
                            if r.primary
                            else None,
                        }
                    )
            print(f"  {pid} done; {time.time() - t0:.0f}s", flush=True)
        if args.cache:
            args.cache.write_text(json.dumps({"model_version": bundle.model_version, "model": model}))
    print(f"served What-If: {len(model)} scenarios; {time.time() - t0:.0f}s", flush=True)

    # ---- paired simulator truth (common random numbers) for all patients
    truth, anchor_ok = {}, {}
    for off in OFFSETS_H:
        rows = []
        for pid in ids:
            a, v = anchor(pid, off)
            a = svc_anchor.get((pid, off), a)
            anchor_ok[(pid, off)] = v <= 180
            rows += [(pid, a, g) for g in ALL_G]
        d = paired_meal_delta(
            inp,
            plasma,
            np.array([pos[p] for p, _, _ in rows]),
            np.array([a for _, a, _ in rows]),
            np.array([g for _, _, g in rows], dtype=float),
            horizon_min=120,
        )
        for (pid, _, g), dd in zip(rows, d, strict=True):
            truth[(pid, off, g)] = {h: float(dd[h]) for h in HORIZONS}
    print(f"ground truth done; {time.time() - t0:.0f}s", flush=True)
    base = {
        (g, h): float(
            np.mean(
                [
                    truth[(p, off, g)][h]
                    for p in ids
                    if split[p] == "train"
                    for off in OFFSETS_H
                    if anchor_ok[(p, off)]
                ]
            )
        )
        for g in ALL_G
        for h in HORIZONS
    }

    # ---- exploratory observed-curve estimator inputs
    train_ids = {p for p in ids if split[p] == "train"}
    curve = observed_curve(cohort, train_ids)
    s_at = {}
    for rec in cohort.records:
        if rec.patient_id not in test_ids:
            continue
        streams = split_streams(cohort.patient_observations(rec.patient_id))
        resp = meal_responses(to_grid(streams["cgm"]), streams["meal"])
        keys = sorted({(m["off"], m["a"]) for m in model if m["pid"] == rec.patient_id})
        at = pd.DatetimeIndex([start + pd.Timedelta(minutes=a) for _, a in keys])
        s, k = personal_carb_sensitivity(resp, carb_sensitivity_prior(rec), at)
        for (off, _), sv, kv in zip(keys, s, k, strict=True):
            s_at[(rec.patient_id, off)] = (float(sv), int(kv))

    elig = [
        m
        for m in model
        if m["cur"] is not None
        and m["cur"] <= 180
        and not m["withheld"]
        and m["support"] == "within_training_support"
    ]
    excl_by_g = {}
    for g in ALL_G:
        mg = [m for m in model if m["g"] == g]
        excl_by_g[str(g)] = {
            "total": len(mg),
            "latest_cgm_above_180_or_missing": sum(m["cur"] is None or m["cur"] > 180 for m in mg),
            "forecast_withheld": sum(m["withheld"] for m in mg if m["cur"] is not None and m["cur"] <= 180),
            "outside_training_support": sum(
                m["support"] != "within_training_support"
                for m in mg
                if m["cur"] is not None and m["cur"] <= 180 and not m["withheld"]
            ),
            "eligible": sum(m in elig for m in mg),
        }

    def frame(h: int, grams: tuple[int, ...]) -> pd.DataFrame:
        rows = []
        for m in elig:
            if m["g"] not in grams:
                continue
            s, _ = s_at[(m["pid"], m["off"])]
            rows.append(
                {
                    "pid": m["pid"],
                    "g": m["g"],
                    "true": truth[(m["pid"], m["off"], m["g"])][h],
                    "whatif": m["p"][h],
                    "baseline": base[(m["g"], h)],
                    "explore_personal": m["g"] * s * curve["c"][h],
                    "explore_cohort_curve": m["g"] * curve["S"] * curve["c"][h],
                }
            )
        return pd.DataFrame(rows)

    pids_e = sorted({m["pid"] for m in elig})
    draws = draws_for(pids_e)
    b_grams = {"exclusions_by_grams": {g: excl_by_g[g] for g in map(str, GRAMS_B)}, "by_horizon": {}}
    explore = {
        "curve": {
            "c_by_horizon": {str(h): r3(v) for h, v in curve["c"].items()},
            "n_meals_by_horizon": {str(h): v for h, v in curve["n_meals"].items()},
            "S_median_observed_ratio_mg_dl_per_g": r3(curve["S"]),
            "n_ratio_meals": curve["n_ratio_meals"],
            "n_training_patients": len(train_ids),
        },
        "grams": list(ALL_G),
        "exclusions_by_grams": excl_by_g,
        "by_horizon": {},
    }
    for h in HORIZONS:
        df = frame(h, GRAMS_B)
        res = score(df, ("whatif", "baseline"), "whatif", draws)
        res["by_grams"] = {
            str(g): {
                "n": int(len(x)),
                "mean_true_delta": r3(x["true"].mean()),
                **{f"{k}_mae": r3((x[k] - x["true"]).abs().mean()) for k in ("whatif", "baseline")},
                **{f"{k}_median_ae": r3((x[k] - x["true"]).abs().median()) for k in ("whatif", "baseline")},
            }
            for g, x in df.groupby("g")
        }
        b_grams["by_horizon"][str(h)] = res
        dfa = frame(h, ALL_G)
        ex = score(
            dfa, ("explore_personal", "explore_cohort_curve", "whatif", "baseline"), "explore_personal", draws
        )
        ex2 = score(dfa, ("explore_cohort_curve", "baseline"), "explore_cohort_curve", draws)
        ex["mae_explore_cohort_curve_minus_baseline"] = ex2["mae_explore_cohort_curve_minus_baseline"]
        ex["mae_explore_cohort_curve_minus_baseline_ci95"] = ex2[
            "mae_explore_cohort_curve_minus_baseline_ci95"
        ]
        explore["by_horizon"][str(h)] = ex
    print(f"scoring done; {time.time() - t0:.0f}s", flush=True)

    # ---- D: train-fitted, validation-selected personalised curve (protocol addendum v3)
    val_ids = [p for p in ids if split[p] == "validation"]
    s_val = {}
    for rec in cohort.records:
        if rec.patient_id not in val_ids:
            continue
        streams = split_streams(cohort.patient_observations(rec.patient_id))
        resp = meal_responses(to_grid(streams["cgm"]), streams["meal"])
        at = pd.DatetimeIndex(
            [start + pd.Timedelta(minutes=anchor(rec.patient_id, off)[0]) for off in OFFSETS_H]
        )
        s, _ = personal_carb_sensitivity(resp, carb_sensitivity_prior(rec), at)
        for off, sv in zip(OFFSETS_H, s, strict=True):
            s_val[(rec.patient_id, off)] = float(sv)
    vrows = [(p, off, g) for p in val_ids for off in OFFSETS_H if anchor_ok[(p, off)] for g in ALL_G]
    shapes = {"median": curve["c"], "mean": curve["c_mean"]}
    cands, alpha = {}, {}
    for shape, c in shapes.items():
        raw = {h: np.array([g * s_val[(p, off)] * c[h] for p, off, g in vrows]) for h in HORIZONS}
        tru = {h: np.array([truth[(p, off, g)][h] for p, off, g in vrows]) for h in HORIZONS}
        alpha[shape] = {h: float((raw[h] * tru[h]).sum() / (raw[h] ** 2).sum()) for h in HORIZONS}
        for cal in (False, True):
            maes = {
                h: float(np.abs((alpha[shape][h] if cal else 1.0) * raw[h] - tru[h]).mean()) for h in HORIZONS
            }
            cands[f"{shape}_{'cal' if cal else 'uncal'}"] = {
                "validation_mae": {str(h): r3(v) for h, v in maes.items()},
                "mean_validation_mae": r3(np.mean(list(maes.values()))),
            }
    order = ["median_uncal", "mean_uncal", "median_cal", "mean_cal"]
    sel = min(order, key=lambda k: (cands[k]["mean_validation_mae"], order.index(k)))
    sel_shape, sel_cal = sel.split("_")
    a_sel = {h: (alpha[sel_shape][h] if sel_cal == "cal" else 1.0) for h in HORIZONS}

    def frame_v3(h: int, grams: tuple[int, ...]) -> pd.DataFrame:
        rows = []
        for m in elig:
            if m["g"] not in grams:
                continue
            s, _ = s_at[(m["pid"], m["off"])]
            rows.append(
                {
                    "pid": m["pid"],
                    "true": truth[(m["pid"], m["off"], m["g"])][h],
                    "curve": a_sel[h] * m["g"] * s * shapes[sel_shape][h],
                    "cohort_average": base[(m["g"], h)],
                    "served_whatif": m["p"][h],
                }
            )
        return pd.DataFrame(rows)

    d_sec = {
        "protocol": "experiments/twin_validity/protocol_addendum_v3.json",
        "validation": {
            "n_patients": len(val_ids),
            "n_scenarios": len(vrows),
            "candidates": cands,
            "alpha_by_shape": {k: {str(h): r3(v) for h, v in a.items()} for k, a in alpha.items()},
            "selected": sel,
            "selected_alpha": {str(h): r3(v) for h, v in a_sel.items()},
            "repeat_of_v2_test_candidate": sel == "median_uncal",
        },
        "curve_shape": {k: {str(h): r3(v) for h, v in c.items()} for k, c in shapes.items()},
        "test_all_grams": {},
        "test_b_grams": {},
    }
    for h in HORIZONS:
        d_sec["test_all_grams"][str(h)] = score_v3(
            frame_v3(h, ALL_G), "curve", ("cohort_average", "served_whatif"), draws
        )
        d_sec["test_b_grams"][str(h)] = score_v3(
            frame_v3(h, GRAMS_B), "curve", ("cohort_average", "served_whatif"), draws
        )
    print(f"section D done (selected {sel}); {time.time() - t0:.0f}s", flush=True)

    # ---- A: post-meal ablation
    prior = {r.patient_id: carb_sensitivity_prior(r) for r in cohort.records}
    tables = {}
    for r in cohort.records:
        if r.split == "test":
            t = build_patient_table(cohort.patient_observations(r.patient_id), r)
            t["prior"] = prior[r.patient_id]
            tables[r.patient_id] = t
    post = post_meal_ablation(bundle, tables)

    v1r = json.loads((REPO / "reports/research/twin_validity.json").read_text())
    report = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "protocol": PROTOCOL,
        "protocol_d": "experiments/twin_validity/protocol_addendum_v3.json",
        "status": "POST-HOC / EXPLORATORY addendum. v1 pre-registered results are collated unchanged below.",
        "model_version": bundle.model_version,
        "what": "Synthetic simulator cohort only (extended Bergman minimal model per src/glucotwin/synth/generator.py). "
        "Frozen served models. Not clinical evidence.",
        "checks": {"simulator_reconstruction_exact": True},
        "A_post_meal_personalisation_ablation": post,
        "B_whatif_extra_grams": b_grams,
        "C_exploratory_observed_curve_estimator": explore,
        "D_train_fitted_validation_selected_curve": d_sec,
        "v1_collated_unchanged": {
            "source": "reports/research/twin_validity.json",
            "v1_model_version": v1r["model_version"],
            "A_personalisation_ablation": v1r["A_personalisation_ablation"],
            "A2_recovery_test_patients": v1r["A2_latent_sensitivity_recovery"]["test_patients"],
            "B_whatif_by_horizon": {
                h: {k: v for k, v in x.items() if k != "mae_by_grams"}
                for h, x in v1r["B_whatif_ground_truth"]["by_horizon"].items()
            },
            "B_exclusions": v1r["B_whatif_ground_truth"]["exclusions"],
        },
        "deviations": [
            "Correction (2026-10-23): reports generated before this date computed every CI with 2,000 patient "
            "resamples and seed 20261023 (imported from the v1 script), although protocol addenda v2 and v3 "
            "register 1,000 resamples with seed 20261017 and the report text said 1,000. This run uses the "
            "registered settings. Point estimates are unaffected; only CI endpoints can change."
        ],
        "runtime_s": round(time.time() - t0, 1),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1) + "\n")
    args.md.write_text(render_md(report))
    print(f"wrote {args.out} and {args.md} in {report['runtime_s']} s")


def _ci(x) -> str:
    return f"[{x[0]:+.2f}, {x[1]:+.2f}]"


def render_md(r: dict) -> str:
    L = [
        "# Twin and What-If validation: addendum v2 (post-hoc / exploratory)",
        "",
        f"Generated by `scripts/validate_twin_and_whatif.py` from protocol `{r['protocol']}`. "
        f"Model `{r['model_version']}`. Synthetic simulator cohort only; frozen served models; not clinical evidence. "
        "The addendum was written after the v1 results were known, so everything here is post-hoc. "
        "Pre-registered v1 results are in `reports/research/twin_validity.json` / `docs/research/TWIN_VALIDITY.md` "
        "and are copied unchanged into the JSON. CIs: 95 %, 1,000 paired patient-bootstrap resamples.",
        "",
        "## A. Personalisation in post-meal windows (test rows with >= 10 g logged in the previous 60 min)",
        "",
        "| Horizon | Rows | RMSE served | RMSE prior-only | Diff [95% CI] | MAE served | MAE prior-only | Diff [95% CI] |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for h, x in r["A_post_meal_personalisation_ablation"]["by_horizon"].items():
        a, m = x["rmse"], x["mae"]
        L.append(
            f"| {h} min | {x['n_rows']:,} | {a['served']:.2f} | {a['ablated']:.2f} | {a['ablated_minus_served']:+.2f} "
            f"{_ci(a['ci95_patient_bootstrap'])} | {m['served']:.2f} | {m['ablated']:.2f} | "
            f"{m['ablated_minus_served']:+.2f} {_ci(m['ci95_patient_bootstrap'])} |"
        )
    L += [
        "",
        "Positive difference = the prior-only (no personalisation) arm is worse.",
        "",
        "## B. Served What-If vs simulator truth at 20/40/60/90/120 g",
        "",
        "| Horizon | n | Mean true delta | What-If MAE / median AE | Cohort-avg MAE / median AE | MAE diff [95% CI] | Median AE diff [95% CI] | What-If bias |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for h, x in r["B_whatif_extra_grams"]["by_horizon"].items():
        w, b = x["whatif"], x["baseline"]
        L.append(
            f"| {h} min | {x['n_scenarios']:,} | {x['mean_true_delta']:.1f} | {w['mae']:.1f} / {w['median_ae']:.1f} | "
            f"{b['mae']:.1f} / {b['median_ae']:.1f} | {x['mae_whatif_minus_baseline']:+.2f} {_ci(x['mae_whatif_minus_baseline_ci95'])} | "
            f"{x['median_ae_whatif_minus_baseline']:+.2f} {_ci(x['median_ae_whatif_minus_baseline_ci95'])} | {w['bias']:+.1f} |"
        )
    L += [
        "",
        "Per gram (120 min): "
        + "; ".join(
            f"{g} g n={v['n']} true {v['mean_true_delta']:.0f}, What-If MAE {v['whatif_mae']:.1f} vs baseline {v['baseline_mae']:.1f}"
            for g, v in r["B_whatif_extra_grams"]["by_horizon"]["120"]["by_grams"].items()
        )
        + ".",
        "",
        "Eligibility per gram: "
        + "; ".join(
            f"{g} g {v['eligible']}/{v['total']} (outside support {v['outside_training_support']})"
            for g, v in r["B_whatif_extra_grams"]["exclusions_by_grams"].items()
        )
        + ".",
        "",
        "Direction accuracy is not informative here: "
        + ", ".join(
            f"{h} min {x['share_true_delta_positive']:.1%}"
            for h, x in r["B_whatif_extra_grams"]["by_horizon"].items()
        )
        + " of true deltas are positive.",
        "",
        "## C. Exploratory: personalised response curve learned from observed CGM (not served)",
        "",
    ]
    c = r["C_exploratory_observed_curve_estimator"]
    cv = c["curve"]
    L += [
        "Curve fraction of peak c(h): "
        + ", ".join(
            f"{h} min {v:.2f} (n={cv['n_meals_by_horizon'][h]})" for h, v in cv["c_by_horizon"].items()
        )
        + f"; median observed ratio S = {cv['S_median_observed_ratio_mg_dl_per_g']:.2f} mg/dL per g from {cv['n_ratio_meals']} meals in "
        f"{cv['n_training_patients']} training patients. Estimate = grams x s(patient, now) x c(h). All 10 gram amounts.",
        "",
        "| Horizon | n | Personal curve MAE | Cohort curve MAE | Served What-If MAE | Cohort-avg (sim truth) MAE | Personal minus cohort-avg [95% CI] |",
        "|---|---|---|---|---|---|---|",
    ]
    for h, x in c["by_horizon"].items():
        L.append(
            f"| {h} min | {x['n_scenarios']:,} | {x['explore_personal']['mae']:.1f} | {x['explore_cohort_curve']['mae']:.1f} | "
            f"{x['whatif']['mae']:.1f} | {x['baseline']['mae']:.1f} | {x['mae_explore_personal_minus_baseline']:+.2f} "
            f"{_ci(x['mae_explore_personal_minus_baseline_ci95'])} |"
        )
    L += [
        "",
        "The cohort-average baseline is fitted on simulator ground truth from training patients, an advantage no real "
        "deployment would have; the curve estimators use observed CGM only. This estimator is exploratory and is not served.",
        "",
    ]
    d = r["D_train_fitted_validation_selected_curve"]
    v = d["validation"]
    L += [
        "## D. Train-fitted, validation-selected personalised response curve (protocol addendum v3)",
        "",
        f"Shape fitted on observed CGM of the 36 training patients; candidate chosen on {v['n_patients']} validation patients "
        f"({v['n_scenarios']:,} scenarios) by mean MAE: "
        + "; ".join(f"{k} {c['mean_validation_mae']:.2f}" for k, c in v["candidates"].items())
        + f". **Selected: {v['selected']}** (alpha "
        + ", ".join(f"{h} min {a:.2f}" for h, a in v["selected_alpha"].items())
        + "). "
        + (
            "This is the candidate whose test numbers addendum v2 already reported, so the test result below is a repeat, not a first look. "
            if v["repeat_of_v2_test_candidate"]
            else ""
        )
        + "Personal sensitivity uses only meals completed before the forecast moment. Scored once on the 12 test patients.",
        "",
    ]
    for key, title in (("test_all_grams", "all 10 meal sizes"), ("test_b_grams", "20/40/60/90/120 g")):
        L += [
            f"Test, {title}:",
            "",
            "| Horizon | n | Curve MAE / RMSE | Cohort-avg MAE / RMSE | Served What-If MAE / RMSE | Curve - cohort MAE [95% CI] | Curve - cohort RMSE [95% CI] | Curve - What-If MAE [95% CI] | Direction acc. (curve) |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for h, x in d[key].items():
            cu, co, wi = x["curve"], x["cohort_average"], x["served_whatif"]
            vc, vw = x["vs_cohort_average"], x["vs_served_whatif"]
            L.append(
                f"| {h} min | {x['n_scenarios']:,} | {cu['mae']:.1f} / {cu['rmse']:.1f} | {co['mae']:.1f} / {co['rmse']:.1f} | "
                f"{wi['mae']:.1f} / {wi['rmse']:.1f} | {vc['mae_diff']:+.2f} {_ci(vc['mae_diff_ci95'])} | "
                f"{vc['rmse_diff']:+.2f} {_ci(vc['rmse_diff_ci95'])} | {vw['mae_diff']:+.2f} {_ci(vw['mae_diff_ci95'])} | "
                f"{cu['direction_accuracy']:.1%} (true deltas positive: {x['share_true_delta_positive']:.1%}) |"
            )
        L.append("")
    L += [
        "Direction accuracy is uninformative when every true delta is positive. Synthetic simulator only; not served.",
        "",
    ]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    main()
