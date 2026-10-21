"""Audit the what-if meal comparisons of the SERVED models on held-out test patients (backlog B-22).

For every held-out test patient, at replay points spread across the 14 days, and for a range of
meal sizes, this calls the same service method the API serves and records:

* the primary comparison  — scenario vs a zero-carb meal logged at the same time;
* the secondary comparison — scenario vs no meal (includes the learned meal-timing expectation);
* feature-vector validity of the three legs (only the intended inputs differ between legs);
* how close a 1 g meal is to the explicit zero-carb reference (why 1 g is not used as the reference);
* the two demo moments used in docs/DEMO_SCRIPT.md (SYN-0039 at 07:55 and 08:55 local).

These are statistics about learned model associations on synthetic data, not physiological effects.
Nothing is ingested into any twin. Runtime: about 3-5 minutes on the default cohort.

Usage:  .venv/bin/python scripts/counterfactual_audit.py [--out reports/counterfactual_audit.json]
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from glucotwin.config import (
    COUNTERFACTUAL_REFERENCE_GRAMS,
    COUNTERFACTUAL_RELIABLE_MIN_GRAMS,
    COUNTERFACTUAL_RISK_SATURATION,
)
from glucotwin.models.bundle import ModelBundle
from glucotwin.service import TwinService

GRAMS = (5, 10, 20, 30, 40, 60, 90, 120, 200)
OFFSETS_H = tuple(float(x) for x in np.arange(26.0, 330.0, 9.5))  # 32 points, varied local clock times
HORIZONS = ("30", "60", "120")
GLUCOSE_TOL, RISK_TOL = 2.0, 0.01  # "material" change thresholds (mg/dL, probability)
CARB_FEATURES = {"carbs_30", "carbs_60", "carbs_120", "carbs_on_board", "expected_meal_rise"}
DEMO = {"07:55": 0, "08:55": 60}  # SYN-0039 replay from 151.833 h, then +60 min


def _features_ok(eng, grams: float) -> bool:
    """Reference differs from baseline only by minutes_since_meal -> 0; scenario from reference only by carbs."""
    t0, rows, reason = eng._counterfactual_features(grams)
    if reason is not None:
        return True
    b, r, s = (rows[k].loc[t0] for k in ("baseline", "reference", "scenario"))
    diff_rb = {c for c in b.index if not np.isclose(b[c], r[c], equal_nan=True)}
    diff_sr = {c for c in b.index if not np.isclose(r[c], s[c], equal_nan=True)}
    return (diff_rb <= {"minutes_since_meal"} and r["minutes_since_meal"] == 0 and s["minutes_since_meal"] == 0
            and diff_sr <= CARB_FEATURES and s["carbs_30"] >= r["carbs_30"] + grams - 1e-6)


def _share(values: list[float], thr: float) -> float:
    a = np.asarray(values, dtype=float)
    return round(float((a < thr).mean()), 4) if a.size else float("nan")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", type=Path, default=Path("artifacts/model_bundle.pkl"))
    ap.add_argument("--out", type=Path, default=Path("reports/counterfactual_audit.json"))
    args = ap.parse_args()
    logging.getLogger("glucotwin").setLevel(logging.WARNING)
    t_start = time.time()
    svc = TwinService(ModelBundle.load(args.bundle), report_path=None)

    rows, invalid, one_gram, points = [], 0, [], 0
    for pid in svc.demo_patient_ids():
        for off in OFFSETS_H:
            svc.create_replay(pid, off)
            eng = svc.engines[pid]
            first = svc.counterfactual(pid, GRAMS[0])
            if first.primary is None or first.baseline.current_glucose_mg_dl is None \
                    or first.baseline.current_glucose_mg_dl > 180:  # same eligibility as the event target
                continue
            points += 1
            ref1 = svc.counterfactual(pid, 1.0).primary  # 1 g minus the explicit 0 g reference
            one_gram.append((max(abs(v) for v in ref1.delta_glucose_mg_dl.values()), abs(ref1.delta_probability or 0.0)))
            for g in GRAMS:
                res = first if g == GRAMS[0] else svc.counterfactual(pid, g)
                invalid += 0 if _features_ok(eng, float(g)) else 1
                rows.append({"g": g, "pid": pid, "off": off, "p": res.primary.model_dump(), "s": res.secondary.model_dump()})

    def table(kind: str) -> dict:
        out = {}
        for g in GRAMS:
            sel = [r[kind] for r in rows if r["g"] == g]
            out[str(g)] = {
                **{f"share_delta{h}_below_minus2": _share([c["delta_glucose_mg_dl"][h] for c in sel], -GLUCOSE_TOL)
                   for h in HORIZONS},
                "share_delta_risk_below_minus0.01": _share([c["delta_probability"] for c in sel], -RISK_TOL),
                "median_delta60": round(float(np.median([c["delta_glucose_mg_dl"]["60"] for c in sel])), 2),
                "median_delta120": round(float(np.median([c["delta_glucose_mg_dl"]["120"] for c in sel])), 2),
                "median_delta_risk": round(float(np.median([c["delta_probability"] for c in sel])), 4),
            }
        return out

    def monotone(kind: str, key: str, tol: float) -> int:
        n = 0
        for pid, off in {(r["pid"], r["off"]) for r in rows}:
            seq = sorted((r for r in rows if r["pid"] == pid and r["off"] == off), key=lambda r: r["g"])
            v = [r[kind]["delta_probability"] if key == "risk" else r[kind]["delta_glucose_mg_dl"][key] for r in seq]
            n += bool(np.all(np.diff(v) >= -tol))
        return n

    demo = {}
    st = svc.create_replay("SYN-0039", 151.833)
    for label, step in DEMO.items():
        if step:
            svc.step_replay(st.session_id, step)
        demo[label] = {}
        for g in (20, 60, 120):
            r = svc.counterfactual("SYN-0039", g)
            demo[label][str(g)] = {
                "baseline_risk": round(r.baseline.excursion.probability, 4),
                "reference_risk": round(r.primary.reference_probability, 4),
                "scenario_risk": round(r.scenario.excursion.probability, 4),
                "primary_delta_glucose": r.primary.delta_glucose_mg_dl,
                "secondary_delta_glucose": r.secondary.delta_glucose_mg_dl,
                "primary_risk_saturated": r.primary.risk_saturated,
                "small_meal_unreliable": r.small_meal_unreliable,
            }

    g1 = np.asarray(one_gram)
    report = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "model_version": svc.bundle.model_version,
        "what": "What-if meal comparisons of the served models on held-out synthetic test patients. "
                "Learned model associations, not physiological effects.",
        "design": {"test_patients": len(svc.demo_patient_ids()), "replay_offsets_h": list(OFFSETS_H),
                   "eligible_points": points, "meal_grams": list(GRAMS), "scenarios": len(rows),
                   "eligibility": "latest CGM <= 180 mg/dL and a forecast was not withheld",
                   "reference_grams": COUNTERFACTUAL_REFERENCE_GRAMS,
                   "reliable_min_grams": COUNTERFACTUAL_RELIABLE_MIN_GRAMS,
                   "risk_saturation": COUNTERFACTUAL_RISK_SATURATION,
                   "material_thresholds": {"glucose_mg_dl": -GLUCOSE_TOL, "risk": -RISK_TOL}},
        "feature_validity_violations": invalid,
        "one_gram_vs_zero_carb_reference": {
            "max_abs_glucose_delta_mg_dl": round(float(g1[:, 0].max()), 3),
            "max_abs_risk_delta": round(float(g1[:, 1].max()), 4),
            "median_abs_risk_delta": round(float(np.median(g1[:, 1])), 4),
            "conclusion": "not exactly equivalent; the explicit zero-carb reference is used",
        },
        "primary_vs_zero_carb_meal_now": table("p"),
        "secondary_vs_no_meal": table("s"),
        "non_decreasing_in_grams_points": {
            "of": points,
            "primary_delta60_tol2": monotone("p", "60", GLUCOSE_TOL),
            "primary_delta120_tol2": monotone("p", "120", GLUCOSE_TOL),
            "primary_risk_tol0.01": monotone("p", "risk", RISK_TOL),
            "secondary_delta60_tol2": monotone("s", "60", GLUCOSE_TOL),
        },
        "demo_SYN-0039": demo,
        "runtime_s": round(time.time() - t_start, 1),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("design", "feature_validity_violations",
                                              "one_gram_vs_zero_carb_reference", "non_decreasing_in_grams_points")},
                     indent=1))
    print(f"wrote {args.out} in {report['runtime_s']} s")


if __name__ == "__main__":
    main()
