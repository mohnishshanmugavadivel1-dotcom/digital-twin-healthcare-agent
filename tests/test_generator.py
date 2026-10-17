import numpy as np
import pandas as pd

from glucotwin.contracts import PatientRecord
from glucotwin.synth.generator import HiddenParams, assign_splits, generate_cohort


def test_generation_is_deterministic():
    a = generate_cohort(n_patients=3, days=2, seed=7)
    b = generate_cohort(n_patients=3, days=2, seed=7)
    pd.testing.assert_frame_equal(a.observations, b.observations)
    assert [r.model_dump() for r in a.records] == [r.model_dump() for r in b.records]


def test_different_seed_differs():
    a = generate_cohort(n_patients=3, days=2, seed=7)
    b = generate_cohort(n_patients=3, days=2, seed=8)
    assert not a.observations["value"].equals(b.observations["value"])


def test_values_in_plausible_ranges(small_cohort):
    obs = small_cohort.observations
    cgm = obs[obs.kind == "cgm"]["value"]
    assert cgm.between(40, 400).all()
    assert obs[obs.kind == "heart_rate"]["value"].between(30, 220).all()
    assert (obs[obs.kind == "steps"]["value"] >= 0).all()
    assert obs[obs.kind == "meal"]["value"].between(0, 400).all()
    # timestamps are tz-aware UTC and on the 5-minute grid for CGM
    ts = pd.DatetimeIndex(obs["timestamp"])
    assert str(ts.tz) == "UTC"
    assert (pd.DatetimeIndex(obs[obs.kind == "cgm"]["timestamp"]).minute % 5 == 0).all()


def test_cgm_has_realistic_gaps(small_cohort):
    """Dropouts must exist so missing-data handling is exercised."""
    n_expected = small_cohort.days * 288 * len(small_cohort.records)
    n_cgm = (small_cohort.observations.kind == "cgm").sum()
    assert 0.8 * n_expected < n_cgm < n_expected


def test_ids_are_synthetic_and_splits_disjoint(small_cohort):
    ids = [r.patient_id for r in small_cohort.records]
    assert all(i.startswith("SYN-") for i in ids)
    splits = {r.split for r in small_cohort.records}
    assert splits == {"train", "validation", "test"}
    s = assign_splits(50, seed=3)
    assert len(s) == 50 and s.count("train") == 30 and s.count("validation") == 10 and s.count("test") == 10


def test_hidden_physiology_not_in_observable_record():
    hidden = set(HiddenParams.__dataclass_fields__)
    assert hidden.isdisjoint(PatientRecord.model_fields)


def test_glycaemic_profile_is_plausible(small_cohort):
    cgm = small_cohort.observations.query("kind == 'cgm'")["value"].to_numpy()
    tir = np.mean((cgm >= 70) & (cgm <= 180))
    assert 0.5 < tir < 0.95  # T2D cohort: neither perfectly controlled nor implausibly bad
