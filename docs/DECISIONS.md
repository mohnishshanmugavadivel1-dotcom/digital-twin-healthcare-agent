# Architecture decision records

**ADR-001 Synthetic-first data (2026-10-17).** There is no open, patient-linked, 5-minute CGM + EHR dataset obtainable before the deadline
(see DATASET_FEASIBILITY.md), and other teams report the rules require synthetic or open data. We build on a deterministic simulator, keep
hidden physiology separate from the observable record, and plan an optional open-data plausibility check.

**ADR-002 Target = onset of hyperglycaemic excursion within 120 min, asked only when glucose ≤ 180.** Predicting "glucose above 180 in the
next 2 h" while already above 180 is trivial and clinically useless. The onset formulation measures real early warning.
3 consecutive 5-minute readings (15 min) avoids single-reading noise.

**ADR-003 No database in v0.1.** The cohort is regenerated deterministically from the seed in the model bundle (about 1 s), and twin state
is in memory. PostgreSQL adds setup and operational burden with no benefit for a single-node demo, and neither Docker nor PostgreSQL exist in the
development environment. Revisit when multi-user demos or real ingestion are needed (B-13).

**ADR-004 One process, step-driven replay.** The client drives the replay clock (`POST /replay/{sid}/step`) instead of the server pushing over
WebSockets. Replay becomes deterministic and testable, with no extra infrastructure; the UI polls once per tick.

**ADR-005 Shared feature function for training and serving.** The online engine calls `build_feature_frame` on its history, so there is no
re-implementation and no skew. A parity test enforces it.

**ADR-006 Serve logistic regression for events; choose the trajectory model by validation RMSE.** Gradient boosting wins on AUROC
(0.936 vs 0.884), but the event model's explanation must be exact and additive for the doctor. We sum log-odds terms in clinically meaningful
groups because individual collinear glucose features produced sign-flipping, misleading per-feature explanations (observed in the first UI
review). Revisit with TreeSHAP (B-07).

**ADR-007 Recharts instead of Plotly.** It is a React-native declarative API and much smaller than plotly.js, which is enough for line, band and
reference lines. Charts are sized with our own ResizeObserver hook because `ResponsiveContainer` measured 0 px inside the CSS grid.

**ADR-008 TypeScript 5.9 instead of 7.x.** 7.x is the new native compiler; we stay on the mature 5.x line to avoid toolchain risk
before the deadline.

**ADR-009 Split-conformal 80% intervals.** These are distribution-free, cheap and honest (test coverage 0.76–0.80). Quantile models are
unnecessary for v0.1.

**ADR-010 Robustness audit as a separate command (wave 2).** `glucotwin audit` re-implements the protocol independently, checks it
reproduces `evaluation_report.json` exactly, then adds patient-bootstrap CIs, stricter (sustained) warning metrics, ablations, extra seeds and
a harder-realism stress test. The served model and the headline report are unchanged, so earlier numbers stay reproducible.

**ADR-011 Display-only synthetic genetics (wave 2).** The official brief lists genetic markers in the simulated EHR. We add family history and
a TCF7L2 rs7903146 genotype from a separate RNG stream, so all other data and metrics are byte-identical. They are not given a simulated effect,
because an invented effect size would let the model "discover" our own assumption.

**ADR-012 Replay limited to held-out test patients (wave 2).** Replaying a training patient shows in-sample predictions that look better
than held-out performance. The API now refuses it.

**ADR-013 Counterfactual what-if via local history fork, never via ingestion (U1, submission day).** "What if the patient ate *x* g of
carbs now" is answered by `TwinEngine.counterfactual_forecast`: it copies the in-memory observation history, appends one hypothetical meal
at `as_of` on the copy only, rebuilds the same leakage-safe features and calls the same served models twice. The real twin — streams, versioned
state, latest forecast, forecast history — is untouched (asserted byte-for-byte by tests), so simulations can never contaminate the demo replay
or the evaluation story. The response is explicitly labelled `is_simulated: true` with a "not medical advice" disclaimer, and the endpoint reuses
the replay guard (held-out test patients only) so in-sample model behaviour is never presented as held-out.
