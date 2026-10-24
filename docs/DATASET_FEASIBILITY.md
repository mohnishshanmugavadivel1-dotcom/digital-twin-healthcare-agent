# Dataset feasibility report (Agent A, 2026-10-17)

**Bottom line.** No openly downloadable dataset links real clinical records with continuous glucose at the
patient level, has CGM resolution of 5 minutes or finer, and can be obtained before the submission deadline
(20 Oct 2026, 09:30 EDT). The strong real datasets require a data use agreement (DUA) signed by an institution. The best open
option, ShanghaiT2DM, is small and records CGM every 15 minutes. We therefore build on a **deterministic synthetic cohort** (this is also
what other teams report the challenge rules require; see "Competition data rules" below). An adapter for one open real
dataset is planned as an *external plausibility check*, not as a training source.

Legend: **[V]** verified from the cited source today · **[S]** from a secondary source (another
paper or repository), not independently confirmed · **[A]** our assumption.

## Candidate datasets

| Dataset | Population | Dynamic data | Clinical / EHR data | Patient-level link | Access / licence | Feasible by 20 Oct? |
|---|---|---|---|---|---|---|
| **ShanghaiT2DM / T1DM** | 100 T2D and 12 T1D patients, China [V] | CGM (FreeStyle Libre H) **every 15 min**, 3–14 days; dietary intake; insulin and oral agents [V] | Summary sheet: age, sex, BMI, smoking and drinking, diabetes duration, complications, HbA1c, fasting and 2-h glucose/C-peptide/insulin, lipids, creatinine, eGFR, medications [V] | **Yes.** Each summary row corresponds to one CGM excel file [V] | Open, **CC BY 4.0** on Figshare [V] | Yes, but figshare.com is not reachable from this sandbox, so the team must download it locally |
| CGMacros | 45 adults (15 healthy, 16 pre-diabetes, 14 T2D) [V] | 2 CGMs (Libre Pro 15 min, Dexcom G6), Fitbit, meal macros and photos, interpolated to 1 min [V] | Demographics, anthropometrics, bloodwork incl. HbA1c [V] | Yes [V] | PhysioNet; **CC BY-NC-SA 4.0** (non-commercial, share-alike) [S] | Possible, but share-alike obligations apply to derived data; physionet.org is not reachable here |
| OhioT1DM | 12 T1D on pumps, 8 weeks [V] | CGM every 5 min, insulin, meals, exercise, sleep, wristband HR/GSR [V] | Minimal (no real weight; placeholder 99) [V] | Yes | **DUA signed by an institutional legal signatory** [V] | **No** (DUA turnaround) |
| T1DEXI | 497 T1D [S] | CGM 5 min, exercise sessions [S] | Study case report forms [S] | Yes | Controlled access via Vivli/Jaeb, DUA [S] | **No** |
| DiaTrend | 54 T1D, about 27.5k CGM days [V] | CGM + pump [V] | Limited demographics [A] | Yes | Controlled (Synapse), DUA [S] | **No** |
| MetaboNet | 3,135 T1D subjects consolidated [S] | CGM + insulin [S] | Varies | Partial | Public subset after registration; the rest is under DUA [S] | Only the public subset; T1D only |

Sources:
* ShanghaiT1DM/T2DM: Zhao et al., *Scientific Data* 2023, https://www.nature.com/articles/s41597-023-01940-7 ; licence: https://figshare.com/articles/dataset/Diabetes_Datasets/20425518 (CC BY 4.0); collection DOI 10.6084/m9.figshare.c.6310860
* CGMacros: https://physionet.org/content/cgmacros/1.0.0/ ; https://www.nature.com/articles/s41597-025-05851-7 ; licence as reported by downstream repositories, e.g. https://github.com/ElijahZhao/ppgr-predictor
* OhioT1DM: http://smarthealth.cs.ohio.edu/OhioT1DM-dataset.html ; Marling & Bunescu 2020, https://pmc.ncbi.nlm.nih.gov/articles/PMC7881904/
* T1DEXI, DiaTrend access: https://journals.plos.org/digitalhealth/article?id=10.1371%2Fjournal.pdig.0001633 ; DiaTrend paper https://www.nature.com/articles/s41597-023-02469-5
* MetaboNet: https://arxiv.org/html/2601.11505v1
* Overview of open CGM datasets: Glucose-ML, https://arxiv.org/html/2507.14077v1

