# GlucoTwin competition video: script and shot list

**Status: NOT RECORDED. No video file and no link exist.** This is a plan only. Do not reference a video anywhere until a file exists and its link has been opened while logged out.

**Length: unresolved.** The challenge page says both "Minimum 20-minute video" and "15–20 minute" ([COMPETITION_COMPLIANCE.md](COMPETITION_COMPLIANCE.md)). Confirm with the organisers, then record one of these:

| Cut | Modules | Planned length | Use if the organisers confirm |
|---|---|---|---|
| **A: core** | 1–12 | **18:30** | "15–20 minutes" |
| **B: extended** | 1–12 plus X1–X3 | **23:00** (stays over 20:00 even after trimming) | "minimum 20 minutes" |
| **C: 20-minute (recommended)** | 1–12 with modules 5 and 6 extended (5+, 6+) and module F added | **20:20** (target window 20:15–20:30) | either reading: just over 20 minutes |

Every on-screen value below comes from the **recorded static snapshot** (`frontend/static-demo/demo/*.json`). It was first recorded on 2026-10-21 and re-recorded on 2026-10-23 from a clean commit; `manifest.json` names the model and commit. Every frame, forecast and What-If in the re-recording is identical to the 2026-10-21 values used here. Only additive fields were added: the confidence line, the FHIR RiskAssessment and per-scenario lower bounds. Times are patient-local (UTC+05:30). All patients are synthetic.

This file supersedes the scene timings in [DEMO_SCRIPT.md](DEMO_SCRIPT.md) and [RECORDING_CHECKLIST.md](RECORDING_CHECKLIST.md). Those files contain values from earlier builds and one outdated claim (SYN-0019 "missed").

---

## 1. Recording setup

**Recommended source: the static snapshot, served locally.** It needs no training run, gives identical numbers on every take, and its banner tells viewers that the responses were recorded from the real API.

```bash
cd frontend && npm ci && npm run build:static && npm run preview:static   # http://localhost:4173/
```

- Deep links: `?patient=SYN-0039&start=151.833` (hero, starts 07:55) and `?patient=SYN-0019&start=253.667` (weakness, starts 13:45).
- In the snapshot, What-If amounts exist at **07:55 and 08:55** (SYN-0039) and **13:45** (SYN-0019) for **18, 22, 25, 28, 30, 32, 35, 36, 40, 44, 45, 48, 50, 52, 58, 60, 64, 65, 68, 78, 90, 92, 120, 200 and 300 g**. The 20 preset amounts are also recorded every 15 min of each replay. Any other amount shows an explicit "no recorded what-if" message. Use only the amounts in this script.
- Browser window **1440 px** wide, zoom 100%, bookmarks bar hidden, notifications off. Record at 1080p.
- Open these in tabs:
  - the dashboard (hero deep link);
  - [README.md](../README.md), rendered locally or on GitHub once it has been pushed;
  - [rmse_by_horizon.svg](../reports/real_data/shanghai_t2dm/public/rmse_by_horizon.svg);
  - the architecture PDF and the presentation PDF.
- The deck was regenerated on 2026-10-23 from `docs/submission/src/presentation.template.html` (`scripts/build_presentation.py`, then `scripts/export_submission_pdfs.mjs`). It now has **15 slides**. New slide 9, *Twin validity against simulator ground truth*, covers personalisation recovery, the post-meal improvement, the confidence line, the served What-If negative result, the train-fitted personalised curve, the FHIR RiskAssessment and the low-glucose watch; every number is filled from the research reports. Later slides moved up by one: dashboard 10, demo moments 11 (SYN-0019 warned late at 14:50, 45 min before 180), safety 12, impact 13, engineering 14 (151 Python tests, 34 frontend tests), thank you 15. Do not show an older copy of the PDF.
- **Update 2026-10-24: the deck has 16 slides.** New **slide 11**, *Twin-curve What-If, Indian meals, AGP and a fact-grounded handover*, sits after the dashboard (10). Later slides moved down by one: demo moments 12, safety 13, impact 14, engineering 15 (test counts filled automatically), thank you 16. The dashboard now also has the **Automated Gentle Meal-Swap Finder** inside the What-If lab and the **Atithi (patient) companion summary** below the clinician handover note (module 6++).
- If any on-screen value differs from this script, **stop**. Never narrate a number you cannot see.

