# Competition readiness (Agent G)

> **Superseded in part (2026-10-17, wave 2).** The official rules were found in full. See [COMPETITION_COMPLIANCE.md](COMPETITION_COMPLIANCE.md).
> In particular, the video must be a **minimum of 20 minutes** (not 15–20), and the current demo plan is [DEMO_SCRIPT.md](DEMO_SCRIPT.md).

## What is verified about the challenge

From the official Unstop page (https://unstop.com/hackathons/crp-digital-twin-challenge-2026-happiest-health-1757873, read 2026-10-17):

* Teams of 1–4 students. Prizes worth ₹2,00,000 plus pre-placement interviews.
* **Prototype & code submission: 18 Sep 2026 – 20 Oct 2026, 09:30 AM EDT (19:00 IST)**, submitted *as a GitHub repository with the
  required documentation as specified in the submission guidelines*.
* Top 10 teams present to the jury virtually (date TBA). The top 5 present at the Reimagining and Reforming Healthcare in India Summit,
  Bengaluru, 20 Nov 2026.
* The framing quoted on the page: a digital twin as "a dynamic, virtual replica of a patient, constantly updated with real-time data from wearables,
  paired with Electronic Health Records (EHR)", which can "predict adverse health events before they happen and personalize
  treatment protocols".
* The registration banner said registration closes on **18 Oct 2026, 19:00 IST**. **Confirm the team is registered.**

## What is not verified (needs confirmation from the official guidelines)

The full challenge text sits behind a "Read more" control that we could not read. The items below are inferred from **several other
participants' public READMEs**, which agree with each other, but they are secondary sources:

| Likely requirement | Source pattern | Status in this repo |
|---|---|---|
| Team details, college or incubator | all checklists | **Missing: team to fill in README** |
| Project title, problem statement, healthcare use case | all | Done (README) |
| Technical stack; AI/ML model and framework details | all | Done (README, ML_PLAN) |
| **15–20 minute unlisted YouTube demo video** | e.g. github.com/srujan1-creator/Digital-Twin-Challenge, github.com/Nikunj-Shah00000/Digital-Twin-Challenge-2026 | **Missing: script outline below** |
| Open-source licence | all | MIT `LICENSE` added. **Team must confirm the licence and the copyright holder** |
| **Architecture diagram as PDF/PPT** | all | Mermaid source in ARCHITECTURE.md. **PDF export missing (B-03)** |
| **Presentation as PDF/PPT** | all | Outline below. **Deck missing (B-04)** |
| Public repository, accessible without permissions | srujan1-creator | **Team must make the repo public** |
| Only anonymised, open or synthetic data | github.com/shashi-bhushan-27/digitalTwinChallenge, TeamDrafts_IITGoa | Synthetic only |

**Open questions for the organisers:** exact data rules; whether real open datasets (ShanghaiT2DM, CC BY 4.0) are allowed for
validation; the evaluation rubric and weights; the video length and format; whether a hosted demo is expected; the date of the jury round.

## Mapping challenge themes to deliverables

| Challenge expectation | GlucoTwin deliverable | Evidence |
|---|---|---|
| Virtual replica updated in real time | `TwinEngine` with versioned `TwinState` per observation; chronological replay | test_engine, test_api |
| Wearables + EHR fusion | CGM + steps + heart rate + meal logs, combined with record features (HbA1c, FPG, eGFR, medications) and an EHR-derived prior for a personal parameter | features.py |
| Predict an adverse event before it happens | 2-hour onset of hyperglycaemic excursion; median lead 95 min for the served model (synthetic) | evaluation report |
| Personalisation | Carb sensitivity learned online from each patient's own meal responses, shrunk towards an EHR prior | StatePanel, ML_PLAN |
| Doctor-facing dashboard | React dashboard | screenshots |
| Transparency | Evaluation tab: baselines, held-out patients, intervals, limitations | /api/evaluation |
| Responsible AI | Synthetic-only, disclaimers everywhere, no instructions, associations not causes | QA_SECURITY |

## Demo strategy (wave-1 draft; superseded by DEMO_SCRIPT.md, minimum 20 min)

1. 0:00–1:30. The problem: post-meal hyperglycaemia in Indian T2D, and why a 2-hour warning matters. State clearly that this is a prototype on synthetic data.
2. 1:30–4:00. What a digital twin is here: record + streams, then state, then forecast, then the doctor. Show the architecture diagram.
3. 4:00–10:00. Live dashboard. Pick a test patient with a meal-driven excursion. Play the replay through breakfast, watch risk rise
   before glucose crosses 180, read the factor groups, toggle "earlier predictions", and show the data-quality flag during a sensor gap.
4. 10:00–13:00. Personalisation: the carb-sensitivity estimate moving from the EHR prior as meals are observed.
5. 13:00–16:00. Evaluation tab. Baselines versus models, the false-alert trade-off, conformal intervals, and why numbers are an upper bound.
6. 16:00–18:00. Engineering quality: contracts, leakage tests (mention the mutation check), reproducibility (`make train`).
7. 18:00–20:00. Limitations, the path to real data (DUA datasets, ShanghaiT2DM check), and the regulatory path (CDSCO SaMD, DPDP).

## Presentation outline (10–12 slides)

1. Title, team, one-line value proposition
2. Clinical problem and Indian context (cite sources carefully; verify every statistic)
3. Solution overview: twin = record + stream, then state, then forecast, then doctor
4. Architecture diagram
5. Data: synthetic cohort design, calibration versus published CGM statistics, and why synthetic
6. Target definition and evaluation protocol (patient-level split, leakage safeguards)
7. Results: baselines versus models, event metrics, alert burden
8. Dashboard walkthrough (screenshots)
9. Personalisation and explanations
10. Responsible AI, limitations, safety wording
11. Roadmap: real-data validation, prospective study, integration (FHIR)
12. Ask and thanks

## Submission checklist

- [ ] Team details, college or incubator in README
- [ ] Repository public; default branch contains the submission
- [ ] Demo video recorded, uploaded unlisted, link in README
- [ ] Architecture diagram PDF in `docs/`
- [ ] Presentation PDF/PPT in `docs/`
- [x] Licence file (team to confirm)
- [x] Reproducible setup: `make setup && make train && make serve`
- [x] Evaluation report generated by the committed code
- [x] Synthetic-data disclaimer in UI, API, README
