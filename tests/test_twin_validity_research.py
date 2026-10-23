"""The paired-intervention helpers must reproduce the generator exactly before any counterfactual is trusted."""

from __future__ import annotations

import numpy as np

from glucotwin.synth.generator import generate_cohort
from glucotwin.twin_validity_research import paired_meal_delta, reconstruct


def _true_matrix(cohort) -> np.ndarray:
    tg = cohort.true_glucose.pivot(index="timestamp", columns="patient_id", values="glucose")
    return tg[[r.patient_id for r in cohort.records]].to_numpy().T


def test_reconstruction_reproduces_cohort_true_glucose_exactly():
    cohort = generate_cohort(n_patients=5, days=2, seed=123)
    _, plasma = reconstruct(5, 2, 123)
    idx = np.arange(0, plasma.shape[1], 5) + 4
    # the cohort stores true glucose rounded to 0.1 mg/dL (generator: np.round(true5, 1)); apply the same rounding
    np.testing.assert_array_equal(np.round(plasma[:, idx[idx < plasma.shape[1]]], 1), _true_matrix(cohort))


def test_zero_gram_intervention_changes_nothing_and_a_meal_raises_glucose_after_it_starts():
    inp, plasma = reconstruct(4, 2, 7)
    pidx = np.array([0, 1, 2, 3, 0])
    start = np.array([600, 700, 800, 900, 1500])
    zero = paired_meal_delta(inp, plasma, pidx, start, np.zeros(5), horizon_min=120)
    assert np.all(zero == 0.0)
    d = paired_meal_delta(inp, plasma, pidx, start, np.full(5, 40.0), horizon_min=120)
    assert np.all(d[:, 0] == 0.0)
    assert np.all(d[:, 1:].max(axis=1) > 5.0)  # a 40 g meal raises interstitial glucose within 2 h