**Alternative: the live app** (`make setup && make train && make serve`). `make train` rewrites `reports/evaluation_report.json` with only `generated_at` and `model_version` changing. Afterwards, run `git diff --stat reports/` and restore with `git checkout -- reports/` before any commit. Live values should match this script, but re-verify them before recording.

## 2. Must-say lines (all cuts)

1. "GlucoTwin is a research prototype. It is not a medical device and has not been clinically validated."
2. "Every patient in the dashboard is synthetic."
3. "The What-If results are learned associations of the model, not physiology and not advice."
4. "Our real-data results are for simpler glucose-history models. The full GlucoTwin model has not been tested on real patients."
5. (Cut C) "The low-glucose watch is the edge of a prediction interval, not a probability, and our research numbers come from the simulator."

## 3. Shot list

Clock times are for **Cut A**. In Cut B, insert X1 after module 3, X2 after X1, and X3 after module 10; every later module shifts accordingly.

**Cut C clock (20:20):**

| # | Module | Clock | Duration |
|---|---|---|---|
| 1 | Cold open | 0:00–0:45 | 0:45 |
| 2 | Problem and product | 0:45–2:15 | 1:30 |
| 3 | Why a twin | 2:15–4:00 | 1:45 |
| 4 | The live state at 07:55 | 4:00–6:00 | 2:00 |
| 5+ | Patient-specific update, plus confidence and post-meal evidence | 6:00–8:30 | 2:30 |
| 6+ | What-If, plus the Low watch column and research check | 8:30–11:40 | 3:10 |
| F | FHIR R4 record | 11:40–12:20 | 0:40 |
| 7 | Early warning | 12:20–14:20 | 2:00 |
| 8 | Unlogged meal | 14:20–15:35 | 1:15 |
| 9 | Synthetic benchmark | 15:35–17:05 | 1:30 |
| 10 | Real data | 17:05–18:35 | 1:30 |
| 11 | Limitations | 18:35–19:50 | 1:15 |
| 12 | Close | 19:50–20:20 | 0:30 |

If a take runs short, pause longer on the evidence card in module 4 rather than adding claims. Stop the recording between 20:15 and 20:30.

| # | Cut A clock | Dur. | Screen | Action | On-screen caption |
|---|---|---|---|---|---|
| 1 | 0:00–0:45 | 0:45 | Deck slide 1 | Static | "team mono · Amrita Vishwa Vidyapeetham, Chennai" · "Research prototype · synthetic patients · not a medical device" |
| 2 | 0:45–2:15 | 1:30 | Deck slide 2 | Static | "Post-meal excursions are usually seen after the fact" |
| 3 | 2:15–4:00 | 1:45 | Deck slide 3, then the architecture PDF (state lane only) | Point to the twin-state lane | "A twin = a patient state that updates with every reading" |
| X1 | (B only) | 1:30 | Architecture PDF, all six lanes | Walk the lanes; point out dashed boxes as *not built* | "As implemented" |
| X2 | (B only) | 1:30 | Deck slide 5 | Static | "Synthetic by necessity: hidden physiology vs observable record" |
| 4 | 4:00–6:00 | 2:00 | Dashboard, hero deep link (07:55) | Hover the forecast band; open the evidence card | "Observed · predicted · uncertainty · evidence" |
| 5 | 6:00–8:00 | 2:00 | Personalised-parameter panel → SYN-0019 in the sidebar → back | Expand "How this parameter updates" | "Learned per patient: 1.31 → 1.70 (SYN-0039) vs 1.25 → 1.11 (SYN-0019)" |
| 6 | 8:00–10:30 | 2:30 | What-If strip at 07:55 | Preset *Idli with sambar* → Simulate; add 120 g; add 300 g; add 25 g | "SIMULATED · compared with a zero-carb meal at the same moment" |
| 7 | 10:30–12:30 | 2:00 | Press **+1 h** → 08:55, then step **+5 min** to 10:20 and play to 10:55 | Show the alert; the earlier predictions; the parameter update at 10:55 | "Alert 85 min before glucose exceeds 180 mg/dL" |
| 8 | 12:30–13:45 | 1:15 | SYN-0019 deep link (13:45) | **+1 h**, then **+5 min** steps to 15:35 | "Weakness: no meal logged" |
| 9 | 13:45–15:15 | 1:30 | Dashboard *Model evaluation* tab, then README "Results at a glance" §1 | Scroll slowly | "Synthetic benchmark · 12 held-out synthetic patients" |
| 10 | 15:15–16:45 | 1:30 | README "Results at a glance" §2 + `rmse_by_horizon.svg` | Show the table, the chart and the attribution line | "Real data (ShanghaiT2DM) · glucose-history models · NOT the GlucoTwin model" |
| X3 | (B only) | 1:30 | Terminal | `make check`; show 140 passed, 23/23 frontend | "Reproducible: one seed, `make check`" |
| 11 | 16:45–18:00 | 1:15 | README "Limitations and intended use" | Scroll | "Not clinically validated · next: real data with carbs and activity" |
| 12 | 18:00–18:30 | 0:30 | Deck slide 16 (thank you) | Static | Repo link · "Synthetic patients · not a medical device" |

