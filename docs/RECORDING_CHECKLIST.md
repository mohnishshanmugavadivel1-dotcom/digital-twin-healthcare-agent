# Recording checklist: one continuous take, ≥ 20 minutes (hard requirement)

Companion to [DEMO_SCRIPT.md](DEMO_SCRIPT.md). Every expected value below was re-verified against the
running API and dashboard on **2026-10-20** (fresh deterministic training, model `gt-0.1.0-s…`, 62/62 tests).
Target length **23:00** so editing cannot push the video under 20:00. **No video has been recorded yet.**

## Pre-flight (finish ≥ 10 min before recording)

- [ ] `make serve` is up at `http://localhost:8000` and the model bundle exists (`artifacts/model_bundle.pkl`). If the API logged "training one now", wait for "service ready".
- [ ] Browser window **1440 px wide**, bookmarks bar hidden, notifications off, recorder set to 1080p.
- [ ] Paste both deep links into a scratch file for one-click navigation:
      hero `/?patient=SYN-0039&start=151.833` · failure `/?patient=SYN-0019&start=253.667`
- [ ] Open in adjacent tabs: deck PDF, architecture PDF, `src/glucotwin/synth/generator.py`, a prepared terminal.
- [ ] Timer visible (or count scenes). Microphone level checked. Say the two safety sentences out loud in the first minute.
- [ ] If any on-screen value differs from this sheet: **stop, re-run `make train`, re-verify — never narrate a number you cannot see.**

## Timeline (23:00 total)

| Video clock | Dur. | On screen | Do / say (verified expected values in **bold**) |
|---|---|---|---|
| 0:00–1:30 | 1:30 | Deck slide 1 | Team **team mono**, **Amrita Vishwa Vidyapeetham, Chennai**, sole member. One-liner: "a continuously updated virtual T2D patient that warns a doctor up to 2 h before a post-meal excursion". Safety: research prototype, **synthetic patients only**, not a medical device. |
| 1:30–4:00 | 2:30 | Deck slides 2–3 | Problem (post-meal excursions seen *after* the fact) and why a *twin* (state updated by every reading; record + streams fused; one learned personal parameter) beats a static risk score. |
| 4:00–6:30 | 2:30 | Architecture PDF | Walk the six lanes; point out dashed boxes = **not built**. |
| 6:30–8:30 | 2:00 | Deck slide 5 + `synth/generator.py` | Hidden physiology vs observable record/streams; noise, dropouts, 10% unlogged meals; why synthetic (sandbox rules). Plausibility: TIR **77.8%** vs ShanghaiT2DM **77.7%**. |
| 8:30–13:30 | 5:00 | **HERO** deep link | Beat sheet below. |
| 13:30–15:30 | 2:00 | **FAILURE** deep link | Beat sheet below. |
| 15:30–17:30 | 2:00 | Evaluation tab + deck 7–8 | Patient-level split 36/12/12; test evaluated once; RMSE **10.4/17.2/25.9**; AUROC **0.884 (0.839–0.923)** served logistic vs GB **0.936**; false alerts **1.4/day**; coverage **0.76–0.80**; audit: sustained warnings **69% (0.48–0.83)**, stress test and ablations. |
| 17:30–19:30 | 2:00 | Terminal | `make check` (ruff + **62 tests** + frontend build, ~13 s), then `.venv/bin/glucotwin audit --quick`; mention mutation-based leakage tests and the clean-clone reproduction from the wave-2 audit. |
| 19:30–21:30 | 2:00 | Deck slides 11–12 | Safety boundaries (no instructions, never 100%/0%, local demo ≠ real data), limitations, validation roadmap without overclaiming. |
| 21:30–23:00 | 1:30 | Deck slide 14 | Recap, repo link, thanks. Closing line repeats the synthetic-data disclaimer. |

## HERO beat sheet — `/?patient=SYN-0039&start=151.833` (Sun 8 Mar, IST)

