# Static recorded-snapshot demo

A backend-free build of the real dashboard that replays answers **recorded from the real GlucoTwin API**.
It exists so that reviewers can click through the demo without installing Python. It is **not** a live system:
nothing is computed in the browser, and every page shows a banner saying so.

## What it contains

| Scenario | Patient (synthetic, held-out test split) | Window (patient-local time) | What it shows |
|---|---|---|---|
| `early-warning` | SYN-0039, replay start offset 151.833 h | Sun 8 Mar 07:55 → 13:55 | Risk 22% at 07:55. A 140 g breakfast is logged at 08:53, and the alert fires at 08:55, 85 min before glucose first exceeds 180 mg/dL (10:20). What-ifs recorded at 07:55 and 08:55. |
| `unlogged-meal` | SYN-0019, offset 253.667 h | Thu 12 Mar 13:45 → 19:45 | A **weakness**: glucose rises with no logged meal. The alert fires only once the rise has begun (14:50, glucose 93 mg/dL, up from 70 at 14:35), 45 min before the first reading above 180 (15:35). Stepping in 1-hour jumps skips the alert (14:45: risk 31%). What-ifs at 13:45. |

* Each scenario covers 6 h in 73 frames, one every 5 min. These are the replay states the API returned when stepped 5 min at a time.
* The observation stream and the forecast history come from the same API.
* What-if results (`POST /api/patients/{id}/counterfactual`) were recorded for 25, 30, 35, 36, 40, 45, 50, 60, 90, 120, 200 and 300 g at the moments listed above. This list covers every Indian meal preset; a front-end test enforces that.
* Any other amount or moment returns an explicit "not recorded; run locally" message instead of an invented number.
* `manifest.json` records:
  * the model version;
  * the git commit;
  * whether the working tree had uncommitted changes at recording time;
  * the SHA-256 of `reports/research/b23_joint_support.json`;
  * the `/api/health`, `/api/model` and `/api/evaluation` responses.

## Faithfulness checks (run by the export script; it writes nothing if any check fails)

* **Observations and forecast history:**
  * The static client keeps items with timestamp > `since` and ≤ the replay clock, then the last 5000 (`frontend/src/api/staticReplay.ts`).
  * At frames 0, 7, 36 and 72 this filtering is compared with the live endpoints, called with the frontend's own `since` (clock − 13 h). The results must be equal.
* **Stepping:**
  * Stepping in 60-min steps must reproduce every 12th 5-min frame.
  * Ignored in that comparison: `session_id`, `forecast_id` and `state.version`. The last is an update counter that depends on step size; this is recorded in `checks.step_comparison_ignores`.
* **Replay end:** the last frame must report `finished: true`.

## Commands

```bash
make setup && make train                      # or reuse an existing artifacts/model_bundle.pkl
.venv/bin/python scripts/export_static_demo.py   # re-record: frontend/static-demo/demo/ (~25 s, ~830 KB)
cd frontend
npm test                                      # includes checks on the recorded snapshot
npm run build:static                          # -> frontend/dist-static/ (relative paths; any sub-path works)
npm run preview:static                        # http://localhost:4173/
```

Browser smoke test (optional QA tool; it needs `puppeteer-core` and a Chromium binary, neither of which is a project dependency): see the header of `docs/qa/browser_smoke.mjs`.

## Publishing (manual; not done)

`.github/workflows/pages-demo.yml` builds the **committed** snapshot and deploys it to GitHub Pages. It runs only from
the Actions tab (`workflow_dispatch`). It needs one repository setting first: *Settings → Pages → Source: GitHub Actions*.

No public URL exists until a maintainer does that and opens the published page.

Status checked on 2026-10-22:
- GitHub lists only the `ci` workflow, because `pages-demo.yml` and the static-demo code are not committed yet.
- The Pages API returns 404 (Pages is not enabled).

To publish, a maintainer must:
1. merge the workflow and the static-demo files into `main` (manual-trigger workflows are offered only from the default branch);
2. set *Settings → Pages → Source: GitHub Actions*;
3. run "Static demo (GitHub Pages)" from the Actions tab;
4. open the URL it prints, which for a project site is normally `https://<owner>.github.io/<repo>/`, and check it before linking it anywhere.

A local rehearsal of the same build, served under `/digital-twin-healthcare-agent/`, passed `docs/qa/browser_smoke.mjs` 14/14 on 2026-10-22.

If the snapshot is re-recorded after committing, the manifest will show a clean commit hash. The current snapshot was recorded on top of commit 581b4f7 with uncommitted changes, and the banner says so.

## Limits

* Synthetic patients only. A research prototype, not a medical device, and forecasts are not diagnoses or treatment instructions.
* Two scenarios. The live app (`make serve`) has 12 held-out patients and can start at any offset.
* The model version string contains the training timestamp. Retraining changes the string, though not the predictions, which are deterministic for the committed seed; re-record after retraining.