## 4. Narration and expected screen values

Narration runs at about 130 words a minute, leaving pauses for clicks. **Bold** values must be visible on screen when you say them.

### Module 1 — Cold open (0:45)

> "Hi, we're team mono from Amrita Vishwa Vidyapeetham, Chennai. This is GlucoTwin: a living digital twin for a person with type 2 diabetes. It forecasts glucose two hours ahead, warns before an excursion, and lets a clinician ask 'what if they eat this now?'. Before anything else: this is a research prototype, not a medical device and not clinically validated, and every patient you'll see is synthetic."

### Module 2 — Problem and product (1:30)

> "People with type 2 diabetes often see a post-meal spike only after it has happened, on a CGM report. A clinician reviewing that data has three questions. Where is this person heading in the next two hours? How much should I trust that? And what would a different meal change? GlucoTwin answers all three on one screen. It fuses the health record (HbA1c, medication, kidney function) with CGM, logged meals, steps and heart rate. Every answer carries its uncertainty and the evidence behind it."

### Module 3 — Why a twin (1:45)

> "A normal predictor takes a window of data and returns a number. GlucoTwin keeps a patient state that changes with every reading: last glucose and trend, carbs on board, activity, data quality, and one learned personal parameter, carb sensitivity. The twin only ever sees data up to 'now'; a test checks that replay never reveals the future. Hypothetical meals run on a copy of the history and are never written into the patient's record."

### X1 — Architecture (Cut B, 1:30)

> Walk the six lanes of the architecture PDF: inputs, stream, twin state, prediction, clinician dashboard and offline evaluation. "The dashed boxes are not built; we only show what exists."

### X2 — Synthetic data design (Cut B, 1:30)

> "Why synthetic? The challenge allows open or synthetic data, and the real CGM datasets with logged carbs and activity that we checked either need a data-use agreement or restrict reuse. Our generator has hidden physiology the models never see. They only see an observable record and noisy streams, with dropouts and some unlogged meals. That makes the task realistic, but simulator performance is still not real-world performance."

### Module 4 — The live state at 07:55 (2:00)

Screen (07:55): Farah N. (synthetic) **SYN-0039**, 32 y, HbA1c **6.1%**. Glucose **94 mg/dL**, stable. Risk **22%**, MODERATE, so **no alert** (threshold 35%). Forecast **+30: 93 [81–105]**, **+60: 119 [101–138]**, +120: 171 [141–201]. Evidence card: CGM **0 min ago**, 3-hour completeness **97%**, gaps over 30 min **0**, **5373** observations ingested.

> "This is Farah, a synthetic patient, at 7:55 in the morning. Glucose is 94 and steady. The blue dashed line is the twin's forecast and the band is its 80% interval: 119 at plus 60 minutes, somewhere between 101 and 138. The excursion risk, the chance that three consecutive readings above 180 start within two hours, is 22%. That is below our alert threshold, so no alert. The bars show what drives that estimate. They are grouped logistic-regression terms; associations, not causes. Underneath, the evidence: the last reading is 0 minutes old, 97% of the last three hours is present, and there are no gaps. If CGM goes stale, the twin says so rather than guessing."

### Module 5 — Patient-specific update (2:00)

Screen: personalised-parameter panel shows **1.70 mg/dL per g**, prior **1.31**, **20** observed meals. Then click **Anil S. (synthetic)** in the sidebar (deep link SYN-0019): parameter **1.11**, prior **1.25**, **33** meals. Then return to the hero deep link.

