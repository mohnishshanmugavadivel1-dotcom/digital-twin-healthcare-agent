"""Twin-validity research analysis (protocol: experiments/twin_validity/protocol.json).

A  personalisation ablation of the frozen models (served vs record-prior carb sensitivity), paired bootstrap;
A2 recovery of the simulator's latent meal response by the engine's personal carb sensitivity, day 0..14;
B  What-If deltas of the served models vs paired simulator ground truth, against a cohort-average baseline;
D  audit of a "forecast lower bound < 70 mg/dL" rule (not a probability) against observed CGM < 70;
E  simulator time below 70 mg/dL.

Synthetic data only. Frozen production models; nothing is retrained, tuned or written outside the output file.
Usage:  .venv/bin/python scripts/twin_validity_analysis.py [--bundle artifacts/model_bundle.pkl]
                                                          [--out reports/research/twin_validity.json]
Runtime: about 10 minutes.
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import pearsonr, spearmanr
from sklearn.metrics import roc_auc_score

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
GRAMS = (25, 35, 36, 40, 45, 50)  # Indian meal presets (frontend/src/mealPresets.ts)
OFFSETS_H = tuple(float(x) for x in np.arange(26.0, 330.0, 9.5))  # same 32 points as counterfactual_audit.py
HORIZONS = (30, 60, 120)
ALL_H = (30, 60, 90, 120)
GAIN_GRAMS = 40
BOOT, SEED = 2000, 20261023
DIRECTION_MIN = 2.0
HYPO = 70.0
HYPO_MEDS = {"sulfonylurea", "basal_insulin"}
HEADLINE = {"rmse": {30: 10.40, 60: 17.21, 120: 25.90}, "auroc": 0.884}


def r3(x) -> float | None:
    return None if x is None or not np.isfinite(x) else round(float(x), 3)


def ci(vals) -> list[float | None]:
    v = np.asarray([x for x in vals if np.isfinite(x)])
    return [r3(np.percentile(v, 2.5)), r3(np.percentile(v, 97.5))] if v.size else [None, None]


def minutes(ts, start) -> int:
    return int(round((pd.Timestamp(ts) - start) / pd.Timedelta(minutes=1)))


# ----------------------------------------------------------------------------- A: ablation
def ablation(bundle, cohort, tables) -> dict:
    te = pd.concat([tables[r.patient_id] for r in cohort.records if r.split == "test"], ignore_index=True)
    prior = {r.patient_id: carb_sensitivity_prior(r) for r in cohort.records}
    X = te[FEATURE_NAMES]
    Xa = X.copy()
    p = te["patient_id"].map(prior).to_numpy()
    Xa["carb_sensitivity"] = p
    Xa["expected_meal_rise"] = p * te["carbs_on_board"].to_numpy()
    pids = te["patient_id"].to_numpy()
    out, sq = {"rmse_mg_dl": {}}, {}
    for arm, XX in (("served", X), ("ablated", Xa)):
        pred = bundle.trajectory_model.predict(XX)
        for h in ALL_H:
            y = te[f"y_glucose_{h}"].to_numpy()
            ok = ~np.isnan(y)
            sq[(arm, h)] = pd.DataFrame({"pid": pids[ok], "se": (pred[h].to_numpy()[ok] - y[ok]) ** 2})
    ev = te.dropna(subset=["y_event"])
    yev = ev["y_event"].to_numpy().astype(int)
    score = {"served": bundle.event_model.predict_proba(ev[FEATURE_NAMES]),
             "ablated": bundle.event_model.predict_proba(Xa.loc[ev.index])}
    ids = sorted(set(pids))
    rng = np.random.default_rng(SEED)
    draws = [rng.choice(ids, size=len(ids), replace=True) for _ in range(BOOT)]
    for h in ALL_H:
        agg = {arm: sq[(arm, h)].groupby("pid")["se"].agg(["sum", "count"]) for arm in ("served", "ablated")}
        rm = {arm: float(np.sqrt(a["sum"].sum() / a["count"].sum())) for arm, a in agg.items()}
        diffs = []
        for d in draws:
            v = {arm: np.sqrt(a.loc[d, "sum"].sum() / a.loc[d, "count"].sum()) for arm, a in agg.items()}
            diffs.append(v["ablated"] - v["served"])
        out["rmse_mg_dl"][str(h)] = {"served": r3(rm["served"]), "ablated": r3(rm["ablated"]),
                                     "ablated_minus_served": r3(rm["ablated"] - rm["served"]),
                                     "ci95_patient_bootstrap": ci(diffs), "n_rows": int(agg["served"]["count"].sum())}
    au = {arm: float(roc_auc_score(yev, s)) for arm, s in score.items()}
    evp = ev["patient_id"].to_numpy()
    by = {pid: np.flatnonzero(evp == pid) for pid in ids}
    diffs = []
    for d in draws:
        ix = np.concatenate([by[q] for q in d])
        if yev[ix].min() == yev[ix].max():
            continue
        diffs.append(roc_auc_score(yev[ix], score["ablated"][ix]) - roc_auc_score(yev[ix], score["served"][ix]))
    out["event_auroc"] = {"served": r3(au["served"]), "ablated": r3(au["ablated"]),
                          "ablated_minus_served": r3(au["ablated"] - au["served"]), "ci95_patient_bootstrap": ci(diffs),
                          "n_rows": int(len(yev)), "n_positive": int(yev.sum())}
    out["reproduces_headline"] = bool(
        all(round(out["rmse_mg_dl"][str(h)]["served"], 2) == v for h, v in HEADLINE["rmse"].items())
        and round(au["served"], 3) == HEADLINE["auroc"])
    out["n_test_patients"] = len(ids)
    return out


# ----------------------------------------------------------------------------- A2: engine s by day
def engine_sensitivity_by_day(cohort, start, days) -> dict[str, list[tuple[float, int]]]:
    res = {}
    for rec in cohort.records:
        streams = split_streams(cohort.patient_observations(rec.patient_id))
        responses = meal_responses(to_grid(streams["cgm"]), streams["meal"])
        prior = carb_sensitivity_prior(rec)
        at = pd.DatetimeIndex([start + pd.Timedelta(days=d) for d in range(1, days + 1)])
        s, k = personal_carb_sensitivity(responses, prior, at)
        res[rec.patient_id] = [(prior, 0)] + [(float(a), int(b)) for a, b in zip(s, k, strict=True)]
    return res


def recovery(est: dict, gain: dict, ids: list[str], days: int, boot: bool) -> list[dict]:
    rows = []
    rng = np.random.default_rng(SEED)
    for d in range(days + 1):
        s = np.array([est[p][d][0] for p in ids])
        g = np.array([gain[p] for p in ids])
        row = {"day": d, "pearson_r": r3(pearsonr(s, g)[0]), "spearman_rho": r3(spearmanr(s, g)[0]),
               "mae_mg_dl_per_g": r3(np.mean(np.abs(s - g))), "median_ratio_estimate_to_latent": r3(np.median(s / g)),
               "mean_meals_used": r3(np.mean([est[p][d][1] for p in ids]))}
        if boot:
            rs = []
            for _ in range(BOOT):
                ix = rng.integers(0, len(ids), len(ids))
                if np.std(s[ix]) > 0 and np.std(g[ix]) > 0:
                    rs.append(pearsonr(s[ix], g[ix])[0])
            row["pearson_r_ci95_patient_bootstrap"] = ci(rs)
        rows.append(row)
    return rows


# ----------------------------------------------------------------------------- D: lower-bound rule
def lower_bound_audit(bundle, cohort, tables) -> dict:
    out = {}
    w = bundle.interval_half_width
    for split in ("validation", "test"):
        recs = [r for r in cohort.records if r.split == split]
        parts = []
        for rec in recs:
            t = tables[rec.patient_id]
            pred = bundle.trajectory_model.predict(t[FEATURE_NAMES])
            lows = np.column_stack([np.round(np.maximum(pred[h].to_numpy() - w[h], 40.0), 1) for h in ALL_H])
            fire = (lows < HYPO).any(axis=1)
            grid = to_grid(split_streams(cohort.patient_observations(rec.patient_id))["cgm"])
            gt = grid.index.as_unit("ns").asi8
            gv = grid.to_numpy(dtype=float)
            ts = pd.DatetimeIndex(t["timestamp"]).as_unit("ns").asi8
            lo_i = np.searchsorted(gt, ts, side="right")
            hi_i = np.searchsorted(gt, ts + 120 * 60 * 10**9, side="right")
            fut = np.array([np.nanmin(gv[a:b]) if b > a and np.isfinite(gv[a:b]).any() else np.nan
                            for a, b in zip(lo_i, hi_i, strict=True)])
            flag = bool({m.drug_class for m in rec.medications} & HYPO_MEDS)
            parts.append(pd.DataFrame({"fire": fire, "outcome": fut < HYPO, "known": np.isfinite(fut), "flag": flag}))
        df = pd.concat(parts, ignore_index=True)
        df = df[df["known"]]

        def stats(x: pd.DataFrame) -> dict:
            n, f, o = len(x), int(x["fire"].sum()), int(x["outcome"].sum())
            tp = int((x["fire"] & x["outcome"]).sum())
            return {"n_forecast_moments": n, "fired": f, "fire_rate": r3(f / n) if n else None,
                    "outcome_moments": o, "outcome_base_rate": r3(o / n) if n else None, "true_positive": tp,
                    "ppv": r3(tp / f) if f else None, "sensitivity": r3(tp / o) if o else None}

        out[split] = {"all": stats(df), "sulfonylurea_or_basal_insulin": stats(df[df["flag"]]),
                      "neither": stats(df[~df["flag"]]),
                      "patients": len(recs), "patients_with_flag": sum(
                          bool({m.drug_class for m in r.medications} & HYPO_MEDS) for r in recs)}
    return out


def time_below_range(cohort) -> dict:
    cgm = cohort.observations[cohort.observations["kind"] == "cgm"]
    flag = {r.patient_id: bool({m.drug_class for m in r.medications} & HYPO_MEDS) for r in cohort.records}
    f = cgm["patient_id"].map(flag)

    def tbr(x) -> dict:
        v = x["value"].to_numpy(dtype=float)
        v = v[np.isfinite(v)]
        return {"readings": int(v.size), "below_70": int((v < 70).sum()), "share_below_70": r3(100 * (v < 70).mean()),
                "below_54": int((v < 54).sum())}

    return {"unit": "percent of CGM readings", "all_60_patients": tbr(cgm),
            "sulfonylurea_or_basal_insulin": tbr(cgm[f]), "neither": tbr(cgm[~f]),
            "published_comparator_in_repo": "2.4% (docs/AUDIT_WAVE2.md F-18; deck slide 6)"}


# ----------------------------------------------------------------------------- main
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", type=Path, default=REPO / "artifacts/model_bundle.pkl")
    ap.add_argument("--out", type=Path, default=REPO / "reports/research/twin_validity.json")
    ap.add_argument("--cache", type=Path, default=None, help="optional cache of the served What-If stage")
    args = ap.parse_args()
    logging.getLogger("glucotwin").setLevel(logging.WARNING)
    t0 = time.time()
    bundle = ModelBundle.load(args.bundle)
    cp = bundle.cohort_params
    cohort = generate_cohort(**cp)
    start = pd.Timestamp(cohort.start_utc)
    days = cp["days"]
    inp, plasma = reconstruct(cp["n_patients"], days, cp["seed"])
    ids = [r.patient_id for r in cohort.records]
    pos = {p: i for i, p in enumerate(ids)}
    split = {r.patient_id: r.split for r in cohort.records}
    tg = cohort.true_glucose.pivot(index="timestamp", columns="patient_id", values="glucose")[ids].to_numpy().T
    idx5 = np.arange(0, plasma.shape[1], 5) + 4
    recon_exact = bool(np.array_equal(np.round(plasma[:, idx5[idx5 < plasma.shape[1]]], 1), tg))
    if not recon_exact:
        raise SystemExit("simulator reconstruction does not reproduce the cohort; aborting (protocol B)")
    print(f"reconstruction exact; {time.time() - t0:.0f}s", flush=True)

    # observed CGM per patient (minutes from start, value) for anchors and eligibility
    cgm = cohort.observations[cohort.observations["kind"] == "cgm"].dropna(subset=["value"])
    cgm_by = {p: (np.array([minutes(t, start) for t in g["timestamp"]]), g["value"].to_numpy(dtype=float))
              for p, g in cgm.groupby("patient_id")}

    # replay offsets count from each patient's first observation (TwinService.create_replay)
    first = {p: minutes(g["timestamp"].min(), start) for p, g in cohort.observations.groupby("patient_id")}

    def anchor(pid: str, off: float) -> tuple[int, float]:
        tm, v = cgm_by[pid]
        k = np.searchsorted(tm, first[pid] + off * 60, side="right") - 1
        return int(tm[k]), float(v[k])

    # ---- B1: served What-If deltas on test patients
    # same joint-support evidence file as the served API (src/glucotwin/api/app.py)
    svc = TwinService(bundle, report_path=None, joint_support_path=REPO / "reports/research/b23_joint_support.json")
    test_ids = svc.demo_patient_ids()
    model, svc_anchor, agree = [], {}, 0
    cached = json.loads(args.cache.read_text()) if args.cache and args.cache.exists() else None
    if cached and cached["model_version"] == bundle.model_version:
        model = [{**m, "p": {int(k): v for k, v in m["p"].items()} if m["p"] else None,
                  "s": {int(k): v for k, v in m["s"].items()} if m["s"] else None} for m in cached["model"]]
        svc_anchor = {(m["pid"], m["off"]): m["a"] for m in model}
        agree = sum(svc_anchor[(p, o)] == anchor(p, o)[0] for p, o in svc_anchor)
        test_ids = sorted({m["pid"] for m in model})
    for pid in ([] if cached and model else test_ids):
        for off in OFFSETS_H:
            svc.create_replay(pid, off)
            for g in GRAMS:
                r = svc.counterfactual(pid, g)
                a = minutes(r.as_of, start)
                svc_anchor[(pid, off)] = a
                model.append({"pid": pid, "off": off, "g": g, "a": a, "cur": r.baseline.current_glucose_mg_dl,
                              "withheld": r.primary is None,
                              "support": r.joint_support.status if r.joint_support else "unavailable",
                              "p": {int(k): v for k, v in r.primary.delta_glucose_mg_dl.items()} if r.primary else None,
                              "s": {int(k): v for k, v in r.secondary.delta_glucose_mg_dl.items()} if r.secondary else None})
            agree += int(svc_anchor[(pid, off)] == anchor(pid, off)[0])
    if args.cache and not cached:
        args.cache.write_text(json.dumps({"model_version": bundle.model_version, "model": model}))
    print(f"served What-If done: {len(model)} scenarios; {time.time() - t0:.0f}s", flush=True)

    # ---- B2 + A2: paired simulator ground truth for all patients at every anchor
    truth, peak40, anchor_ok = {}, {}, {}
    for off in OFFSETS_H:
        rows = []
        for pid in ids:
            a, v = anchor(pid, off)
            a = svc_anchor.get((pid, off), a)
            anchor_ok[(pid, off)] = v <= 180
            rows += [(pid, a, g) for g in GRAMS]
        d = paired_meal_delta(inp, plasma, np.array([pos[p] for p, _, _ in rows]), np.array([a for _, a, _ in rows]),
                              np.array([g for _, _, g in rows], dtype=float), horizon_min=120)
        for (pid, _, g), dd in zip(rows, d, strict=True):
            truth[(pid, off, g)] = {h: float(dd[h]) for h in HORIZONS}
            if g == GAIN_GRAMS:
                peak40[(pid, off)] = float(dd[1:].max()) / GAIN_GRAMS
    print(f"ground truth done; {time.time() - t0:.0f}s", flush=True)

    # baseline: training-patient mean true delta per (g, h)
    base = {(g, h): float(np.mean([truth[(p, off, g)][h] for p in ids if split[p] == "train" for off in OFFSETS_H
                                   if anchor_ok[(p, off)]])) for g in GRAMS for h in HORIZONS}
    n_base = sum(anchor_ok[(p, off)] for p in ids if split[p] == "train" for off in OFFSETS_H)

    # scoring
    elig = [m for m in model if m["cur"] is not None and m["cur"] <= 180 and not m["withheld"]
            and m["support"] == "within_training_support"]
    excl = {"total_scenarios": len(model),
            "latest_cgm_above_180_or_missing": sum(m["cur"] is None or m["cur"] > 180 for m in model),
            "forecast_withheld": sum(m["withheld"] for m in model if m["cur"] is not None and m["cur"] <= 180),
            "outside_training_support": sum(m["support"] != "within_training_support" for m in model
                                            if m["cur"] is not None and m["cur"] <= 180 and not m["withheld"]),
            "eligible": len(elig)}
    whatif = {"exclusions": excl, "eligible_patients": len({m["pid"] for m in elig}),
              "eligible_moments": len({(m["pid"], m["off"]) for m in elig}),
              "baseline_training_anchor_points": int(n_base), "by_horizon": {}}
    rng = np.random.default_rng(SEED)
    pids_e = sorted({m["pid"] for m in elig})
    draws = [rng.choice(pids_e, size=len(pids_e), replace=True) for _ in range(BOOT)]
    for h in HORIZONS:
        df = pd.DataFrame([{"pid": m["pid"], "g": m["g"], "true": truth[(m["pid"], m["off"], m["g"])][h],
                            "primary": m["p"][h], "secondary": m["s"][h], "baseline": base[(m["g"], h)]} for m in elig])
        res = {"n_scenarios": len(df), "mean_true_delta": r3(df["true"].mean()),
               "true_delta_range": [r3(df["true"].min()), r3(df["true"].max())]}
        big = df["true"].abs() >= DIRECTION_MIN
        for k in ("primary", "secondary", "baseline"):
            err = df[k] - df["true"]
            res[k] = {"mae": r3(err.abs().mean()), "bias": r3(err.mean()),
                      "spearman_rho": r3(spearmanr(df[k], df["true"])[0]) if df[k].nunique() > 1 else None,
                      "direction_accuracy": r3((np.sign(df.loc[big, k]) == np.sign(df.loc[big, "true"])).mean()),
                      "direction_n": int(big.sum())}
        ae = df.assign(ep=(df["primary"] - df["true"]).abs(), eb=(df["baseline"] - df["true"]).abs())
        per = ae.groupby("pid")[["ep", "eb"]].agg(["sum", "count"])
        diffs = []
        for d in draws:
            sub = per.loc[d]
            diffs.append(sub[("ep", "sum")].sum() / sub[("ep", "count")].sum()
                         - sub[("eb", "sum")].sum() / sub[("eb", "count")].sum())
        res["mae_primary_minus_baseline"] = r3(res["primary"]["mae"] - res["baseline"]["mae"])
        res["mae_primary_minus_baseline_ci95_patient_bootstrap"] = ci(diffs)
        res["mae_by_grams"] = {str(g): {k: r3((x[k] - x["true"]).abs().mean()) for k in ("primary", "baseline")}
                               for g, x in df.groupby("g")}
        whatif["by_horizon"][str(h)] = res

    # ---- A2: latent sensitivity recovery
    gain = {}
    for p in ids:
        vals = [peak40[(p, off)] for off in OFFSETS_H if anchor_ok[(p, off)]]
        gain[p] = float(np.mean(vals))
    est = engine_sensitivity_by_day(cohort, start, days)
    test_list = [p for p in ids if split[p] == "test"]
    rec = {"latent_definition": f"mean peak interstitial-glucose rise per gram after an extra {GAIN_GRAMS} g meal "
                                "(paired simulator runs, eligible anchors)",
           "latent_range_test": [r3(min(gain[p] for p in test_list)), r3(max(gain[p] for p in test_list))],
           "test_patients": recovery(est, gain, test_list, days, boot=True),
           "all_60_patients": recovery(est, gain, ids, days, boot=False)}

    # ---- A, D, E
    tables = {r.patient_id: build_patient_table(cohort.patient_observations(r.patient_id), r)
              for r in cohort.records if r.split in ("test", "validation")}
    abl = ablation(bundle, cohort, tables)
    print(f"ablation done; {time.time() - t0:.0f}s", flush=True)
    low = lower_bound_audit(bundle, cohort, tables)
    report = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "protocol": "experiments/twin_validity/protocol.json",
        "model_version": bundle.model_version,
        "what": "Synthetic simulator cohort only. Research analysis of the frozen served models; not clinical evidence.",
        "checks": {"simulator_reconstruction_exact": recon_exact,
                   "service_anchor_equals_latest_cgm_at_offset": f"{agree}/{len(test_ids) * len(OFFSETS_H)}",
                   "anchor_note": "the rest fall in CGM gaps, where the service anchors on the latest observation "
                                  "of any stream; ground truth always uses the service's own moment",
                   "served_arm_reproduces_headline": abl["reproduces_headline"]},
        "A_personalisation_ablation": abl,
        "A2_latent_sensitivity_recovery": rec,
        "B_whatif_ground_truth": whatif,
        "D_lower_bound_below_70_rule": low,
        "E_time_below_range": time_below_range(cohort),
        "runtime_s": round(time.time() - t0, 1),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1) + "\n")
    print(f"wrote {args.out} in {report['runtime_s']} s")


if __name__ == "__main__":
    main()
