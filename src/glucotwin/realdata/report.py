"""Render the dated markdown report from results.json only (no hand-typed numbers)."""

from __future__ import annotations

from glucotwin.realdata.public import ATTRIBUTION, MODEL_NAMES, SCOPE


def _ci(c):
    return f"[{c[0]:.2f}, {c[1]:.2f}]"


def _censoring_line(r: dict) -> str:
    parsed = [s for s in r["sessions"] if s.get("status") == "parsed"]
    n_text = sum(s["n_cgm_text_values"] for s in parsed)
    low = r.get("post_hoc_observations", {}).get("readings_at_lowest_recorded_value")
    txt = f"- CGM text values (e.g. LO/HI) excluded: {n_text}."
    if low:
        txt += (f" {low['n_readings']} readings in {low['n_sessions']} sessions sit at the lowest recorded value "
                f"({low['value_mg_dl']} mg/dL, plausibly the sensor's lower reporting limit); they are kept as recorded, so "
                "low glucose is left-censored. The pre-registered sensor-limit flag (exactly 40/500 mg/dL) did not match "
                "this encoding and reports 0 (observation made after seeing the data; modelling unaffected).")
    return txt


def render_report(r: dict) -> str:
    c, cfg, prov = r["counts"], r["config"], r.get("provenance") or {}
    src = (prov.get("source") or {})
    lines = [
        f"# ShanghaiT2DM CGM forecasting experiment — {r['generated_at'][:10]}",
        "",
        f"**Data: {r['data_label']}.** Research experiment on retrospective CGM recordings. Not clinical validation; "
        "retrospective forecasting accuracy does not establish clinical utility. Not a medical device.",
        "",
        f"**Scope.** {SCOPE}",
        "",
        "**Private report.** Contains dataset patient/session identifiers, per-patient metrics and individual readings. "
        "Do not publish; the aggregate-only version is `public/SUMMARY.md`.",
        "",
        f"**Attribution.** {ATTRIBUTION}",
        "",
        "## 1. Dataset and provenance",
        f"- Citation: {src.get('citation', 'n/a')}",
        f"- Version / DOI: v{src.get('version', '?')} / {src.get('doi', 'n/a')}; licence {src.get('license', 'n/a')}",
        f"- Archive verified: md5 `{(prov.get('verified') or {}).get('md5', 'n/a')}`, sha256 "
        f"`{(prov.get('verified') or {}).get('sha256', 'n/a')}`, {(prov.get('verified') or {}).get('size_bytes', 'n/a')} bytes",
        f"- Protocol `{cfg['protocol']}` registered {cfg['registered_on']} before data access; config sha256 "
        f"`{r['config_sha256']}`; seed {cfg['seed']}",
        "",
        *([f"- In-archive documentation (`note.txt`): {r['post_hoc_observations']['archive_note']}"]
          if r.get("post_hoc_observations", {}).get("archive_note") else []),
        "",
        "## 2. Counts",
        f"- Session workbooks in `{cfg['data']['folder']}`: {c['session_workbooks']} "
        f"(parsed {c['sessions_parsed']}, excluded {c['sessions_excluded']})",
        f"- Unique patients parsed: {c['unique_patients_parsed']}; included in modelling: {c['patients_included']}",
        f"- Patients with several sessions: {c['patients_with_multiple_sessions'] or 'none'}",
        f"- Regular CGM readings after cleaning: {c['regular_cgm_readings']}",
        f"- Patients excluded for too few usable windows: {c['patients_excluded_too_few_windows'] or 'none'}",
        "",
        "### Excluded sessions",
    ]
    excl = [s for s in r["sessions"] if s.get("status") != "parsed"]
    lines += [f"- `{s['member']}`: {s['reason']}" for s in excl] or ["- none"]
    lines += ["", "### Per-session audit", "",
              "| session | days | regular readings | missing share | extra excluded | implausible | segments | usable windows (30/60/120) |",
              "|---|---|---|---|---|---|---|---|"]
    for s in r["sessions"]:
        if s.get("status") == "parsed":
            u = s.get("usable_windows_by_horizon", {})
            lines.append(f"| {s['session_id']} | {s['duration_days']} | {s['n_regular_readings']} | {s['missing_share']} | "
                         f"{s['n_extra_readings_excluded']} | {s['n_implausible_dropped']} | {s['n_segments']} | "
                         f"{'/'.join(str(u.get(str(h), 0)) for h in cfg['windows']['horizons_min'])} |")
    sp = r["split"]
    lines += ["", "## 3. Patient-level split", f"Unit: {sp['unit']}; seed {sp['seed']}; fractions {cfg['split']['fractions']}.",
              f"- train ({len(sp['train'])}): {', '.join(sp['train'])}",
              f"- validation ({len(sp['validation'])}): {', '.join(sp['validation'])}",
              f"- test ({len(sp['test'])}): {', '.join(sp['test'])}",
              f"- Leakage checks: {r['leakage_checks']}", "",
              "## 4. Frozen production model", f"Verdict: **{r['frozen_model']['verdict']}**. {r['frozen_model']['decision']}",
              f"Re-check against inspected headers: {r['archive_audit']['frozen_model_recheck']['verdict']} "
              f"({r['archive_audit']['frozen_model_recheck']['decisive_inputs_found']}).", "",
              "## 5. Separately trained real-data models (CGM-only)",
              f"Features: {', '.join(['g0 (latest reading)', 'delta_15/30/60', 'accel_15', 'mean_60', 'std_60', 'tod_sin/cos'])}; "
              f"inputs matched within ±{cfg['windows']['tolerance_min']} min in the same gap-free segment; models predict "
              "the change from the latest reading. Ridge alpha and the gradient-boosting setting were chosen per horizon on "
              "validation patients; models fitted on training patients only; test scored once.", "",
              "| horizon | test windows | test patients | model | MAE | RMSE | RMSE 95% CI | RMSE − persistence (95% CI) |",
              "|---|---|---|---|---|---|---|---|"]
    for h, t in r["test_results"].items():
        b = t["bootstrap"]
        for m, met in t["metrics"].items():
            d = b["difference_vs_persistence_ci95"].get(m, {}).get("rmse")
            diff = f"{met['rmse'] - t['metrics']['persistence']['rmse']:+.2f} {_ci(d)}" if d else "—"
            lines.append(f"| {h} min | {t['n_windows']} | {t['n_patients']} | {MODEL_NAMES.get(m, m)} | {met['mae']:.2f} | {met['rmse']:.2f} | "
                         f"{_ci(b['ci95'][m]['rmse'])} | {diff} |")
    cs = r["test_results_common_subset"]
    lines += ["", "CIs: 95% percentile intervals, 2,000 bootstrap resamples of test patients. Pooled metrics weight "
              "patients by their number of (overlapping, correlated) windows; patient-level resampling accounts for the "
              "correlation."]
    lines += ["", f"Common subset (test anchors with targets at every horizon): {cs['n_windows']} windows, "
              f"{cs['n_patients']} patients: " + "; ".join(
                  f"{h} min RMSE " + ", ".join(f"{m} {v['rmse']:.2f}" for m, v in d.items()) for h, d in cs["by_horizon"].items()),
              "", "Model selection (validation RMSE by candidate):"]
    for h, s in r["selection"].items():
        lines.append(f"- {h} min: ridge chose {s['ridge']['chosen']}; gradient boosting chose {s['hgb']['chosen']}; "
                     f"windows {s['n_windows']}")
    lines += ["", "## 6. Failure cases"]
    for h, f in r["failure_cases"].items():
        lines.append(f"- {h} min: test patients where ridge RMSE > persistence: "
                     f"{f['test_patients_where_ridge_rmse_exceeds_persistence'] or 'none'}")
    lines += ["", "Per-patient metrics are in `results.json` → `test_results.<h>.per_patient`.", "",
              "## 7. Plots", *[f"- `{p}`" for p in r["plots"]],
              "Trajectory plots show individual test-patient readings: private, not for publication.", "",
              "## 8. Model artifact (private, gitignored)",
              *([f"- `{k}`: `{v}`" for k, v in r["artifact"].items() if k != "software"]
                + [f"- software: {r['artifact'].get('software')}"] if isinstance(r.get("artifact"), dict)
                else [f"- {r.get('artifact')}"]), "",
              "## 9. Limitations",
              "- Small cohort; patient-bootstrap CIs are wide and assume test patients are exchangeable."
              + (f" **Only {min(t['n_patients'] for t in r['test_results'].values())} test patients: the CIs are not"
                 " informative.**" if r["test_results"] and min(t["n_patients"] for t in r["test_results"].values()) < 10
                 else ""),
              "- CGM-only models: dietary intake, insulin and medication fields were audited but not used (free text / "
              "completeness unknown); no meal or activity information enters the forecasts.",
              "- FreeStyle Libre readings are interstitial glucose at 15-min resolution; sensor error is not modelled.",
              _censoring_line(r),
              "- Results are not comparable with the synthetic benchmark (different sampling, inputs, population, targets).",
              "- Retrospective accuracy is not clinical utility or safety.", ""]
    return "\n".join(lines)
