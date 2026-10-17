from datetime import datetime

import pytest
from pydantic import ValidationError

from glucotwin.contracts import Observation, ObservationKind


def test_observation_requires_timezone():
    with pytest.raises(ValidationError):
        Observation(patient_id="SYN-0001", timestamp=datetime(2026, 1, 1, 8, 0), kind=ObservationKind.cgm, value=120)


def test_patient_id_must_be_synthetic_prefix():
    with pytest.raises(ValidationError):
        Observation(patient_id="MRN-12345", timestamp="2026-01-01T08:00:00Z", kind="cgm", value=120)


def test_extra_fields_forbidden():
    with pytest.raises(ValidationError):
        Observation(patient_id="SYN-0001", timestamp="2026-01-01T08:00:00Z", kind="cgm", value=120, name="x")


def test_record_is_marked_synthetic(record):
    assert record.is_synthetic is True
    assert "is_synthetic" in record.model_dump()
