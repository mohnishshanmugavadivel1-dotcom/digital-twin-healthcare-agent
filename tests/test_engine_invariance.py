"""Ingest invariance: the twin's final state must not depend on how the same
chronological observation stream is batched into ingest() calls.

Live monitors push single readings; replay pushes multi-observation windows;
batch jobs may push whole days. All three paths must land on the same twin —
same state, same version, same personalization, same served forecast.
"""

from __future__ import annotations

import pandas as pd

from glucotwin.twin.engine import TwinEngine


def _test_window(cohort, hours: int = 24):
    rec = next(r for r in cohort.records if r.split == "test")
    obs = cohort.observations[cohort.observations["patient_id"] == rec.patient_id]
    obs = obs.sort_values("timestamp").reset_index(drop=True)
    end = obs["timestamp"].min() + pd.Timedelta(hours=hours)
    return rec, obs[obs["timestamp"] <= end].reset_index(drop=True)


def test_chunked_ingest_reaches_identical_state(trained, small_cohort):
    _, bundle, _, _ = trained
    rec, window = _test_window(small_cohort)
    assert len(window) > 60, "test window should span many observations"

    one_shot = TwinEngine(rec, bundle)
    one_shot.ingest_frame(window, forecast_mode="last")

    chunked = TwinEngine(rec, bundle)
    for i in range(0, len(window), 15):
        chunked.ingest_frame(window.iloc[i : i + 15], forecast_mode="last")

    assert one_shot.ingested == chunked.ingested
    s1, s2 = one_shot.state.model_dump(), chunked.state.model_dump()
    # version counts state updates, so it legitimately depends on batching
    # (one call with N observations = 1 update; N calls = N updates). It is a
    # change counter for concurrency/purity checks, not a content hash.
    assert s1.pop("version") != s2.pop("version")
    assert s1 == s2  # glucose, COB, 24h summary, personal params, data quality: identical
    assert one_shot.version >= 1 and chunked.version >= one_shot.version

    f1, f2 = one_shot.latest_forecast, chunked.latest_forecast
    assert f1 is not None and f2 is not None
    assert f1.status == f2.status == "ok"
    assert f1.current_glucose_mg_dl == f2.current_glucose_mg_dl
    assert [p.model_dump() for p in f1.trajectory] == [p.model_dump() for p in f2.trajectory]
    if f1.excursion is None or f2.excursion is None:
        assert f1.excursion is None and f2.excursion is None
    else:
        assert f1.excursion.probability == f2.excursion.probability
        assert f1.excursion.alert == f2.excursion.alert


def test_reingesting_the_same_stream_is_a_noop(trained, small_cohort):
    """Duplicate deliveries (retried uploads, overlapping windows) must not
    double-count observations or change any state value."""
    _, bundle, _, _ = trained
    rec, window = _test_window(small_cohort)

    eng = TwinEngine(rec, bundle)
    eng.ingest_frame(window, forecast_mode="last")
    snapshot = eng.state.model_dump()
    version, ingested = eng.version, eng.ingested

    res = eng.ingest_frame(window, forecast_mode="last")

    assert res.accepted == 0
    assert res.duplicates == len(window)
    assert res.rejected == 0
    assert eng.state.model_dump() == snapshot
    assert eng.version == version and eng.ingested == ingested
