"""Fill docs/submission/src/presentation.template.html with numbers from reports/audit_report.json.

No metric in the deck is typed by hand except the headline table copied from evaluation_report.json (checked
against it below). Usage:  .venv/bin/python scripts/build_presentation.py  then run export_submission_pdfs.mjs.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "docs/submission/src"


def pct(x: float) -> str:
    return f"{100 * x:.0f}%"


def ci(v, fmt="{:.3f}") -> str:
    return f"{fmt.format(v[0])}–{fmt.format(v[1])}"


def rng(vals, fmt) -> str:
    return f"{fmt(min(vals))}–{fmt(max(vals))}"


# Paired-simulator truth for SYN-0039, 35 g at 07:55, +120 min (docs/research/TWIN_VALIDITY.md section B);
# tests/test_twin_curve_agp_fhir_ingest.py::test_demo_example_ground_truth reproduces it from the simulator.
DEMO_TRUTH_120 = 65.4


def twin_validity_values() -> dict[str, str]:
    """Tokens for the twin-validity slide, read from the research reports and the recorded static snapshot."""
    tv = json.loads((ROOT / "reports/research/twin_validity.json").read_text())
    tw = json.loads((ROOT / "reports/research/twin_and_whatif_validation.json").read_text())
    snap = json.loads((ROOT / "frontend/static-demo/demo/early-warning.json").read_text())
    rec = {x["day"]: x["pearson_r"] for x in tv["A2_latent_sensitivity_recovery"]["test_patients"]}
    pm = tw["A_post_meal_personalisation_ablation"]["by_horizon"]["60"]
    wi = tw["B_whatif_extra_grams"]["by_horizon"]["120"]
    d = tw["D_train_fitted_validation_selected_curve"]
    dt = d["test_all_grams"]
    personal = snap["frames"][0]["state"]["personal"]
    w35 = next(w["result"] for w in snap["whatifs"] if w["frame_index"] == 0 and w["grams"] == 35)
    walk = json.loads((ROOT / "reports/research/walk_whatif_validation.json").read_text())["test"]["120"]
    entries = snap["fhir"]["bundle"]["entry"]
    kinds: dict[str, int] = {}
    for e in entries:
        kinds[e["resource"]["resourceType"]] = kinds.get(e["resource"]["resourceType"], 0) + 1
    probs = [p["probabilityDecimal"] for e in entries if e["resource"]["resourceType"] == "RiskAssessment"
             for p in e["resource"]["prediction"] if "probabilityDecimal" in p]
    names = {"median_uncal": "median shape, no calibration", "mean_uncal": "mean shape, no calibration",
             "median_cal": "median shape, validation-calibrated", "mean_cal": "mean shape, validation-calibrated"}
    def f2(x: float) -> str:
        return f"{x:+.1f}".replace("-", "\u2212")

    def ci2(pair: list[float]) -> str:
        return ", ".join(f"{x:+.1f}".replace("-", "\u2212") for x in pair)

    return {
        "rec_r0": f"{rec[0]:.2f}", "rec_r3": f"{rec[3]:.2f}", "rec_r14": f"{rec[14]:.2f}",
        "pm_diff": f"{pm['rmse']['ablated_minus_served']:+.2f}", "pm_ci": ci(pm["rmse"]["ci95_patient_bootstrap"], "{:.2f}"),
        "pm_served": f"{pm['rmse']['served']:.2f}", "pm_abl": f"{pm['rmse']['ablated']:.2f}", "pm_rows": f"{pm['n_rows']:,}",
        "conf_w": pct(personal["observed_weight"]), "conf_n": str(personal["meals_used"]),
        "conf_se": f"{personal['sampling_se_mg_dl_per_g']:.2f}",
        "wi_mae": f"{wi['whatif']['mae']:.1f}", "co_mae": f"{wi['baseline']['mae']:.1f}",
        "wi_diff": f2(wi["mae_whatif_minus_baseline"]), "wi_ci": ci2(wi["mae_whatif_minus_baseline_ci95"]),
        "d_sel": names[d["validation"]["selected"]],
        "d_mae": f"{dt['120']['curve']['mae']:.1f}", "d_co": f"{dt['120']['cohort_average']['mae']:.1f}",
        "d_wi": f"{dt['120']['served_whatif']['mae']:.1f}",
        "d_diff": f2(dt["120"]["vs_cohort_average"]["mae_diff"]), "d_ci": ci2(dt["120"]["vs_cohort_average"]["mae_diff_ci95"]),
        "d_mae30": f"{dt['30']['curve']['mae']:.1f}", "d_mae60": f"{dt['60']['curve']['mae']:.1f}",
        "d_co30": f"{dt['30']['cohort_average']['mae']:.1f}", "d_co60": f"{dt['60']['cohort_average']['mae']:.1f}",
        "fhir_counts": " · ".join(f"{n} {k}" for k, n in sorted(kinds.items())),
        "fhir_p": f"probabilityDecimal {probs[0]:.3f} at the replay start" if probs else "none recorded",
        "lb_ppv": f'{100 * tv["D_lower_bound_below_70_rule"]["test"]["all"]["ppv"]:.1f}%',
        "tc_served": f"{w35['primary']['delta_glucose_mg_dl']['120']:+.1f}",
        "tc_curve": f"{w35['twin_curve']['delta_glucose_mg_dl']['120']:+.1f}",
        "tc_truth": f"{DEMO_TRUTH_120:+.1f}",
        "walk_mae": f"{walk['selected']['mae']:.1f}", "walk_none": f"{walk['no_effect']['mae']:.1f}",
    }


def main() -> None:
    a = json.loads((ROOT / "reports/audit_report.json").read_text())
    ev = json.loads((ROOT / "reports/evaluation_report.json").read_text())
    # guard: the hand-copied headline numbers in the template must match the committed report
    e = {x["model"]: x for x in ev["event"]}
    t = {(x["model"], x["horizon_min"]): x for x in ev["trajectory"]}
    assert round(e["logistic_regression"]["auroc"], 3) == 0.884 and round(e["hist_gradient_boosting"]["auroc"], 3) == 0.936
    assert round(e["trend_rule"]["auroc"], 3) == 0.655
    assert round(t[("hist_gradient_boosting", 30)]["rmse_mg_dl"], 1) == 10.4
    assert round(t[("hist_gradient_boosting", 120)]["rmse_mg_dl"], 1) == 25.9
    assert round(t[("persistence", 30)]["rmse_mg_dl"], 1) == 18.7
    assert all(a["consistency_with_pipeline_report"][k] if isinstance(a["consistency_with_pipeline_report"][k], bool)
               else all(a["consistency_with_pipeline_report"][k].values()) for k in a["consistency_with_pipeline_report"])

    b = a["bootstrap_95ci_patient_level"]
    g = a["main"]["event"]["logistic_regression"]["grid"]  # served threshold
    seeds = a["seed_robustness"]["other_seeds"].values()
    ab = a["ablation"]
    st = a["stress_test"]
    n_tests = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:warnings"], cwd=ROOT,
                             capture_output=True, text=True).stdout
    per_file = [int(x) for x in re.findall(r"^tests/\S+\.py: (\d+)$", n_tests, flags=re.M)]  # pytest 9 -q format
    vals = {
        "ci_rmse30": ci(b["rmse30_hgb"], "{:.1f}"), "ci_rmse120": ci(b["rmse120_hgb"], "{:.1f}"),
        "ci_auroc_trend": ci(b["auroc_trend"]), "ci_auroc_log": ci(b["auroc_logistic"]), "ci_auroc_hgb": ci(b["auroc_hgb"]),
        "ev_any": pct(g["event_sensitivity_any_alert"]), "ci_ev_any": ci(b["evsens_any_logistic"], "{:.2f}"),
        "ev_30": pct(g["event_sensitivity_lead_ge_30min"]),
        "ev_sus": pct(g["event_sensitivity_sustained"]), "ci_ev_sus": ci(b["evsens_sustained_logistic"], "{:.2f}"),
        "lead_any": f"{g['median_lead_any_alert_min']:.0f}", "lead_sus": f"{g['median_lead_sustained_min']:.0f}",
        "fa": f"{g['false_alert_episodes_per_monitored_day']:.2f}", "ci_fa": ci(b["fa_per_monitored_day_logistic"], "{:.2f}"),
        "seed_auroc": rng([s["auroc_logistic_regression"] for s in seeds], "{:.3f}".format),
        "seed_sus": rng([s["logistic_event_sensitivity_sustained"] for s in seeds], pct),
        "abl_noehr": f"{ab['no_record_features']['auroc_logistic_regression']:.3f}",
        "abl_noehr_sus": pct(ab["no_record_features"]["logistic_event_sensitivity_sustained"]),
        "abl_nomeal": f"{ab['no_meal_features']['auroc_logistic_regression']:.3f}",
        "abl_nomeal_sus": pct(ab["no_meal_features"]["logistic_event_sensitivity_sustained"]),
        "stress_auroc": f"{st['auroc_logistic_regression']:.3f}", "stress_sus": pct(st["logistic_event_sensitivity_sustained"]),
        "stress_rmse30": f"{st['rmse30_hist_gradient_boosting']:.1f}", "stress_30": pct(st["logistic_event_sensitivity_lead_ge_30min"]),
        "n_tests": str(sum(per_file)) if per_file else "?",
        "n_frontend": str(sum(len(re.findall(r"^\s*test\(", f.read_text(), re.M)) for f in (ROOT / "frontend/tests").glob("*.ts"))),
        **twin_validity_values(),
    }
    html = (SRC / "presentation.template.html").read_text()
    for k, v in vals.items():
        html = html.replace("{{" + k + "}}", v)
    left = re.findall(r"\{\{\w+\}\}", html)
    if left:
        raise SystemExit(f"unfilled tokens: {left}")
    (SRC / "presentation.html").write_text(html)
    print(json.dumps(vals, indent=1))


if __name__ == "__main__":
    main()
