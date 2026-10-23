"""Post-meal walk effect estimator, protocol addendum v4 (experiments/twin_validity/protocol_addendum_v4.json).

Synthetic simulator cohort only. Candidates are fitted on the 36 training patients, one is selected on the
12 validation patients, and the 12 test patients are scored once against paired simulator truth.
Writes reports/research/walk_whatif_validation.json and reports/research/WALK_WHATIF_VALIDATION.md.

    .venv/bin/python scripts/validate_walk_whatif.py
"""

from __future__ import annotations

import importlib.util
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from glucotwin.models.bundle import ModelBundle
from glucotwin.synth.generator import generate_cohort
from glucotwin.twin_validity_research import paired_walk_delta, reconstruct

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("tv1", REPO / "scripts/twin_validity_analysis.py")
v1 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(v1)
r3, ci, minutes, OFFSETS_H = v1.r3, v1.ci, v1.minutes, v1.OFFSETS_H

PROTOCOL = "experiments/twin_validity/protocol_addendum_v4.json"
SEED, BOOT = 20261017, 1000
GRAMS = (20, 25, 35, 36, 40, 45, 50, 60, 90, 120)
HORIZONS = (30, 60, 120)
DIRECTION_MIN = 2.0
WALK = {"offset_min": 15, "minutes": 20, "steps_per_min": 125.0}
ORDER = ("cohort_constant", "cohort_by_grams", "glucose_scaled")
OUT_JSON = REPO / "reports/research/walk_whatif_validation.json"
OUT_MD = REPO / "reports/research/WALK_WHATIF_VALIDATION.md"


def metrics(pred: np.ndarray, true: np.ndarray) -> dict:
    err = pred - true
    big = np.abs(true) >= DIRECTION_MIN
    return {
        "mae": r3(np.abs(err).mean()),
        "rmse": r3(np.sqrt((err**2).mean())),
        "bias": r3(err.mean()),
        "direction_accuracy": r3((np.sign(pred[big]) == np.sign(true[big])).mean()) if big.any() else None,
        "direction_n": int(big.sum()),
    }


def paired_ci(df: pd.DataFrame, a: str, b: str, draws: list[np.ndarray]) -> dict:
    """Patient-bootstrap CI of (a - b) for MAE and RMSE; df has columns pid, true, a, b."""
    g = pd.DataFrame(
        {
            "pid": df["pid"],
            "ae_a": (df[a] - df["true"]).abs(),
            "ae_b": (df[b] - df["true"]).abs(),
            "se_a": (df[a] - df["true"]) ** 2,
            "se_b": (df[b] - df["true"]) ** 2,
        }
    ).groupby("pid")
    s, n = g.sum(), g.size()
    mae_d, rmse_d = [], []
    for d in draws:
        ss, nn = s.loc[d].sum(), n.loc[d].sum()
        mae_d.append((ss["ae_a"] - ss["ae_b"]) / nn)
        rmse_d.append(np.sqrt(ss["se_a"] / nn) - np.sqrt(ss["se_b"] / nn))
    ae_a, ae_b = (df[a] - df["true"]).abs().mean(), (df[b] - df["true"]).abs().mean()
    se_a, se_b = ((df[a] - df["true"]) ** 2).mean(), ((df[b] - df["true"]) ** 2).mean()
    return {
        "mae_diff": r3(ae_a - ae_b),
        "mae_diff_ci95": ci(mae_d),
        "rmse_diff": r3(np.sqrt(se_a) - np.sqrt(se_b)),
        "rmse_diff_ci95": ci(rmse_d),
    }