> "This is what makes it a twin rather than a generic model. Farah's carb sensitivity, how much her glucose rises per gram of carbohydrate, started at 1.31 from her HbA1c. After 20 of her own meals it is 1.70: her responses are steeper than her record suggested. Anil, a different synthetic patient, started at 1.25 and has come down to 1.11 over 33 meals. The rule is simple and visible: each eligible meal contributes its observed rise per gram, shrunk towards the record-based prior with the weight of three pseudo-meals. In our simulator it measurably helps forecasts, which I'll show in a moment; we have not tested that on real patients. It makes the twin's state patient-specific, and you'll see it update live in a minute."

**5+ (Cut C, +0:30).** Screen: the confidence line under the parameter reads **"Confidence: 87% from 20 observed meals; ± 0.16 sampling error (meal-to-meal SD 0.81)"**. Then show deck slide 9 (or the README section *How personalisation works*, bullet "It matters most after meals"): **+2.44 mg/dL**, CI **0.73–3.86**.

> "How much should you trust that 1.70? The twin tells you: 87% of it comes from Farah's own 20 meals, with a sampling error of about plus or minus 0.16. That's a spread, not a probability. And does personalisation help? In the simulator, in the hour after a logged meal, switching it off raises the 60-minute forecast error by 2.44 mg/dL, with a 95% interval of 0.73 to 3.86. That analysis was added after our first results, and it's simulator evidence only."

### Module 6 — Supported What-If (2:30)

Screen (still 07:55): choose preset **Idli with sambar** (2 idli + 1 small bowl sambar, **≈ 35 g**) and press **Simulate meal**. Row: Δ **+7.9 / +29.9 / +10.7** mg/dL at +30/+60/+120; risk **7% → 52%**; grey "vs no meal" column **22% → 52%**. Add **120 g**: **+20.1 / +76.1 / +58.4**, **7% → >99%**. Add **300 g**: tag **outside training support**, with the reason on hover. Optional: add **25 g**, which is greyed as unreliable under 30 g (**7% → 34%**).

> "Now the clinician's question: what if she eats two idli with sambar right now? About 35 grams; the preset values are approximate and editable. The comparison is against eating a zero-carb meal at the same moment, which isolates the carbohydrate. Predicted risk goes from 7 to 52%, and the forecast at plus 60 is about 30 mg/dL higher. A heavier 120-gram meal takes the risk above 99%. Now 300 grams. Look at the tag: 'outside training support'. No training meal was comparable, and the twin tells you so instead of silently extrapolating. That tag is a diagnostic, not a guarantee; being inside the training range doesn't make a forecast right either. And these differences are what the model has learned in simulation, not physiology and not dietary advice."

Optional comparison for Cut B (SYN-0019 at 13:45, same preset): **7% → 20%**, Δ+60 **+25.4**. "Same meal, different twin, different predicted response."

**6+ (Cut C, +0:40).** Screen: scroll the What-If table right to the **Low watch** column (every recorded row shows **–**; hover one for the tooltip). Then read the grey *Research check* note under the table: served What-If **37.3**, cohort average **16.8**, personalised curve **5.9** mg/dL MAE at +120 min.

> "The last column is a low-glucose watch for each scenario. Adding carbs lifts the forecast, so it stays clear here; you'll see the watch fire on the risk card for a patient on a sulfonylurea and insulin. Now honesty about the What-If. We replayed every scenario against the simulator's true response. At two hours the served What-If is off by 37 mg/dL on average, worse than a simple cohort-average curve at 17. But a curve built from this patient's learned sensitivity, fitted on training patients and tested once, gets about 6. So the learned parameter carries the right information; our forecasting model doesn't yet use it well. That curve now sits beside the table as a purple research column; the served numbers are unchanged."

