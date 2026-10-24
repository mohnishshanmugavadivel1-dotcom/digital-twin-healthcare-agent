"""ShanghaiT2DM real-CGM experiment (research only). Stages:

    .venv/bin/python scripts/shanghai_experiment.py compat   # frozen-model compatibility (no data needed)
    .venv/bin/python scripts/shanghai_experiment.py audit    # verified archive -> per-session audit only
    .venv/bin/python scripts/shanghai_experiment.py run      # audit + split + models + one test pass + report

``audit`` and ``run`` refuse to start unless data/real/shanghai/diabetes_datasets.zip exists, its size and md5 match
the official Figshare v5 file, and the provenance written by scripts/fetch_shanghai_t2dm.py is present.
Outputs: reports/real_data/shanghai_t2dm/ (results.json, REPORT_<date>.md, plots/) and the separate model artifact
artifacts/real_data/shanghai_t2dm/models.pkl (gitignored). Production artifacts and reports are never touched.
Needs the optional readers: .venv/bin/pip install --require-hashes -r requirements-realdata.lock
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ARCHIVE = REPO / "data/real/shanghai/diabetes_datasets.zip"
PROVENANCE = REPO / "data/real/shanghai/provenance.json"
CONFIG = REPO / "experiments/shanghai_t2dm/config.json"
OUT = REPO / "reports/real_data/shanghai_t2dm"
ARTIFACTS = REPO / "artifacts/real_data/shanghai_t2dm"
PROTECTED = [REPO / "artifacts/model_bundle.pkl", REPO / "reports/evaluation_report.json",
             REPO / "reports/audit_report.json", REPO / "reports/counterfactual_audit.json"]


def verified_archive(cfg: dict) -> tuple[Path, dict] | None:
    if not ARCHIVE.is_file() or not PROVENANCE.is_file():
        print(f"BLOCKED: verified archive not found. Expected {ARCHIVE} and {PROVENANCE}.\n"
              "Place the official file with: python3 scripts/fetch_shanghai_t2dm.py --archive <path-to-zip>",
              file=sys.stderr)
        return None
    md5, n = hashlib.md5(), 0
    with open(ARCHIVE, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            md5.update(chunk)
            n += len(chunk)
    if md5.hexdigest() != cfg["data"]["archive_md5"] or n != cfg["data"]["archive_size_bytes"]:
        print(f"REJECTED: archive md5/size {md5.hexdigest()}/{n} do not match the official v5 file", file=sys.stderr)
        return None
    prov = json.loads(PROVENANCE.read_text())
    if prov.get("verified", {}).get("md5") != cfg["data"]["archive_md5"]:
        print("REJECTED: provenance.json does not record the official md5", file=sys.stderr)
        return None
    return ARCHIVE, prov


def write_public(res: dict, pub: Path) -> None:
    from glucotwin.realdata import plots, public
    pub.mkdir(parents=True, exist_ok=True)
    summ = public.public_summary(res)
    (pub / "summary.json").write_text(json.dumps(summ, indent=2) + "\n")
    (pub / "SUMMARY.md").write_text(public.public_markdown(summ))
    bars = [{"label": f"{h} min", "model": m, "value": t["metrics"][m]["rmse"],
             "lo": t["bootstrap"]["ci95"][m]["rmse"][0], "hi": t["bootstrap"]["ci95"][m]["rmse"][1]}
            for h, t in res["test_results"].items() for m in t["metrics"]]
    (pub / "rmse_by_horizon.svg").write_text(plots.bars_svg(
        "ShanghaiT2DM held-out test RMSE, 95% patient-bootstrap CI (20 test patients)", bars,
        names=public.MODEL_NAMES,
        subtitle="Glucose-history-only models trained on ShanghaiT2DM. Not the GlucoTwin model (not evaluated)."))


def post_hoc(archive: Path, res: dict) -> dict:
    """Descriptive observations added after the data were seen. They never feed back into modelling."""
    import zipfile

    from glucotwin.realdata import pipeline
    series, _, _ = pipeline.audit_archive(archive, res["config"])
    lo = float(series["glucose"].min())
    at_lo = series[series["glucose"] <= lo + 1e-9]
    with zipfile.ZipFile(archive) as zf:
        note = next((n for n in zf.namelist() if n.rsplit("/", 1)[-1] == "note.txt"), None)
        text = zf.read(note).decode("utf-8", "replace") if note else ""
    english = " ".join(ln.strip() for ln in text.splitlines() if ln.strip() and ln.strip().isascii())
    return {"note": "added after data inspection; descriptive only",
            "readings_at_lowest_recorded_value": {"value_mg_dl": lo, "n_readings": int(len(at_lo)),
                                                  "n_sessions": int(at_lo["session_id"].nunique())},
            "highest_recorded_value_mg_dl": float(series["glucose"].max()),
            "archive_note": english}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["compat", "audit", "run", "report", "publish"])
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--artifacts", type=Path, default=ARTIFACTS)
    args = ap.parse_args(argv)
    for p in (args.out, args.artifacts):
        if any(p.resolve() == q.resolve() or q.resolve().is_relative_to(p.resolve()) for q in PROTECTED):
            print(f"REFUSED: {p} would contain a protected production file", file=sys.stderr)
            return 4
    cfg = json.loads(CONFIG.read_text())
    from glucotwin.realdata import compat
    args.out.mkdir(parents=True, exist_ok=True)
    if args.stage == "compat":
        (args.out / "frozen_model_compatibility.json").write_text(json.dumps(compat.frozen_model_compatibility(), indent=2) + "\n")
        print(f"wrote {args.out / 'frozen_model_compatibility.json'}")
        return 0
    if args.stage == "publish":  # aggregate-only public summary from an existing results.json (no data needed)
        write_public(json.loads((args.out / "results.json").read_text()), args.out / "public")
        print(f"wrote aggregate-only {args.out / 'public'}")
        return 0
    if args.stage == "report":  # re-render REPORT_<date>.md from an existing results.json (no retraining)
        from glucotwin.realdata import report as rep
        res = json.loads((args.out / "results.json").read_text())
        (args.out / f"REPORT_{res['generated_at'][:10]}.md").write_text(rep.render_report(res))
        print(f"re-rendered {args.out}/REPORT_{res['generated_at'][:10]}.md")
        return 0
    got = verified_archive(cfg)
    if got is None:
        return 2
    archive, prov = got
    prov = dict(prov)  # the fetch script's note was written before the files were inspected: keep it, labelled as such
    if "note" in prov:
        prov["fetch_time_note"] = prov.pop("note")
    from glucotwin.realdata import pipeline, report
    if args.stage == "audit":
        _series, records, arch = pipeline.audit_archive(archive, cfg)
        (args.out / "audit.json").write_text(json.dumps({"provenance": prov, "archive_audit": arch, "sessions": records},
                                                        indent=2, default=str) + "\n")
        print(f"wrote {args.out / 'audit.json'}")
        return 0
    res = pipeline.run_experiment(archive, args.out, args.artifacts, cfg, "REAL ShanghaiT2DM CGM (Figshare v5)", prov)
    res["post_hoc_observations"] = post_hoc(archive, res)
    (args.out / "results.json").write_text(json.dumps(res, indent=2, default=str) + "\n")
    (args.out / f"REPORT_{res['generated_at'][:10]}.md").write_text(report.render_report(res))
    write_public(res, args.out / "public")
    print(f"wrote {args.out}/results.json and REPORT_{res['generated_at'][:10]}.md; artifact {res['artifact']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