def main() -> None:
    t0 = time.time()
    bundle = ModelBundle.load(REPO / "artifacts/model_bundle.pkl")
    cp = bundle.cohort_params
    cohort = generate_cohort(**cp)
    start = pd.Timestamp(cohort.start_utc)
    inp, plasma = reconstruct(cp["n_patients"], cp["days"], cp["seed"])
    ids = [r.patient_id for r in cohort.records]
    pos = {p: i for i, p in enumerate(ids)}
    split = {r.patient_id: r.split for r in cohort.records}
    tg = cohort.true_glucose.pivot(index="timestamp", columns="patient_id", values="glucose")[ids].to_numpy().T
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

    rows = []
    for off in OFFSETS_H:
        batch = []
        for pid in ids:
            tm, v = cgm_by[pid]
            k = np.searchsorted(tm, first[pid] + off * 60, side="right") - 1
            a, cur = int(tm[k]), float(v[k])
            if cur > 180:
                continue
            batch += [(pid, off, a, cur, g) for g in GRAMS]
        w = paired_walk_delta(
            inp,
            np.array([pos[b[0]] for b in batch]),
            np.array([b[2] for b in batch]),
            np.array([b[4] for b in batch], dtype=float),
            walk_offset_min=WALK["offset_min"],
            walk_minutes=WALK["minutes"],
            walk_steps_per_min=WALK["steps_per_min"],
        )
        for (pid, o, _a, cur, g), ww in zip(batch, w, strict=True):
            rows.append({"pid": pid, "split": split[pid], "off": o, "cur": cur, "g": g}
                        | {f"w{h}": float(ww[h]) for h in HORIZONS})
    df = pd.DataFrame(rows)
    print(f"walk truth: {len(df)} scenarios; {time.time() - t0:.0f}s", flush=True)

    tr = df[df["split"] == "train"]
    fit = {
        "cohort_constant": {h: float(tr[f"w{h}"].mean()) for h in HORIZONS},
        "cohort_by_grams": {h: tr.groupby("g")[f"w{h}"].mean().to_dict() for h in HORIZONS},
        "glucose_scaled": {
            h: float((tr["cur"] * tr[f"w{h}"]).sum() / (tr["cur"] ** 2).sum()) for h in HORIZONS
        },
    }

    def predict(cand: str, d: pd.DataFrame, h: int) -> np.ndarray:
        if cand == "cohort_constant":
            return np.full(len(d), fit[cand][h])
        if cand == "cohort_by_grams":
            return d["g"].map(fit[cand][h]).to_numpy(dtype=float)
        return fit[cand][h] * d["cur"].to_numpy()

    va = df[df["split"] == "validation"]
    val = {}
    for cand in ORDER:
        maes = {h: float(np.abs(predict(cand, va, h) - va[f"w{h}"]).mean()) for h in HORIZONS}
        val[cand] = {"validation_mae": {str(h): r3(m) for h, m in maes.items()},
                     "mean_validation_mae": r3(np.mean(list(maes.values())))}
    sel = min(ORDER, key=lambda c: (val[c]["mean_validation_mae"], ORDER.index(c)))
    print(f"selected {sel}; {time.time() - t0:.0f}s", flush=True)

    te = df[df["split"] == "test"].reset_index(drop=True)
    test_ids = sorted(te["pid"].unique())
    rng = np.random.default_rng(SEED)
    draws = [rng.choice(test_ids, size=len(test_ids), replace=True) for _ in range(BOOT)]
    test = {}
    for h in HORIZONS:
        d = pd.DataFrame({"pid": te["pid"], "true": te[f"w{h}"], "selected": predict(sel, te, h),
                          "no_effect": 0.0, "cohort_constant": predict("cohort_constant", te, h)})
        res = {
            "n_scenarios": len(d),
            "n_patients": len(test_ids),
            "mean_true_walk_effect": r3(d["true"].mean()),
            "true_effect_range": [r3(d["true"].min()), r3(d["true"].max())],
            "share_true_negative": r3((d["true"] < 0).mean()),
            "selected": metrics(d["selected"].to_numpy(), d["true"].to_numpy()),
            "no_effect": metrics(d["no_effect"].to_numpy(), d["true"].to_numpy()),
            "vs_no_effect": paired_ci(d, "selected", "no_effect", draws),
        }
        if sel != "cohort_constant":
            res["cohort_constant"] = metrics(d["cohort_constant"].to_numpy(), d["true"].to_numpy())
            res["vs_cohort_constant"] = paired_ci(d, "selected", "cohort_constant", draws)
        test[str(h)] = res

    served = {"kind": sel}
    if sel == "glucose_scaled":
        served["beta_per_mg_dl"] = {str(h): round(fit[sel][h], 5) for h in HORIZONS}
    elif sel == "cohort_constant":
        served["mg_dl"] = {str(h): round(fit[sel][h], 2) for h in HORIZONS}
    else:
        served["mg_dl_by_grams"] = {str(h): {str(g): round(v, 2) for g, v in fit[sel][h].items()} for h in HORIZONS}

    out = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "protocol": PROTOCOL,
        "model_version_of_cohort_bundle": bundle.model_version,
        "status": "synthetic simulator only; research estimator; not clinical evidence; not exercise advice",
        "walk": WALK | {"total_steps": int(WALK["minutes"] * WALK["steps_per_min"])},
        "counts": {s: {"patients": int(df[df["split"] == s]["pid"].nunique()), "scenarios": int((df["split"] == s).sum())}
                   for s in ("train", "validation", "test")},
        "train_fit": {
            "cohort_constant": {str(h): r3(v) for h, v in fit["cohort_constant"].items()},
            "glucose_scaled_beta": {str(h): round(v, 5) for h, v in fit["glucose_scaled"].items()},
        },
        "validation": {"candidates": val, "selected": sel},
        "test": test,
        "served_coefficients": served,
        "bootstrap": {"resamples": BOOT, "seed": SEED, "unit": "test patient"},
        "runtime_s": round(time.time() - t0, 1),
    }
    OUT_JSON.write_text(json.dumps(out, indent=2) + "\n")
    OUT_MD.write_text(render_md(out))
    print(f"wrote {OUT_JSON.name} and {OUT_MD.name}; {time.time() - t0:.0f}s", flush=True)


