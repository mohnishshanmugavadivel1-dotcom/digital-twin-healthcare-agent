"""Ambulatory glucose profile (AGP) summary from the CGM readings a twin has received.

Metrics follow the international consensus on CGM reporting (Battelino et al., Diabetes Care 2019;42:1593):
time in range 70-180 mg/dL, time above 180 and 250, time below 70 and 54, mean glucose, coefficient of
variation, and the glucose management indicator GMI (%) = 3.31 + 0.02392 x mean glucose in mg/dL
(Bergenstal et al., Diabetes Care 2018;41:2275). The consensus recommends at least 14 days with at least 70%
of possible readings; ``sufficient`` reports whether that is met. The hourly profile gives the 5th, 25th,
50th, 75th and 95th percentiles by hour of the patient's local day. Descriptive only, from synthetic data;
not a diagnosis and never used by a forecast.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from glucotwin.contracts import AgpHour, AgpSummary

CGM_INTERVAL_MIN = 5
PERCENTILES = (5, 25, 50, 75, 95)
MIN_DAYS, MIN_COVERAGE = 14, 0.70


def agp_summary(patient_id: str, times: pd.DatetimeIndex, values: np.ndarray, as_of: pd.Timestamp,
                utc_offset_minutes: int, days: int = 14) -> AgpSummary:
    """Summarise CGM readings in (as_of - days, as_of]. ``times`` are UTC timestamps."""
    times = pd.DatetimeIndex(times)
    v = np.asarray(values, dtype=float)
    start = as_of - pd.Timedelta(days=days)
    keep = (times > start) & (times <= as_of) & np.isfinite(v)
    t, g = times[keep], v[keep]
    span_days = 0.0 if len(t) == 0 else min(days, (as_of - t.min()).total_seconds() / 86400)
    expected = days * 24 * 60 / CGM_INTERVAL_MIN
    coverage = len(g) / expected if expected else 0.0

    def pct(mask: np.ndarray) -> float | None:
        return round(float(100 * mask.mean()), 1) if g.size else None

    mean = float(g.mean()) if g.size else None
    hours: list[AgpHour] = []
    if g.size:
        local_hour = ((t + pd.Timedelta(minutes=utc_offset_minutes)).hour).to_numpy()
        for h in range(24):
            gh = g[local_hour == h]
            if gh.size:
                q = np.percentile(gh, PERCENTILES)
                hours.append(AgpHour(hour=h, n=int(gh.size), p5=round(float(q[0]), 1), p25=round(float(q[1]), 1),
                                     p50=round(float(q[2]), 1), p75=round(float(q[3]), 1), p95=round(float(q[4]), 1)))
    return AgpSummary(
        patient_id=patient_id,
        as_of=as_of.to_pydatetime(),
        window_days=days,
        days_with_data=round(span_days, 1),
        n_readings=int(g.size),
        coverage_pct=round(100 * coverage, 1),
        sufficient=bool(span_days >= MIN_DAYS - 0.01 and coverage >= MIN_COVERAGE),
        mean_mg_dl=None if mean is None else round(mean, 1),
        gmi_pct=None if mean is None else round(3.31 + 0.02392 * mean, 1),
        cv_pct=round(float(100 * g.std() / g.mean()), 1) if g.size > 1 else None,
        tir_70_180_pct=pct((g >= 70) & (g <= 180)),
        tar_181_250_pct=pct((g > 180) & (g <= 250)),
        tar_over_250_pct=pct(g > 250),
        tbr_54_69_pct=pct((g >= 54) & (g < 70)),
        tbr_under_54_pct=pct(g < 54),
        hourly=hours,
        utc_offset_minutes=utc_offset_minutes,
    )