**6++ (Cut C, +1:30). Twin curve, walk, swap finder, AGP and the two grounded notes.** Show deck **slide 11** for a few seconds first, then return to the dashboard (still 07:55, idli row in the table).
- Purple columns on the idli row: twin curve **+42.5 / +60.0** at +60/+120 min. Tick **compare with a post-meal walk (+20 min, 2,500 steps)**: **+48.8 (walk −11.2)**.
- Preset **Rajma chawal** (**68 g**) → **Add scenario**. The **Automated Gentle Meal-Swap Finder** runs by itself ("large meal (68 g …); simulated excursion risk 93% …"). Its top 3: **Khaman dhokla 32 g +54.8**, **Idli with sambar 35 g +60.0**, **Rava upma 35 g +60.0**, each with the low watch "not triggered". Read the label: "Deterministic Twin Scenario Search … educational simulation, not a clinical prescription."
- Scroll to the **Glucose profile (AGP)** card (6.3 days, 44.9% coverage, so marked below the 14-day / 70% minimum), the **Clinician handover note** ("Verified: 100% of numbers") and the **Atithi (Patient) Plain-Language Companion Summary** ("Verified: 100% of numbers (20/20)").

> "The purple column is the personalised twin curve. For two idli it predicts about 60 mg/dL at two hours, close to the simulator's true 65 you saw on slide 11. A twenty-minute walk afterwards is a cohort-level effect: on held-out test scenarios its error was 4.3 mg/dL, against 11.6 if you assume a walk does nothing. Now a big plate of rajma chawal. The swap finder searches our Indian presets automatically, keeps only meals inside training support that don't trip the low watch, and ranks them by the twin curve. Honestly, that curve only sees grams, so the order is simply fewer carbs first; the GI badge is context, not part of the ranking. Below, the AGP says this window is too short to be a proper profile. The clinician note and the Atithi summary — Atithi is Happiest Health's word for the people it serves — are fixed templates, and a separate checker traces every number back to the twin; if one doesn't trace, the card isn't shown. They explain; they never prescribe."

Optional, if time allows: SYN-0019 deep link, **+1 h** three times → **16:45**: the risk card shows "Low-glucose watch: the 80% forecast lower bound falls below 70 mg/dL from **+120 min** (lowest **69 mg/dL**)", listing **Glimepiride (sulfonylurea)** and **Insulin glargine (basal insulin)**. Return to the hero deep link before module F.

### Module F — FHIR R4 record (Cut C, 0:40)

Screen (SYN-0039): click **FHIR R4 record (interoperability prototype)** under the patient header. It is a collapsible panel, not a pop-up. It shows **82** resources: **1 Patient, 2 Condition, 3 MedicationStatement, 75 Observation, 1 RiskAssessment**. The code table includes LOINC **99504-3** (CGM) and SNOMED **44054006** (type 2 diabetes). The RiskAssessment line reads "Hyperglycaemic excursion … probabilityDecimal **0.215**". Click **Copy JSON**, then point at **Download JSON**.

> "The twin can hand its record to other systems. One click gives a FHIR R4 bundle: the synthetic patient, conditions, medications, labs, CGM, and a RiskAssessment with the excursion probability. A low-glucose watch, when present, goes in as a qualitative flag with no probability attached. India's ABDM health-record guide is built on FHIR R4, but this export is a prototype: it is not profiled against that guide and not certified. The ID is our own synthetic one, never an ABHA number."

### Module 7 — Early warning and the live update (2:00)

Screen:
- Press **+1 h** → **08:55**: the What-If rows clear. A **140 g** breakfast was logged at **08:53** (green triangle). Glucose **89, rising**; risk **>99%**, **HIGH**, "Above the alert threshold (35%)". The top driver is "Recent meals / carbs on board (**138**)". Forecast **+60: 205 [186–223]**.
- Step **+5 min** to **09:25**: observed **103**, against the **128** forecast at 08:55 for +30.
- Continue to **10:20**: glucose **187**, and the card switches to "already above 180".
- Peak **207** at **10:35**. Continue to **10:55**: parameter **1.666** from **21** meals.

> "One hour later, a 140-gram breakfast has just been logged. Glucose is still only 89, but the twin combines that meal with Farah's learned sensitivity and raises an alert: excursion risk above 99%, forecast 205 at plus 60. Let's step forward. An honest detail: at 9:25 she's at 103, lower than the 128 the twin expected, so the rise came later than predicted. At 10:20 glucose crosses 180; the alert had stayed on from 8:55, an 85-minute warning. Now watch the parameter at 10:55, when this breakfast's two-hour window closes. That breakfast rose about 0.91 mg/dL per gram, gentler than her running estimate. So the twin revises her sensitivity from 1.70 to 1.67, now based on 21 meals. The twin learns from what just happened. This is one well-chosen example; across all test onsets, a sustained warning came for about 69%."

