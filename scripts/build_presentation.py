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
