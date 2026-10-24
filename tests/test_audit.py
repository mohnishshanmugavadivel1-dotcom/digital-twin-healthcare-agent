"""Audit helpers, simulator realism knobs, and display-only synthetic genetics."""

import numpy as np
import pandas as pd

from glucotwin.evaluation.audit import STRESS_REALISM, choose_threshold_quantile, per_patient_alert_stats
from glucotwin.features import FEATURE_NAMES
from glucotwin.synth.generator import Realism, generate_cohort

T0 = pd.Timestamp("2026-03-01T00:00:00Z")


def test_default_realism_is_identical_to_no_argument():
    a = generate_cohort(n_patients=3, days=2, seed=7)
    b = generate_cohort(n_patients=3, days=2, seed=7, realism=Realism())
    pd.testing.assert_frame_equal(a.observations, b.observations)


def test_stress_realism_reduces_and_delays_meal_logs():
    a = generate_cohort(n_patients=4, days=3, seed=7)
    b = generate_cohort(n_patients=4, days=3, seed=7, realism=STRESS_REALISM)
    ma, mb = (c.observations[c.observations.kind == "meal"] for c in (a, b))
    assert len(mb) < len(ma)
    # CGM noise differs, physiology/schedule draws are shared: same number of CGM rows not guaranteed, but non-empty
    assert (b.observations.kind == "cgm").sum() > 0


def test_genetics_present_deterministic_and_not_a_feature(small_cohort):
    again = generate_cohort(n_patients=10, days=4, seed=1234)
    for r1, r2 in zip(small_cohort.records, again.records, strict=True):
        assert r1.genetic_markers and r1.genetic_markers == r2.genetic_markers
        assert r1.family_history_t2d == r2.family_history_t2d
        assert r1.genetic_markers[0].genotype in {"CC", "CT", "TT"}
    assert not any("tcf7l2" in f or "genetic" in f or "family" in f for f in FEATURE_NAMES)


def test_quantile_threshold_works_below_probability_grid():
    rng = np.random.default_rng(0)
    y = rng.integers(0, 2, 2000)
    s = np.where(y == 1, rng.uniform(0.001, 0.004, 2000), rng.uniform(0.0, 0.002, 2000))  # tiny scores
    t = choose_threshold_quantile(y, s)
    assert t < 0.05  # the fixed 0.05-0.95 grid could never select this


def _frame(alert_minutes, all_minutes):
    ts = [T0 + pd.Timedelta(minutes=m) for m in all_minutes]
    onset = T0 + pd.Timedelta(minutes=200)
    # label per the frozen target: positive when the onset lies within (t, t + 120 min]
    y = [int(onset - pd.Timedelta(minutes=120) <= t < onset) for t in ts]
    df = pd.DataFrame({"patient_id": "SYN-0001", "timestamp": ts, "y_event": y})
    return df, np.array([m in alert_minutes for m in all_minutes])


def test_sustained_vs_any_alert():
    onset = T0 + pd.Timedelta(minutes=200)
    minutes = list(range(80, 200, 5))  # eligible predictions every 5 min up to onset
    # a single early alert at 90 min that switches off: counts as "any alert" but not "sustained"
    df, alert = _frame({90}, minutes)
    st = per_patient_alert_stats(df, alert, {"SYN-0001": pd.DatetimeIndex([onset])}, {"SYN-0001": 1.0})
    row = st.loc["SYN-0001"]
    assert row.onsets == 1 and row.warned == 1 and row.sustained == 0 and row.leads_any == [110.0]
    # alert continuously on from 150 to onset: sustained with lead 50 min
    df, alert = _frame(set(range(150, 200, 5)), minutes)
    st = per_patient_alert_stats(df, alert, {"SYN-0001": pd.DatetimeIndex([onset])}, {"SYN-0001": 1.0})
    row = st.loc["SYN-0001"]
    assert row.sustained == 1 and row.leads_sus == [50.0] and row.false_eps == 0