def render_md(r: dict) -> str:
    v = r["validation"]
    lines = [
        "# Post-meal walk effect: train-fitted, validation-selected (protocol addendum v4)",
        "",
        f"Generated by `scripts/validate_walk_whatif.py` from `{r['protocol']}`. Synthetic simulator only; "
        "a research estimator; not clinical evidence and not exercise advice.",
        "",
        f"Walk: +{r['walk']['steps_per_min']:.0f} steps/min for {r['walk']['minutes']} min "
        f"({r['walk']['total_steps']:,} steps) starting {r['walk']['offset_min']} min after the meal. "
        "Truth: paired simulator difference (meal + walk minus meal only) in noiseless interstitial glucose.",
        "",
        "The served tree models see only past steps (30 and 60 min before the forecast moment), so they cannot "
        "represent a planned walk; the twin has no learned per-patient activity parameter, so every candidate "
        "is cohort level.",
        "",
        "Validation (mean MAE over +30/60/120 min): "
        + "; ".join(f"{c} {d['mean_validation_mae']:.2f}" for c, d in v["candidates"].items())
        + f". **Selected: {v['selected']}.**",
        "",
        "| Horizon | n | Mean true walk effect | Selected MAE / RMSE | No-effect MAE / RMSE | Selected - no effect, MAE [95% CI] | RMSE [95% CI] |",
        "|---|---|---|---|---|---|---|",
    ]
    for h, t in r["test"].items():
        s, z, c = t["selected"], t["no_effect"], t["vs_no_effect"]
        lines.append(
            f"| +{h} min | {t['n_scenarios']:,} | {t['mean_true_walk_effect']:+.1f} | {s['mae']:.1f} / {s['rmse']:.1f} | "
            f"{z['mae']:.1f} / {z['rmse']:.1f} | {c['mae_diff']:+.2f} [{c['mae_diff_ci95'][0]:+.2f}, "
            f"{c['mae_diff_ci95'][1]:+.2f}] | {c['rmse_diff']:+.2f} [{c['rmse_diff_ci95'][0]:+.2f}, "
            f"{c['rmse_diff_ci95'][1]:+.2f}] |"
        )
    lines += [
        "",
        f"95% CIs: {r['bootstrap']['resamples']:,} paired test-patient bootstrap resamples (seed {r['bootstrap']['seed']}).",
        "The size of the walk effect is a property of the simulator's built-in exercise model "
        "(-ex_gain x activity x glucose), not evidence about real walking.",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    main()
