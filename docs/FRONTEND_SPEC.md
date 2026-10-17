# Doctor dashboard specification (Agent E)

Screenshots from the running build: [`screenshots/dashboard.png`](screenshots/dashboard.png),
[`screenshots/evaluation.png`](screenshots/evaluation.png).

## Primary doctor workflow

1. **Triage.** Open the dashboard and scan the patient list. Each row shows the latest glucose (coloured by range) and the latest
   2-hour excursion risk (coloured relative to the served alert threshold).
2. **Understand the patient.** Select a patient. The header shows the record summary: age, sex, BMI, diabetes duration, HbA1c, FPG,
   eGFR, medications and conditions.
3. **See now and next.** The glucose chart shows the last 12 hours plus a 2-hour forecast with its 80% interval, the target band and
   logged meals. Next to it, the risk card gives the probability, band, alert state and the five strongest factor groups.
4. **Check trust.** "Earlier 60-minute predictions" overlays what the twin predicted an hour ago against what happened. The risk
   history shows how the estimate evolved. Data-quality and staleness flags explain withheld forecasts.
5. **Replay.** Play, step or restart the chronological stream. The twin only ever sees data up to "now".
6. **Audit the model.** The evaluation tab shows the target definition, split protocol, every baseline and model on held-out
   patients, and the limitations.

## Information architecture and component boundaries

| Component | Responsibility | Data source |
|---|---|---|
| `App` | Tabs, persistent synthetic-data banner, patient list, threshold from model card | `/api/health`, `/api/patients`, `/api/model` |
| `PatientView` | Replay session lifecycle, polling loop (one in-flight request at a time), layout | `/api/replay*`, observations, forecasts |
| `GlucoseChart` | CGM line (gaps over 10 min broken, never interpolated), forecast + interval, meals, past predictions, now line | props |
| `RiskPanel` | Probability, band, alert text, factor groups, event definition; explicit states for "withheld" and "already above 180" | `Forecast` |
| `RiskTimeline` | Probability over time with threshold, aligned to the chart's time axis | `ForecastSummary[]` |
| `StatePanel` | Current glucose and trend arrow, 24 h TIR/TAR/TBR bar, meals and activity, personalised parameter, data quality | `TwinState` |
| `EvaluationView` | Metric tables (served model highlighted), dataset card, notes | `/api/evaluation` |

## Visual system

* Neutral surfaces. Colour is reserved for meaning: green means in range or lowers risk, amber means above 180 or moderate risk, red means below 70 or high risk.
  The 70–180 band is shaded on the chart, and the 70 and 180 lines are dashed and labelled.
* Numbers use tabular figures. Units are always shown. Times are shown in patient-local time with the UTC offset displayed.
* The disclaimer banner is always visible, and every name carries "(synthetic)".
* Accessibility: native buttons and selects with focus rings, `aria-label` on charts and controls, trend arrows with text equivalents,
  and a responsive single-column layout below 1000 px.

## Wording rules (safety)

* Never phrase output as an instruction ("give insulin", "eat"). Use: "Above the alert threshold. Consider reviewing."
* Explanations are labelled as associations, not causes.
* When data are insufficient, say so, and show no number.

## Minimum viable UI (done) versus next

Done: everything above. Next (backlog): a what-if panel (B-10), clinician notes or acknowledgements, keyboard shortcuts for replay,
a print or export view for the jury, and code-splitting Recharts (bundle is 633 kB minified, 186 kB gzip).
