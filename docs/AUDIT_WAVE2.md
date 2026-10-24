# Wave-2 independent audit (2026-10-17)

> **Note (Historical Sprint Record):** This document is preserved as an engineering development log from earlier waves. For final release metrics (161 Python tests, 50 frontend tests, 83 browser checks, and validated twin-curve / real-data benchmarks), see the root [README.md](../README.md).

Scope: verify every wave-1 claim from the repository, the code and the official competition source; fix verified defects; produce
submission artefacts. "Verified" means re-executed or read from source during this audit. Wave-1 claims were treated as unverified.

## 1. Repository state (verified)

* Branch `arena/65426a60-digital-twin-healthcare-agent`. Wave-1 commit `ec975a4` matched `origin` exactly before wave 2 (69 files).
  `main` is still at `4a487f1` (initial commit; README contains only the repository name).
* The repository is **public** (`gh repo view` → `isPrivate: false`). GitHub Actions CI ran on `ec975a4`: **success** (run 39057300895).
* No secrets were found (`git ls-files` and a grep for key/token/password patterns). `.pkl`, data and build outputs are ignored.
* **Clean-clone reproduction:** a fresh `git clone` plus a new venv from `requirements.lock` gave 45/45 tests passing and `glucotwin train` exit 0.
  `reports/evaluation_report.json` was **identical** to the committed one, apart from timestamps. The frontend built byte-identical asset hashes.

## 2. Findings

