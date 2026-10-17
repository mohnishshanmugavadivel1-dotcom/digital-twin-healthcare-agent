"""Assemble the supervised learning table (features + labels) for a cohort."""

from __future__ import annotations

import logging

import pandas as pd

from glucotwin.features import build_feature_frame, split_streams
from glucotwin.labels import event_labels, to_grid, trajectory_targets
from glucotwin.synth.generator import Cohort

log = logging.getLogger(__name__)


def build_patient_table(obs: pd.DataFrame, record) -> pd.DataFrame:
    feats = build_feature_frame(obs, record)
    if feats.empty:
        return feats
    grid = to_grid(split_streams(obs)["cgm"])
    table = feats.join(event_labels(grid, feats.index)).join(trajectory_targets(grid, feats.index))
    table.index.name = "timestamp"
    table = table.reset_index()
    table.insert(0, "patient_id", record.patient_id)
    table.insert(1, "split", record.split)
    return table


def build_cohort_table(cohort: Cohort) -> pd.DataFrame:
    tables = []
    for rec in cohort.records:
        tables.append(build_patient_table(cohort.patient_observations(rec.patient_id), rec))
    table = pd.concat(tables, ignore_index=True)
    log.info("built table: %d rows, %d patients", len(table), table["patient_id"].nunique())
    return table