## Feasibility blockers (ranked)

1. **Time.** Submission closes in about 3 days. Every 5-minute CGM dataset with real clinical context requires an institutional DUA.
2. **Resolution.** The only open dataset with a patient-level EHR link (ShanghaiT2DM) records CGM every **15 minutes**. A 2-hour horizon is
   then only 8 steps, and "3 consecutive readings above 180" would mean 45 minutes instead of 15 [A]. The target definition would need
   a dataset-specific variant.
3. **No wearable stream in ShanghaiT2DM.** There are no steps or heart rate [V]. The "wearable" part of the challenge cannot
   be shown on it.
4. **Size and population.** 100 T2D patients with 3–14 days each (about 112k readings [S]) from a Chinese hospital population, not Indian.
5. **Sandbox egress.** figshare.com and physionet.org are blocked here, so integration has to be prepared as a download script
   the team runs locally. Raw data must never be committed (`data/` is git-ignored).
6. **Competition data rules (unconfirmed).** Several 2026 participant repositories state that only
   anonymised, open or **synthetic** data are allowed, and one says "all data is synthetic, as the challenge's data rules require" [S]:
   https://github.com/Varshith2403315/TeamDrafts_IITGoa , https://github.com/shashi-bhushan-27/digitalTwinChallenge .
   The official page's full text is truncated behind a "Read more" control and could not be read here.
   **Action for the team: confirm the data rules on Unstop before using any real dataset.**

## Decision and recommendation

* **Primary (implemented).** A synthetic T2D cohort (60 patients × 14 days, seed 20261017) from a simplified Bergman-type
  glucose–insulin model with meals, activity, dawn phenomenon, unobserved stress days, a CGM noise and lag model, dropouts,
  meal-logging errors and 10% unlogged meals. The observable EHR is derived from hidden physiology *with noise*.
* **Calibration evidence (actual run, seed 20261017).** Mean per-patient time in range is 77.8%, time above range 21.8%, time below range 0.4%, CV 0.25,
  HbA1c 5.5–9.0%. Published ShanghaiT2DM summary statistics are TIR 77.7 ± 18.1%, TAR 20.0 ± 18.4%, TBR 2.4 ± 7.2%
  ([S], Zhao et al. 2023, as quoted in the ResearchGate copy of the paper: https://www.researchgate.net/publication/367252616). Lows are under-represented in our simulator, which is a known limitation.
* **Next (backlog B-05).** A `scripts/fetch_shanghai_t2dm.py` adapter that maps a summary row to `PatientRecord` and an excel file to
  `Observation` rows. It would be used for a *real-data plausibility check* only: distribution comparison and running the trained
  pipeline on a 15-minute variant. Results must be labelled as such, and only if the team confirms that the rules allow it.
* **Not pursued now.** OhioT1DM, T1DEXI and DiaTrend (DUA timeline); CGMacros (share-alike licence obligations, plus egress).

## Is forecasting glucose excursions feasible?

Yes, on synthetic data, and the evidence comes from actual runs. On 12 held-out test patients, persistence has RMSE 18.7 mg/dL at 30 min
and 46.6 at 120 min. The 30-minute persistence value is in the range reported for real CGM data, e.g. 19.6 ± 3.8 mg/dL for a
sensor-augmented-pump baseline (Mosquera-Lopez & Jacobs 2022, https://journals.sagepub.com/doi/10.1177/19322968211042621).
Our learned models reach 10.4 mg/dL at 30 min, which is **better than real-world literature** for 30-minute forecasting (about 17–20 mg/dL;
e.g. Herrero et al. 2024, https://pmc.ncbi.nlm.nih.gov/articles/PMC11418465/). That strongly suggests the simulator is more
predictable than reality (accurate meal logs, a simple physiology model). Results must be presented as an upper bound.