| ID | Sev | Finding | Evidence | Resolution |
|---|---|---|---|---|
| F-01 | **P0** | The video requirement in the wave-1 docs ("15–20 min") was wrong. The official text says "**Minimum 20-minute video**" | `details` field of https://unstop.com/api/public/competition/1757873 | Fixed in docs: `DEMO_SCRIPT.md` planned at 22–24 min; COMPETITION.md marked superseded |
| F-02 | **P0** | The submission branch is not on `main`. Evaluators opening the public repo see a near-empty README | `git log origin/main` = `4a487f1` | PR opened; **merging needs the team's authorisation** |
| F-03 | **P0** | README team details and college are missing (official mandatory item) | README "Team" section | **Needs team input** |
| F-04 | **P0** | Architecture diagram PDF and presentation PDF were missing | – | DONE: `docs/submission/GlucoTwin_Architecture.pdf` (1 page), `GlucoTwin_Presentation.pdf` (14 pages); overflow-checked and visually reviewed |
| F-05 | **P0** | No video exists | – | **Needs team (recording)**; script and verified scenes ready |
| F-06 | P1 | The official static data list includes "genetic markers"; the record had none | official `details` | Added synthetic family history + TCF7L2 genotype (separate RNG, display-only, not a feature; test enforced). All metrics unchanged (verified by retrain) |
| F-07 | P1 | "91% of episodes warned" counts **any single alert row** in the 2 h before onset, which is lenient. When the alert must still be on just before onset ("sustained"), the figure is **69%** (95% CI 0.48–0.83) | `metrics.event_metrics`; `glucotwin audit` | Both are now reported (README, deck). Pipeline metric left unchanged for reproducibility |
| F-08 | P1 | With only 12 test patients, no uncertainty was reported | – | Patient-level bootstrap CIs (1000 resamples) in `reports/audit_report.json` |
| F-09 | P1 | Synthetic HbA1c is computed from the **same 14-day window** that is evaluated (corr **0.950** with that window's mean CGM): a future-information channel | `generator._build_records` line `hba1c = (mean_g + 46.7) / 28.7 …` | Quantified by ablation: removing all record features **raises** logistic AUROC 0.884 → 0.907, so no inflation. Disclosed. Fix planned (B-20) |
| F-10 | P1 | Direct record (EHR) features do not improve held-out discrimination (same ablation) | audit `ablation` | Disclosed honestly. The record contributes via the carb-sensitivity prior and clinical context. B-19: consider dropping them after multi-seed confirmation |
| F-11 | P1 | Near-perfect real-time meal logging is the dominant signal (80% of onsets follow a logged meal within 2 h; removing meal features gives AUROC 0.884 → 0.849) | `/tmp` analysis, audit ablation | Added opt-in `Realism` knobs and a stress test: 30-min RMSE 10.4 → 15.4; ≥ 30-min-lead warnings 87% → 78%; AUROC maintained (0.904) |
| F-12 | P2 | `POST /api/replay` returned **HTTP 500** for huge `start_offset_hours` / `duration_hours` (`OutOfBoundsTimedelta`) | server log traceback | Bounds ≤ 8784 h in the contract, so these now return 422. Regression test added |
| F-13 | P2 | Training-split patients could be replayed (in-sample predictions presented like held-out ones) | `POST /api/replay {"patient_id":"SYN-0001"}` → 201 | Restricted to the test split (404). Regression test added |
| F-14 | P2 | A fractional replay offset put the clock off the 5-min grid (02:24:59.88), dropping a boundary reading | live API | Warm-up clock rounded to the 5-min grid |
| F-15 | P2 | Probability 0.9998 was displayed as "100%" (false certainty) | dashboard screenshot | Displayed as ">99%" / "<1%" |
| F-16 | P2 | Trend-rule threshold sat at the edge of the fixed 0.05–0.95 grid (0.05) | `choose_threshold` | Re-chosen over score quantiles in the audit (0.004): 7.1 false alerts/day; conclusions unchanged. Documented |
| F-17 | P2 | pytest 8.4.2 is affected by PYSEC-2026-1845 / CVE-2025-71176 (tmpdir handling; dev-only) | pip-audit | Upgraded to pytest 9.1.1; pip-audit clean |
| F-18 | P2 | Hypoglycaemia is under-represented (TBR 0.37% vs 2.4% published) | sim analysis: TBR 1.76% on SU + insulin, 0.39% on SU only, about 0% on neither (30 patients) | Mechanistic: the only hypo pathway is glucose-independent insulin action. Disclosed; B-16 |
| F-19 | P2 | Model selection and conformal calibration share the validation set (slight optimism in intervals) | `pipeline.py` | Disclosed; test coverage 0.76–0.80 against nominal 0.80 |
| F-20 | P2 | Name collision: at least one other entry in this challenge is called "GlucoTwin" | github.com/adityajaggal2308/GlucoTwin_Dr_Ambedkar_Institute_of_Technology | Team decision |
| F-21 | P2 | The official text is inconsistent: "Top 10" (stage) versus "Top 5" (details) teams shortlisted | official JSON | Informational |

Verified as **correct** (no defect found): patient-level split (36/12/12, disjoint); features only use data ≤ t (interpolation is inside-only,
and rows exist only at readings); carb-sensitivity responses gated by `available_at`; labels are unknown (not negative) at the end of a record;
threshold, model choice and conformal widths are fitted on validation only; baselines and models are scored on identical test rows;
the false-alert denominator (nominal 168 days vs monitored 167.95 days, so the difference is negligible); no CORS opened; Pydantic validation on all bodies.

## 3. Independently reproduced metrics (commands)

```bash
git clone … && python3 -m venv v && v/bin/pip install -r requirements.lock && v/bin/pip install -e . --no-deps
v/bin/glucotwin train          # → reports/evaluation_report.json (identical to committed, except timestamps)
v/bin/glucotwin audit          # → reports/audit_report.json (~5 min, 2 CPUs); first block checks consistency with the report
.venv/bin/python scripts/find_demo_scenario.py   # demo moments on held-out patients
```

Audit consistency block: every AUROC, threshold, warning rate and RMSE matched `evaluation_report.json` exactly (`true` for all keys).

| Metric (served configuration) | Value | 95% patient-bootstrap CI |
|---|---|---|
| Glucose RMSE 30 / 120 min (gradient boosting) | 10.4 / 25.9 mg/dL | 9.8–11.0 / 23.2–29.1 |
| Persistence RMSE 30 min | 18.7 | 16.4–21.1 |
| AUROC: logistic (served) / gradient boosting / trend rule | 0.884 / 0.936 / 0.655 | 0.839–0.923 / 0.915–0.955 / 0.583–0.736 |
| Onsets with any alert in 2 h (logistic, thr 0.35) | 91% | 0.83–0.98 |
| Onsets with ≥ 30 min lead | 87% | – |
| Onsets with a **sustained** alert | 69% | 0.48–0.83 |
| Median lead: any alert / sustained | 95 / 85 min | – |
| False-alert episodes per monitored patient-day | 1.36 | 0.92–1.92 |
| Other seeds (1, 2, 3): logistic AUROC; sustained warnings | 0.883–0.910; 72–78% | – |
| Stress realism: AUROC; sustained; RMSE 30 min | 0.904; 70%; 15.4 | – |

All values describe the synthetic simulator only. They are not clinical validation.
