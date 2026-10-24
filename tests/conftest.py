"""Shared, deterministic test fixtures (small cohort so the suite runs in well under a minute)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from glucotwin.contracts import PatientRecord, Sex

SMALL = {"n_patients": 10, "days": 4, "seed": 1234}


@pytest.fixture(scope="session")
def small_cohort():
    from glucotwin.synth.generator import generate_cohort

    return generate_cohort(**SMALL)


@pytest.fixture(scope="session")
def trained(tmp_path_factory):
    """(report, bundle, report_path) from the real pipeline on a small cohort."""
    from glucotwin.evaluation.pipeline import run_pipeline

    d = tmp_path_factory.mktemp("artifacts")
    report, bundle = run_pipeline(**SMALL, report_path=d / "report.json", bundle_path=d / "bundle.pkl")
    return report, bundle, d / "report.json", d / "bundle.pkl"


@pytest.fixture(scope="session")
def service(trained, small_cohort):
    from glucotwin.service import TwinService

    _, bundle, report_path, _ = trained
    return TwinService(bundle, report_path=report_path, cohort=small_cohort)


@pytest.fixture()
def record() -> PatientRecord:
    return PatientRecord(
        patient_id="SYN-0001", display_name="Test (synthetic)", age_years=50, sex=Sex.female, height_cm=160,
        weight_kg=70, bmi=27.3, diabetes_duration_years=5, hba1c_percent=7.5, fasting_glucose_mg_dl=140,
        egfr_ml_min_1_73m2=90,
    )


T0 = datetime(2026, 3, 2, 0, 0, tzinfo=UTC)


def cgm_frame(values, start=T0, step_min=5) -> pd.DataFrame:
    """Long-format CGM observations; None values are skipped (missing readings)."""
    rows = [
        {"timestamp": pd.Timestamp(start + timedelta(minutes=step_min * i)), "kind": "cgm", "value": float(v)}
        for i, v in enumerate(values)
        if v is not None
    ]
    return pd.DataFrame(rows)
