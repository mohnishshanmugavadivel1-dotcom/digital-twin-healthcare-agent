from datetime import timedelta

import pytest

from conftest import T0
from glucotwin.contracts import Observation
from glucotwin.twin.engine import TwinEngine


def obs(kind, minutes, value, pid="SYN-0001", unit=None):
    return Observation(patient_id=pid, timestamp=T0 + timedelta(minutes=minutes), kind=kind, value=value, unit=unit)


@pytest.fixture()
def engine(record, trained):
    _, bundle, _, _ = trained
    return TwinEngine(record, bundle)


def test_rejects_out_of_range_wrong_unit_and_wrong_patient(engine):
    res = engine.ingest([
        obs("cgm", 0, 900),
        obs("cgm", 5, 120, unit="mmol/L"),
        obs("cgm", 10, 120, pid="SYN-0002"),
        obs("heart_rate", 0, 400),
    ])
    assert res.accepted == 0 and res.rejected == 4 and len(res.errors) == 4
    assert engine.state is None


def test_duplicates_are_idempotent_and_out_of_order_rejected(engine):
    engine.ingest([obs("cgm", m, 120) for m in range(0, 60, 5)])
    v = engine.state.version
    res = engine.ingest([obs("cgm", 50, 120)])
    assert res.duplicates == 1 and res.accepted == 0 and engine.state.version == v
    res = engine.ingest([obs("cgm", 52, 120)])
    assert res.rejected == 1 and "out of order" in res.errors[0]


def test_insufficient_data_forecast(engine):
    res = engine.ingest([obs("cgm", 0, 120), obs("cgm", 5, 125)])
    assert res.forecast.status == "insufficient_data"
    assert res.forecast.trajectory == [] and res.forecast.excursion is None


def test_state_and_forecast_update_with_stream(engine):
    engine.ingest([obs("cgm", m, 110 + m / 5) for m in range(0, 120, 5)])
    s1 = engine.state
    assert s1.last_glucose_mg_dl == pytest.approx(133.0)
    assert s1.trend_arrow == "stable"
    engine.ingest([obs("meal", 121, 60), obs("cgm", 125, 140), obs("steps", 125, 50)])
    s2 = engine.state
    assert s2.version == s1.version + 1
    assert s2.carbs_on_board_g > 55
    fc = engine.latest_forecast
    assert fc.status == "ok" and len(fc.trajectory) == 4
    assert all(p.lower_mg_dl <= p.glucose_mg_dl <= p.upper_mg_dl for p in fc.trajectory)
    assert fc.excursion is not None and 0 <= fc.excursion.probability <= 1
    assert len(fc.excursion.top_factors) == 5
    assert {f.feature for f in fc.excursion.top_factors} <= {
        "glucose_level", "glucose_trend", "meals", "activity", "history_24h", "time_of_day", "record"}
    assert "Not a medical device" in fc.disclaimer


def test_no_excursion_risk_when_already_high(engine):
    engine.ingest([obs("cgm", m, 200) for m in range(0, 120, 5)])
    assert engine.latest_forecast.status == "ok"
    assert engine.latest_forecast.excursion is None


def test_stale_flag_when_cgm_stops(engine):
    engine.ingest([obs("cgm", m, 120) for m in range(0, 60, 5)])
    engine.ingest([obs("steps", 120, 10)])
    assert engine.state.data_quality.stale is True
    assert engine.state.data_quality.minutes_since_last_cgm == pytest.approx(65.0)
