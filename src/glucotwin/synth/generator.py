"""Deterministic synthetic T2D cohort generator.

Design
------
Each virtual patient has *hidden* physiological parameters (never exposed to
models or the API) and an *observable* synthetic health record derived from
them with noise, mimicking what a clinic would actually know.

Physiology: an extended Bergman minimal model integrated with 1-minute Euler
steps, vectorised across patients::

    dG/dt = -(p1 + X + e_x*A) * G + p1 * Gb(t) + Ra(t) / (Vg * BW)
    dX/dt = -p2 * X + p3 * I
    dI/dt = -n * I + gamma * max(G - Gb, 0)              (endogenous secretion)
    gut:  dQ1/dt = -Q1/tau + u(t);  dQ2/dt = (Q1 - Q2)/tau;  Ra = f * Q2 / tau

* ``Gb(t)`` includes a dawn-phenomenon bump and occasional unobserved
  "stress days" (elevated baseline) so that not everything is predictable.
* ``A`` is physical activity derived from steps; it raises glucose uptake.
* CGM = first-order interstitial lag + multiplicative sensor bias + AR(1)
  noise, sampled every 5 min, with random dropouts (gaps).
* Meal logs carry log-normal carb-estimation error and ~10 % of meals are
  never logged.

This is a plausibility-oriented simulator for software development and a
transparent demo. It is *not* a validated physiological model, and metrics
computed on it do not transfer to real patients.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd

from glucotwin.config import CGM_INTERVAL_MIN
from glucotwin.contracts import GeneticMarker, LabResult, Medication, PatientRecord, Sex

DATASET_NAME = "glucotwin-synthetic-t2d"
DATASET_VERSION = "0.1.0"
DEFAULT_SEED = 20261017
DEFAULT_START_LOCAL = datetime(2026, 3, 2, 0, 0)  # a Monday, local clock
UTC_OFFSET_MIN = 330  # Asia/Kolkata

_FIRST_NAMES_F = ["Asha", "Meera", "Lakshmi", "Priya", "Kavita", "Anita", "Sunita", "Deepa", "Farah", "Neha"]
_SURNAME_INITIALS = "KSRNPMDGBTV"
_FIRST_NAMES_M = ["Ravi", "Arjun", "Suresh", "Imran", "Vikram", "Mohan", "Rahul", "Karthik", "Anil", "Joseph"]


@dataclass(frozen=True)
class HiddenParams:
    """Ground-truth physiology. Must never be used as model input."""

    gb: np.ndarray  # basal glucose, mg/dL
    p1: np.ndarray  # glucose effectiveness, 1/min
    x_tonic: np.ndarray  # glucose-independent insulin action (SU / basal insulin), 1/min
    p2: np.ndarray  # remote insulin decay, 1/min
    p3: np.ndarray  # insulin action gain
    gamma: np.ndarray  # secretion gain
    n_clear: np.ndarray  # insulin clearance, 1/min
    tau_meal: np.ndarray  # gut absorption time constant, min
    ex_gain: np.ndarray  # exercise uptake gain, 1/min
    bw: np.ndarray  # body weight, kg
    dawn: np.ndarray  # fractional dawn rise of Gb
    hr_rest: np.ndarray  # resting heart rate


@dataclass
class Cohort:
    records: list[PatientRecord]
    observations: pd.DataFrame  # columns: patient_id, timestamp (UTC), kind, value
    true_glucose: pd.DataFrame  # columns: patient_id, timestamp, glucose (5-min, noiseless) - for audit only
    hidden: HiddenParams
    seed: int
    days: int
    start_utc: datetime

    def patient_observations(self, patient_id: str) -> pd.DataFrame:
        obs = self.observations
        return obs[obs["patient_id"] == patient_id].reset_index(drop=True)

    def record(self, patient_id: str) -> PatientRecord:
        for rec in self.records:
            if rec.patient_id == patient_id:
                return rec
        raise KeyError(patient_id)


def assign_splits(n_patients: int, seed: int, fractions=(0.6, 0.2, 0.2)) -> list[str]:
    """Patient-level split. Deterministic given the seed."""
    rng = np.random.default_rng(seed + 7)
    order = rng.permutation(n_patients)
    n_train = int(round(fractions[0] * n_patients))
    n_val = int(round(fractions[1] * n_patients))
    splits = np.empty(n_patients, dtype=object)
    splits[order[:n_train]] = "train"
    splits[order[n_train : n_train + n_val]] = "validation"
    splits[order[n_train + n_val :]] = "test"
    return list(splits)


def _sample_patients(rng: np.random.Generator, n: int):
    age = rng.integers(30, 76, n)
    female = rng.random(n) < 0.45
    height = np.where(female, rng.normal(156, 6, n), rng.normal(169, 7, n))
    bmi = np.clip(rng.normal(27.5, 4.0, n), 20, 40)
    weight = bmi * (height / 100) ** 2
    duration = np.clip(rng.gamma(2.0, 3.5, n), 0.3, 25)
    severity = np.clip(rng.beta(2.2, 2.6, n) + 0.015 * (duration - 7), 0, 1)

    on_metformin = rng.random(n) < 0.85
    on_su = (rng.random(n) < 0.35 + 0.3 * severity)
    on_dpp4 = rng.random(n) < 0.3
    on_basal = (severity > 0.7) & (rng.random(n) < 0.6)

    gb = 112 + 70 * severity
    gb = np.where(on_metformin, gb * 0.94, gb)
    gb = np.where(on_basal, gb * 0.90, gb)
    gamma = 0.0045 * (1 - 0.7 * severity) * rng.lognormal(0, 0.2, n)
    gamma = np.where(on_su, gamma * 1.5, gamma)
    gamma = np.where(on_dpp4, gamma * 1.15, gamma)
    si = 5.5e-4 * np.exp(-(bmi - 22) / 14) * rng.lognormal(0, 0.25, n)
    p2 = np.full(n, 0.025)
    p1 = rng.uniform(0.012, 0.022, n)
    # glucose-independent insulin action (sulfonylurea / basal insulin) as a fraction of p1;
    # this is what makes hypoglycaemia possible in fasting / exercise periods.
    tonic = np.where(on_su, rng.uniform(0.25, 0.60, n), 0.0) + np.where(on_basal, rng.uniform(0.15, 0.35, n), 0.0)
    hidden = HiddenParams(
        gb=gb,
        p1=p1,
        x_tonic=tonic * p1,
        p2=p2,
        p3=si * p2,
        gamma=gamma,
        n_clear=np.full(n, 0.14),
        tau_meal=rng.uniform(30, 55, n),
        ex_gain=rng.uniform(0.012, 0.024, n),
        bw=weight,
        dawn=rng.uniform(0.03, 0.12, n),
        hr_rest=rng.normal(74, 7, n),
    )
    demo = dict(
        age=age, female=female, height=height, bmi=bmi, weight=weight, duration=duration,
        on_metformin=on_metformin, on_su=on_su, on_dpp4=on_dpp4, on_basal=on_basal, severity=severity,
    )
    return hidden, demo


@dataclass(frozen=True)
class Realism:
    """Knobs for how hard the observable data are. Defaults reproduce the published v0.1 cohort exactly.

    Used by the robustness audit (``glucotwin audit``) to test how much reported performance
    depends on optimistic assumptions (near-perfect, real-time meal logging; low sensor noise).
    """

    meal_log_prob: float = 0.9  # probability that a meal is logged at all
    carb_log_sigma: float = 0.25  # log-normal SD of the carb-estimation error
    meal_log_delay_max_min: int = 0  # logs appear U(0, max) minutes after eating (timestamp = log time)
    cgm_noise_sd: float = 4.5  # AR(1) innovation SD of the CGM sensor noise (mg/dL)


DEFAULT_REALISM = Realism()


def _daily_schedule(rng: np.random.Generator, n: int, days: int, realism: Realism = DEFAULT_REALISM,
                    delay_rng: np.random.Generator | None = None):
    """Return carb input per minute (n, T) in grams/min, logged meals, and activity (n, T) in steps/min."""
    T = days * 1440
    carbs = np.zeros((n, T))
    steps = np.zeros((n, T))
    meal_events: list[tuple[int, int, float]] = []  # (patient, minute, logged_carbs)
    for p in range(n):
        carb_scale = rng.uniform(0.8, 1.25)
        for d in range(days):
            base = d * 1440
            weekend = (d % 7) >= 5
            plan = [
                (8.0 + (1.0 if weekend else 0.0), 0.7, (35, 75), 1.0),  # breakfast
                (13.5, 0.75, (45, 95), 1.0),  # lunch
                (17.0, 0.5, (12, 35), 0.55),  # snack
                (20.75, 0.75, (45, 95), 1.0),  # dinner
            ]
            for hour, sd, (lo, hi), prob in plan:
                if rng.random() > prob:
                    continue
                minute = int(np.clip(base + 60 * rng.normal(hour, sd), base, base + 1439))
                true_g = rng.uniform(lo, hi) * carb_scale
                dur = 15
                carbs[p, minute : min(minute + dur, T)] += true_g / dur
                if rng.random() < realism.meal_log_prob:  # default: 10 % of meals are never logged
                    logged = true_g * rng.lognormal(0, realism.carb_log_sigma)
                    log_minute = minute
                    if realism.meal_log_delay_max_min > 0 and delay_rng is not None:
                        # separate RNG so the default cohort's random stream is unchanged
                        log_minute = min(minute + int(delay_rng.integers(0, realism.meal_log_delay_max_min + 1)), T - 1)
                    meal_events.append((p, log_minute, float(np.round(logged))))
            # activity
            awake = np.arange(base + 6 * 60 + 30, base + 23 * 60)
            steps[p, awake] = rng.poisson(rng.uniform(4, 12), awake.size)
            if rng.random() < 0.5:  # morning walk
                s = int(base + 60 * rng.normal(6.75, 0.3))
                steps[p, s : s + int(rng.uniform(20, 45))] = rng.normal(105, 10)
            if rng.random() < 0.3:  # post-dinner walk
                s = int(base + 60 * rng.normal(21.6, 0.3))
                steps[p, s : s + int(rng.uniform(15, 30))] = rng.normal(95, 10)
    return carbs, np.clip(steps, 0, None), meal_events


def _simulate(hp: HiddenParams, carbs: np.ndarray, steps: np.ndarray, rng: np.random.Generator, days: int):
    n, T = carbs.shape
    minute_of_day = np.arange(T) % 1440
    dawn_curve = np.exp(-0.5 * ((minute_of_day - 6 * 60) / 75.0) ** 2)  # peak 06:00
    stress = np.ones((n, days))
    stress[rng.random((n, days)) < 0.12] = 1.12  # unobserved stress/illness days
    G = hp.gb.copy() * 1.02
    X = np.zeros(n)
    Ins = np.zeros(n)
    Q1 = np.zeros(n)
    Q2 = np.zeros(n)
    out = np.empty((n, T))
    vg = 1.7  # dL/kg
    f_bio = 0.65  # effective systemic appearance after hepatic first-pass (calibrated)
    activity = np.clip(steps / 100.0, 0, 1.3)
    act_eff = np.zeros(n)
    for t in range(T):
        day = t // 1440
        gb_t = hp.gb * (1 + hp.dawn * dawn_curve[t]) * stress[:, day]
        ra = f_bio * Q2 / hp.tau_meal  # g/min
        act_eff += (activity[:, t] - act_eff) / 20.0  # activity effect builds/decays over ~20 min
        dG = -(hp.p1 + X + hp.x_tonic + hp.ex_gain * act_eff) * G + hp.p1 * gb_t + ra * 1000.0 / (vg * hp.bw)
        dX = -hp.p2 * X + hp.p3 * Ins
        dI = -hp.n_clear * Ins + hp.gamma * np.maximum(G - hp.gb, 0) * 1.0
        dQ1 = -Q1 / hp.tau_meal + carbs[:, t]
        dQ2 = (Q1 - Q2) / hp.tau_meal
        G = np.clip(G + dG, 40, 500)
        X = np.maximum(X + dX, 0)
        Ins = np.maximum(Ins + dI, 0)
        Q1 = np.maximum(Q1 + dQ1, 0)
        Q2 = np.maximum(Q2 + dQ2, 0)
        out[:, t] = G
    return out


def _cgm_from_plasma(plasma: np.ndarray, rng: np.random.Generator, noise_sd: float = 4.5):
    n, T = plasma.shape
    ig = np.empty_like(plasma)
    ig[:, 0] = plasma[:, 0]
    for t in range(1, T):  # interstitial lag ~10 min
        ig[:, t] = ig[:, t - 1] + (plasma[:, t] - ig[:, t - 1]) / 10.0
    idx = np.arange(0, T, CGM_INTERVAL_MIN) + (CGM_INTERVAL_MIN - 1)
    idx = idx[idx < T]
    sampled = ig[:, idx]
    bias = rng.normal(1.0, 0.04, (n, 1))
    noise = np.zeros_like(sampled)
    for k in range(1, sampled.shape[1]):
        noise[:, k] = 0.7 * noise[:, k - 1] + rng.normal(0, noise_sd, n)
    cgm = np.clip(np.round(sampled * bias + noise), 40, 400)
    # dropouts: a few multi-reading gaps per patient + sparse single misses
    mask = rng.random(cgm.shape) < 0.005
    for p in range(n):
        for _ in range(rng.poisson(2.5)):
            s = rng.integers(0, cgm.shape[1])
            mask[p, s : s + rng.integers(6, 36)] = True
    cgm = np.where(mask, np.nan, cgm)
    return idx, cgm, plasma[:, idx]


def generate_cohort(n_patients: int = 60, days: int = 14, seed: int = DEFAULT_SEED,
                    realism: Realism = DEFAULT_REALISM) -> Cohort:
    """Generate a deterministic synthetic cohort. Same (n, days, seed, realism) -> identical output."""
    if n_patients < 1 or days < 1:
        raise ValueError("n_patients and days must be >= 1")
    rng = np.random.default_rng(seed)
    hp, demo = _sample_patients(rng, n_patients)
    carbs, steps_min, meal_events = _daily_schedule(rng, n_patients, days, realism,
                                                    delay_rng=np.random.default_rng([seed, 7]))
    plasma = _simulate(hp, carbs, steps_min, rng, days)
    idx, cgm, true5 = _cgm_from_plasma(plasma, rng, realism.cgm_noise_sd)

    start_utc = (DEFAULT_START_LOCAL - timedelta(minutes=UTC_OFFSET_MIN)).replace(tzinfo=UTC)
    start_ts = pd.Timestamp(start_utc)
    ts5 = start_ts + pd.to_timedelta(idx + 1, unit="min")  # bin end time
    ids = [f"SYN-{i + 1:04d}" for i in range(n_patients)]
    splits = assign_splits(n_patients, seed)

    frames = []
    truth_frames = []
    T = days * 1440
    for p, pid in enumerate(ids):
        valid = ~np.isnan(cgm[p])
        frames.append(pd.DataFrame({"patient_id": pid, "timestamp": ts5[valid], "kind": "cgm", "value": cgm[p][valid]}))
        truth_frames.append(pd.DataFrame({"patient_id": pid, "timestamp": ts5, "glucose": np.round(true5[p], 1)}))
        steps5 = steps_min[p, : (T // 5) * 5].reshape(-1, 5).sum(axis=1)
        hr_minute = hp.hr_rest[p] + 55 * np.clip(steps_min[p] / 100.0, 0, 1.3)
        hr5 = hr_minute[: (T // 5) * 5].reshape(-1, 5).mean(axis=1) + rng.normal(0, 2.5, T // 5)
        # sleeping heart rate a bit lower (local 23:00-06:30)
        mod = (np.arange(T // 5) * 5) % 1440
        hr5 = np.where((mod >= 23 * 60) | (mod < 6 * 60 + 30), hr5 - 8, hr5)
        wear = rng.random(T // 5) > 0.03  # wristband occasionally not worn
        frames.append(pd.DataFrame({"patient_id": pid, "timestamp": ts5[wear], "kind": "steps",
                                    "value": np.round(steps5[wear])}))
        frames.append(pd.DataFrame({"patient_id": pid, "timestamp": ts5[wear], "kind": "heart_rate",
                                    "value": np.round(hr5[wear], 1)}))
    meals = pd.DataFrame(meal_events, columns=["p", "minute", "value"])
    if not meals.empty:
        meals["patient_id"] = [ids[i] for i in meals["p"]]
        meals["timestamp"] = start_ts + pd.to_timedelta(meals["minute"], unit="min")
        meals["kind"] = "meal"
        frames.append(meals[["patient_id", "timestamp", "kind", "value"]])
    obs = pd.concat(frames, ignore_index=True).sort_values(["patient_id", "timestamp", "kind"]).reset_index(drop=True)

    records = _add_genetics(_build_records(ids, splits, demo, hp, cgm, rng, start_utc), seed)
    return Cohort(records=records, observations=obs, true_glucose=pd.concat(truth_frames, ignore_index=True),
                  hidden=hp, seed=seed, days=days, start_utc=start_utc)


def _build_records(ids, splits, demo, hp: HiddenParams, cgm, rng, start_utc) -> list[PatientRecord]:
    records = []
    for p, pid in enumerate(ids):
        mean_g = float(np.nanmean(cgm[p]))
        hba1c = float(np.clip((mean_g + 46.7) / 28.7 + rng.normal(0, 0.3), 5.5, 14))  # ADAG relation + noise
        fpg = float(np.clip(hp.gb[p] + rng.normal(0, 8), 70, 350))
        egfr = float(np.clip(rng.normal(95 - 0.5 * (demo["age"][p] - 30), 14), 25, 130))
        female = bool(demo["female"][p])
        names = _FIRST_NAMES_F if female else _FIRST_NAMES_M
        meds = []
        if demo["on_metformin"][p]:
            meds.append(Medication(name="Metformin", drug_class="biguanide", dose="1000 mg BD"))
        if demo["on_su"][p]:
            meds.append(Medication(name="Glimepiride", drug_class="sulfonylurea", dose="2 mg OD"))
        if demo["on_dpp4"][p]:
            meds.append(Medication(name="Sitagliptin", drug_class="dpp4_inhibitor", dose="100 mg OD"))
        if demo["on_basal"][p]:
            meds.append(Medication(name="Insulin glargine", drug_class="basal_insulin", dose="14 U at bedtime"))
        conditions = ["Type 2 diabetes mellitus"]
        if rng.random() < 0.5:
            conditions.append("Essential hypertension")
            meds.append(Medication(name="Ramipril", drug_class="ace_inhibitor", dose="5 mg OD"))
        if rng.random() < 0.45:
            conditions.append("Dyslipidaemia")
            meds.append(Medication(name="Atorvastatin", drug_class="statin", dose="20 mg OD"))
        lab_time = start_utc - timedelta(days=int(rng.integers(7, 60)))
        labs = [
            LabResult(name="HbA1c", value=round(hba1c, 1), unit="%", measured_at=lab_time),
            LabResult(name="Fasting plasma glucose", value=round(fpg), unit="mg/dL", measured_at=lab_time),
            LabResult(name="eGFR", value=round(egfr), unit="mL/min/1.73m2", measured_at=lab_time),
            LabResult(name="LDL cholesterol", value=round(float(rng.normal(110, 30))), unit="mg/dL", measured_at=lab_time),
        ]
        records.append(PatientRecord(
            patient_id=pid,
            display_name=f"{names[p % len(names)]} {_SURNAME_INITIALS[(p // len(names)) % len(_SURNAME_INITIALS)]}. (synthetic)",
            age_years=int(demo["age"][p]),
            sex=Sex.female if female else Sex.male,
            height_cm=round(float(demo["height"][p]), 1),
            weight_kg=round(float(demo["weight"][p]), 1),
            bmi=round(float(demo["bmi"][p]), 1),
            diabetes_duration_years=round(float(demo["duration"][p]), 1),
            hba1c_percent=round(hba1c, 1),
            fasting_glucose_mg_dl=round(fpg),
            egfr_ml_min_1_73m2=round(egfr),
            conditions=conditions,
            medications=meds,
            labs=labs,
            utc_offset_minutes=UTC_OFFSET_MIN,
            split=splits[p],
        ))
    return records


# Illustrative allele frequency for the TCF7L2 rs7903146 T allele. ASSUMPTION for synthetic display only
# (not taken from a verified population source); it has no effect on simulated physiology or on the model.
TCF7L2_T_ALLELE_FREQ = 0.3


def _add_genetics(records: list[PatientRecord], seed: int) -> list[PatientRecord]:
    """Attach synthetic family history + one genotype per record using a SEPARATE RNG stream,
    so all other cohort values (and every reported metric) are unchanged."""
    grng = np.random.default_rng([seed, 11])
    out = []
    for r in records:
        k = int(grng.binomial(2, TCF7L2_T_ALLELE_FREQ))
        fam = bool(grng.random() < 0.5)
        marker = GeneticMarker(gene="TCF7L2", variant="rs7903146", genotype=["CC", "CT", "TT"][k], risk_alleles=k)
        out.append(r.model_copy(update={"family_history_t2d": fam, "genetic_markers": [marker]}))
    return out
