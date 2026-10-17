"""Command line entry point: ``glucotwin {train,serve,summary}``."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from glucotwin.synth.generator import DEFAULT_SEED


def _summary(report_path: Path) -> None:
    from glucotwin.contracts import EvaluationReport

    rep = EvaluationReport.model_validate_json(report_path.read_text())
    print(f"model {rep.model_version} | dataset {rep.dataset.name} v{rep.dataset.version} seed {rep.dataset.seed}")
    print(f"patients per split: {rep.dataset.split_patients}")
    print("\nTrajectory (test):  model, horizon, MAE, RMSE, MARD%, Clarke A%, A+B%, coverage")
    for t in rep.trajectory:
        cov = "" if t.interval_coverage is None else f"{t.interval_coverage:.2f}"
        print(f"  {t.model:24s} {t.horizon_min:4d}  {t.mae_mg_dl:6.1f} {t.rmse_mg_dl:6.1f} {t.mard_percent:6.1f} "
              f"{t.clarke_a_pct:6.1f} {t.clarke_ab_pct:6.1f} {cov}")
    print("\nExcursion onset within 120 min (test):")
    for e in rep.event:
        def f(x, fmt="{:.3f}"):
            return "-" if x is None else fmt.format(x)
        print(f"  {e.model:24s} n={e.n} prev={e.prevalence:.3f} AUROC={f(e.auroc)} AUPRC={f(e.auprc)} "
              f"Brier={f(e.brier)} thr={f(e.threshold, '{:.2f}')} sens={f(e.sensitivity)} spec={f(e.specificity)} "
              f"PPV={f(e.ppv)} event_sens={f(e.event_sensitivity)} lead={f(e.median_lead_time_min, '{:.0f}')}min "
              f"false_eps/day={f(e.false_alert_episodes_per_patient_day, '{:.2f}')}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="glucotwin")
    sub = parser.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("train", help="generate synthetic cohort, train, evaluate, write report + bundle")
    t.add_argument("--patients", type=int, default=60)
    t.add_argument("--days", type=int, default=14)
    t.add_argument("--seed", type=int, default=DEFAULT_SEED)
    s = sub.add_parser("serve", help="run the API (and built dashboard, if present)")
    s.add_argument("--host", default="0.0.0.0")
    s.add_argument("--port", type=int, default=8000)
    m = sub.add_parser("summary", help="print the evaluation report")
    m.add_argument("--report", default="reports/evaluation_report.json")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.cmd == "train":
        from glucotwin.evaluation.pipeline import run_pipeline

        run_pipeline(n_patients=args.patients, days=args.days, seed=args.seed)
        _summary(Path("reports/evaluation_report.json"))
    elif args.cmd == "serve":
        import uvicorn

        uvicorn.run("glucotwin.api.app:create_app", factory=True, host=args.host, port=args.port)
    elif args.cmd == "summary":
        _summary(Path(args.report))


if __name__ == "__main__":
    main()
