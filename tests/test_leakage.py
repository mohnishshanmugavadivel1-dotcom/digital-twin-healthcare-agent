"""Temporal-leakage and train/serve-skew safeguards."""

import numpy as np
import pandas as pd

from glucotwin.dataset import build_cohort_table
from glucotwin.features import FEATURE_NAMES, build_feature_frame
from glucotwin.synth.generator import HiddenParams
from glucotwin.twin.engine import TwinEngine


def test_features_do_not_change_when_future_is_removed(small_cohort):
    rec = small_cohort.records[0]
    obs = small_cohort.patient_observations(rec.patient_id)
    full = build_feature_frame(obs, rec)
    rng = np.random.default_rng(0)
    for t in rng.choice(full.index[300:], size=5, replace=False):
        truncated = build_feature_frame(obs[obs["timestamp"] <= t], rec)
        pd.testing.assert_series_equal(full.loc[t], truncated.loc[t], check_names=False)


def test_online_engine_matches_offline_features(small_cohort, trained):
    """The twin's served forecast uses the same features as training (parity check)."""
    _, bundle, _, _ = trained
    rec = small_cohort.records[1]
    obs = small_cohort.patient_observations(rec.patient_id)
    offline = build_feature_frame(obs, rec)
    t = offline.index[400]
    eng = TwinEngine(rec, bundle)
    eng.ingest_frame(obs[obs["timestamp"] <= t], forecast_mode="last")
    points, _ = bundle.predict_row(offline.loc[[t]], t)
    served = eng.latest_forecast
    assert served.status == "ok"
    assert [p.glucose_mg_dl for p in served.trajectory] == [p.glucose_mg_dl for p in points]


def test_hidden_parameters_never_used_as_features():
    hidden = set(HiddenParams.__dataclass_fields__)
    assert hidden.isdisjoint(FEATURE_NAMES)
    assert not any(name.startswith(("y_", "true_")) for name in FEATURE_NAMES)


def test_patient_level_split_is_disjoint(small_cohort):
    table = build_cohort_table(small_cohort)
    per_patient = table.groupby("patient_id")["split"].nunique()
    assert (per_patient == 1).all()


def test_labels_only_on_eligible_rows(small_cohort):
    table = build_cohort_table(small_cohort)
    labelled = table.dropna(subset=["y_event"])
    assert (labelled["glucose"] <= 180).all()


def test_explanation_groups_cover_every_feature_exactly_once():
    from glucotwin.features import FEATURE_GROUPS

    members = [m for *_, ms in FEATURE_GROUPS for m in ms]
    assert sorted(members) == sorted(FEATURE_NAMES)
