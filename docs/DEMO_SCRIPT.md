# Demo script: minimum 20-minute video (official requirement)

The official guideline is a "**Minimum 20-minute video** explaining and demonstrating your prototype", either a recorded PowerPoint or an
unlisted YouTube video ([COMPETITION_COMPLIANCE.md](COMPETITION_COMPLIANCE.md)). This script is planned for **22–24 minutes** so that
editing cannot push it under 20. **No video has been recorded yet.**

## Setup (before recording)

```bash
make setup && make train      # deterministic; model and metrics identical on every run
make serve                    # http://localhost:8000
```
Use a 1440 px-wide browser window. Every scene below starts from a **deep link**, so it is reproducible without counting clicks.
The deep link `?patient=<id>&start=<hours>` starts the replay `<hours>` after the start of that patient's record. Only held-out test patients
can be replayed. All times shown are patient-local (UTC+05:30).

## Scenes

| # | Time | Screen | What to say (key points) |
|---|---|---|---|
| 1 | 0:00–1:30 | Title slide | Team, college, one sentence: "a continuously updated virtual T2D patient that warns a doctor up to 2 h before a post-meal glucose excursion". Say clearly: research prototype, synthetic patients only, not a medical device. |
| 2 | 1:30–4:00 | Slides 2–3 | Problem and use case. Why a *twin* (per-patient state updated by every reading, record + streams fused, personal parameter learned) rather than one static risk score. |
| 3 | 4:00–6:30 | Architecture PDF | Walk the six lanes: inputs, stream, twin state, prediction, clinician, offline evaluation. Point out the dashed boxes: they are **not built**. |
| 4 | 6:30–8:30 | Slide 5 + `src/glucotwin/synth/generator.py` | Synthetic data design: hidden physiology versus the observable record and streams; noise, dropouts, unlogged meals. Why synthetic (sandbox rules; restricted real datasets). |
| 5 | 8:30–13:30 | **Hero scene** (below) | The twin warns 85 min ahead while glucose is still 89 mg/dL. |
| 6 | 13:30–15:30 | **Failure scene** (below) | An excursion the twin misses because the meal was never logged. |
| 7 | 15:30–19:00 | Evaluation tab + slides 7–8 | Target definition, patient-level split, baselines; then the stricter audit: sustained warnings, CIs, ablations, stress test. |
| 8 | 19:00–21:00 | Terminal: `make check`, `glucotwin audit --quick` | Tests (leakage, replay never leaks the future), reproducibility, CI. |
| 9 | 21:00–23:00 | Slides 11–12 | Safety boundaries, limitations, a validation roadmap that makes no claims beyond what we tested; close. |

### Scene 5: hero (verified 2026-10-17 against the live API and dashboard)

Deep link: **`/?patient=SYN-0039&start=151.833`**. The replay starts at Sun 8 Mar, 07:55.

1. **Expected at load (07:55):** Farah N. (synthetic), 32 y F, HbA1c 6.1%, on metformin, glimepiride and ramipril. Glucose is **94 mg/dL** and risk is about **22%**, below the 35% alert threshold, so no alert.
   Point out the record header, including "family history / TCF7L2 (synthetic, context only; not a model input)".
2. Press **+1 h**. **Expected at 08:55:** a 140 g breakfast was logged 2 minutes ago (green triangle) and current glucose is **89 mg/dL, rising**.
   Risk is **>99%, HIGH, "Above the alert threshold (35%). Consider reviewing."** The top factor group is "Recent meals / carbs on board (138)".
   The forecast band climbs past 180, to about 205 mg/dL [186–223] at +60 min.
   *Say:* glucose is still normal, yet the twin combines the logged meal with this patient's learned carb sensitivity (1.70 mg/dL per g,
   learned from 20 observed meals, prior 1.31 from the record).
3. Press **+5 min** a few times (or Play at 15 min/tick). **Expected:** the CGM line follows the forecast upward, and the earlier-predictions dots
   appear. Be honest: at 09:25 the observed value (103) was *below* the 30-min forecast made at 08:55 (128), so the rise came later than predicted.
4. Continue to **10:20**. **Expected:** glucose is 187, above 180. The risk card switches to "already above 180", because the onset question is only asked at ≤ 180.
   The alert stayed on from 08:55 until onset: an **85-min sustained warning**. The peak was about 207 mg/dL.
5. *Say:* this is one well-chosen example. The audit shows that only about 69% of onsets get a sustained warning (95% CI 0.48–0.83).
6. **What-if meal (U1, added 2026-10-20).** Restart to 07:55, press **+1 h** back to 08:55. In the orange strip enter **80 g** and press
   **Simulate meal**: a dashed orange scenario curve overlays the solid forecast, with a **SIMULATED** tag and a Δ readout (risk and +60-min glucose).
   The fork runs on a copy of the history — the hypothetical meal is **never ingested** (state, version, streams and forecast history are
   unchanged; `tests/test_counterfactual.py` asserts it), the endpoint is test-split-only, and the response carries a
   "not medical advice" disclaimer. Say those boundaries out loud.

### Scene 6: honest failure (verified)

Deep link: **`/?patient=SYN-0019&start=253.667`**. The replay starts at Thu 12 Mar, 13:45.

1. **Expected at load (13:45):** glucose 88 mg/dL, risk about 12%.
2. Press **+1 h**. **Expected at 14:45:** glucose 88 mg/dL, risk about **31%**, just *below* the 35% threshold, so no alert. No meal is logged that afternoon. The last logged meal was 389 min ago. Note that the glucose *forecast* already bends upward (about 160 at +2 h) but stays under 180: a weak signal without the meal.
3. Press **+1 h**. **Expected at about 15:45:** glucose has risen past 180 (onset 15:45; peak about 191 by 16:10).
4. *Say:* the twin missed it. The patient almost certainly ate without logging, and the ablation shows meal logs are the single most
   important input. In the stress test with fewer, later meal logs, warnings with ≥ 30 min lead fell from 87% to 78%.

### Other reproducible moments

`.venv/bin/python scripts/find_demo_scenario.py --top 10` lists 34 candidate moments and 53 missed daytime onsets on test patients, with deep links.

## Must-say safety lines (in the video and on the slides)

* "All patients are synthetic. Performance describes our simulator, not real people."
* "This is decision support for review, not a diagnosis or treatment instruction."
* "Explanations are associations, not causes."