| Step | Clock | Expected on screen (verified 2026-10-20) |
|---|---|---|
| Load | 07:55 | Farah N. (synthetic), record header incl. "**TCF7L2 rs7903146 (synthetic; display-only)**". Glucose **94**, risk **22%** (moderate), **no alert**. |
| Press **+1 h** | 08:55 | Breakfast **140 g logged 08:53** (green triangle). Glucose **89, rising**. Risk **>99% (0.9998), HIGH badge, "Above the alert threshold (35%). Consider reviewing."** Top factor "**Recent meals / carbs on board (138)**". Forecast +60 min ≈ **205 [186–223]**. Twin panel: learned carb sensitivity **1.70 mg/dL per g** (prior 1.31, **20 meals used**). *Say:* glucose is normal, yet the twin already knows. |
| **+5 min** ×6 | 09:25 | CGM follows the forecast up. **Honest beat:** observed **103** vs the 30-min forecast made at 08:55 (**128**) — the rise came later than predicted. |
| Continue to | 10:20 | Glucose **187** → card switches to "**already above 180**" (onset question stops). |
| Then | 10:35 | **Peak 207**. Alert stayed on **08:55 → 10:15**: an **85-min sustained warning**. |
| **What-if** (at the **07:55 load point, before stepping**) | 07:55 | In the orange strip: set **120 g**, press **Simulate meal** → dashed orange curve over the solid blue forecast, **SIMULATED** tag. Verified readout: **+60-min glucose 119 → 197 (Δ ≈ +78), risk 22% → 99.9%**. *Say:* "a what-if fork: the hypothetical meal is **never added to the record** — state, version and history are untouched (there are tests asserting that). A simulated scenario, not medical advice." (The strip needs glucose ≤ 180; at 07:55 glucose is **94**.) NOTE: do the fork **here**, not at 08:55 — after the real 140 g breakfast an extra hypothetical meal moves ≈ 0 (138 g already on board, risk saturated). |
| Say | — | "One well-chosen example: the audit shows only **69%** of onsets get a sustained warning (95% CI **0.48–0.83**)." |

## FAILURE beat sheet — `/?patient=SYN-0019&start=253.667` (Thu 12 Mar, IST)

| Step | Clock | Expected on screen (verified 2026-10-20) |
|---|---|---|
| Load | 13:45 | Glucose **88**, risk **12%**, no alert. |
| Press **+1 h** | 14:45 | Glucose **88**, risk **31%** — just **below** the 35% threshold, **no alert**. **No meal logged**; twin panel: last meal **389 min ago**, carbs on board **0**. Forecast bends up but stays under 180: a weak signal without the meal. |
| Press **+1 h** | 15:45 | Glucose **184** — the excursion began at **15:45** (a single 185 at 15:35 falls back to 179 at 15:40, which *breaks the run* under the frozen ≥3-consecutive-readings definition — expect the risk card to flicker back on for one reading around 15:40; that is the definition working, say so if visible). **Peak 191 at 16:00.** |
| Say | — | "The twin missed it. The patient almost certainly ate without logging. Meal logs are the single most important input (ablation AUROC 0.884 → 0.849 without them), and the stress test cuts ≥30-min-lead warnings from **87% to 78%**." |

## After recording

- [ ] Check duration **≥ 20:30** (raw take; before any trim).
- [ ] Upload **unlisted** YouTube (or keep as recorded PPT video); confirm the link plays in a logged-out browser.
- [ ] Add the link to the README "Submission artefacts" table (replacing "_link to be added after recording_").
- [ ] Update `docs/COMPETITION_COMPLIANCE.md` video row and `docs/DEMO_SCRIPT.md` line 5.
- [ ] Re-check the repo is public and every link in the README opens logged-out.
- [ ] If you ran `glucotwin audit --quick` on camera: afterwards run `git checkout -- reports/audit_report.json` — `--quick` writes a reduced report (no multi-seed section) that must not replace the committed full-audit artifact.