### Module 8 — Weakness: an unlogged meal (1:15)

Screen (SYN-0019 deep link, 13:45): glucose **88**, risk **12%**.
- **+1 h** → **14:45**: glucose **88**, risk **31%** (just below 35%, no alert). Last meal **389 min** ago; nothing logged.
- **+5 min** → **14:50**: glucose **93**, rising fast; risk **36%**, alert.
- Step to **15:35**: glucose **185**, the first reading above 180. Peak **191** at **16:00**.

> "Now a weakness. Anil has nothing logged since the morning. At 2:45 the risk is 31%, just under the threshold. At 2:50 glucose is rising fast and the alert fires, 45 minutes before he crosses 180. By our definition that counts as a warning, but notice that it only came once the rise had begun. Without a meal log the twin has nothing to anticipate with. Meal logging is the single most important input."

### Module 9 — Results 1: the synthetic benchmark (1:30)

Screen: *Model evaluation* tab, then README "Results at a glance" §1.

> "First, results on our synthetic benchmark: 12 held-out synthetic patients over 14 days, never seen in training, scored once. Forecast error, RMSE, is 10.4 mg/dL at 30 minutes against 18.7 for simply carrying the last reading forward, and 25.9 against 46.6 at two hours, about 44 to 45% lower. For excursion warnings, AUROC is 0.884 against 0.655 for a trend rule. Of 298 test onsets, 272 had an alert in the preceding two hours, with 229 false-alert episodes over 168 patient-days. The trend rule alerted on all 298, but with 1,055 false-alert episodes. These describe our simulator, not real patients."

### Module 10 — Results 2: real data, kept separate (1:30)

Screen: README "Results at a glance" §2, then `rmse_by_horizon.svg`. Keep the attribution line (ShanghaiT2DM v5, Zhao, Zhu, Wang and Rao, CC BY 4.0) visible for at least 3 seconds.

> "Second, and separate: real data. We used ShanghaiT2DM, a public dataset of 100 people with type 2 diabetes. Note what was evaluated: simple models trained on glucose history alone, not the full GlucoTwin. We split by patient before building any windows and scored once, on 20 held-out people. At 30 minutes, gradient boosting reaches an RMSE of 12.3 against 16.1 for persistence. At two hours it is 33.6 against 40.8, better for 15 of the 20 patients. The full twin was not run, because this dataset records food as text, not carbohydrate grams, and has no steps or heart rate: ten of its 33 inputs would have to be invented. These numbers can't be compared with the synthetic ones. Data credit: Zhao, Zhu, Wang and Rao, CC BY 4.0."

### X3 — Reproducibility (Cut B, 1:30)

Screen: terminal, `make check`. Show Ruff passing, **151 passed** and **34/34** frontend tests (counts from 2026-10-23). Re-verify the counts on the day; never read out a number that is not on screen.

> "Everything is reproducible from one seed. `make check` runs linting, 151 Python tests (including leakage and replay-never-reveals-the-future tests), the TypeScript build and 34 frontend tests."

### Module 11 — Limitations and next steps (1:15)

> "To be clear about limits: GlucoTwin is not clinically validated and gives no diagnoses or treatment advice. The dashboard and the headline metrics are synthetic. The real-data results are for glucose-history models only, from one region and one sensor. The full twin has not been evaluated on real patients. What-If results are model associations. Next steps: evaluate the full twin on a governed real dataset that records carbohydrates and activity; test whether the simulator gains from personalisation hold on real people; rebuild the What-If around the personalised response curve and pre-register that test; and only then think about prospective validation."

### Module 12 — Close (0:30)

> "That's GlucoTwin: a patient state that learns the individual, forecasts with honest uncertainty, and says when it's on thin ice. The code and every number are in the repository. Thank you."

## 5. After recording

- [ ] Check the duration against the cut the organisers confirmed (A: about 18:30; B: at least 20:30 before any trim; C: between 20:15 and 20:30).
- [ ] Upload as **unlisted** (or a recorded PPT, if the organisers allow it), then open the link in a logged-out browser.
- [ ] Only then add the link to README §14 and §18 and to `docs/COMPETITION_COMPLIANCE.md`.
- [ ] Submit the 15-slide PDF regenerated on 2026-10-23 (slide 9 is twin validity).
