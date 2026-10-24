"""Research-only helpers for paired simulator interventions (experiments/twin_validity/protocol.json).

Not imported by the API, the engine or the training pipeline. The simulator is used exactly as the
generator defines it: hidden parameters, meal/activity schedule and stress-day draws are re-created
from the cohort seed by replaying the generator's random-number sequence, and ``_simulate`` is called
unchanged. ``reconstruct`` must reproduce the cohort's stored true glucose exactly (checked by the
analysis script and by tests) before any counterfactual is trusted.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, fields

import numpy as np

from glucotwin.synth.generator import (
    DEFAULT_REALISM,
    HiddenParams,
    _daily_schedule,
    _sample_patients,
    _simulate,
)

MEAL_DURATION_MIN = 15  # the generator spreads every meal over 15 min (_daily_schedule)
SENSOR_LAG_MIN = 10.0  # the generator's interstitial lag (_cgm_from_plasma)


class _FixedStress:
    """Stand-in for the generator RNG inside ``_simulate``: returns pre-drawn stress-day uniforms per row."""

    def __init__(self, u: np.ndarray):
        self._u = u

    def random(self, shape):
        if tuple(shape) != self._u.shape:
            raise ValueError(f"unexpected draw shape {shape}, expected {self._u.shape}")
        return self._u


@dataclass(frozen=True)
class SimInputs:
    hidden: HiddenParams
    carbs: np.ndarray  # (n, T) grams per minute, true intake
    steps: np.ndarray  # (n, T) steps per minute
    stress_u: np.ndarray  # (n, days) the uniforms _simulate draws for stress days
    days: int


def reconstruct(n_patients: int, days: int, seed: int) -> tuple[SimInputs, np.ndarray]:
    """Re-create the simulator inputs of ``generate_cohort(n_patients, days, seed)`` and its plasma glucose."""
    rng = np.random.default_rng(seed)
    hp, _ = _sample_patients(rng, n_patients)
    carbs, steps, _ = _daily_schedule(rng, n_patients, days, DEFAULT_REALISM,
                                      delay_rng=np.random.default_rng([seed, 7]))
    probe = np.random.default_rng()
    probe.bit_generator.state = copy.deepcopy(rng.bit_generator.state)
    stress_u = probe.random((n_patients, days))  # first draw inside _simulate
    plasma = _simulate(hp, carbs, steps, rng, days)
    return SimInputs(hp, carbs, steps, stress_u, days), plasma


def _rows(hp: HiddenParams, idx: np.ndarray) -> HiddenParams:
    return HiddenParams(**{f.name: np.asarray(getattr(hp, f.name))[idx] for f in fields(HiddenParams)})


def paired_meal_delta(inp: SimInputs, plasma: np.ndarray, patient_idx: np.ndarray, start_min: np.ndarray,
                      grams: np.ndarray, horizon_min: int = 120) -> np.ndarray:
    """Noiseless interstitial-glucose difference (with extra meal minus without) for each row.

    Row i adds ``grams[i]`` of true carbohydrate to patient ``patient_idx[i]`` starting at minute
    ``start_min[i]`` (spread over 15 min, as the generator does). Returns an array (rows, horizon_min + 1)
    where column h is the difference at minute ``start_min + h - 1`` of the plasma index, i.e. h minutes
    after a meal logged at time ``start + start_min`` (column 0 is always 0).
    """
    patient_idx, start_min = np.asarray(patient_idx), np.asarray(start_min, dtype=int)
    grams = np.asarray(grams, dtype=float)
    t_end = int(start_min.max()) + horizon_min + 1
    carbs = inp.carbs[patient_idx, :t_end].copy()
    for i, (m, g) in enumerate(zip(start_min, grams, strict=True)):
        carbs[i, m : m + MEAL_DURATION_MIN] += g / MEAL_DURATION_MIN
    out = _simulate(_rows(inp.hidden, patient_idx), carbs, inp.steps[patient_idx, :t_end],
                    _FixedStress(inp.stress_u[patient_idx]), inp.days)
    dp = out - plasma[patient_idx, :t_end]
    # the sensor-lag filter is linear, so the interstitial difference is the filtered plasma difference
    ig = np.zeros_like(dp)
    for t in range(1, t_end):
        ig[:, t] = ig[:, t - 1] + (dp[:, t] - ig[:, t - 1]) / SENSOR_LAG_MIN
    res = np.zeros((len(patient_idx), horizon_min + 1))
    for i, m in enumerate(start_min):
        res[i, 1:] = ig[i, m : m + horizon_min]
    return res
