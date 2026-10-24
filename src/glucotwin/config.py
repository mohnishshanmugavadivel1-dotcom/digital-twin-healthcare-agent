"""Frozen project-wide constants (contract v0.1).

Changing anything here changes the target definition or the data contract and
must be accompanied by a version bump in ``contracts.SCHEMA_VERSION`` and an
entry in ``docs/DECISIONS.md``.
"""

from __future__ import annotations

# --- Sampling grid -----------------------------------------------------------
CGM_INTERVAL_MIN = 5  # CGM readings arrive every 5 minutes

# --- Clinical thresholds (international consensus on time in range) ----------
HYPER_THRESHOLD_MG_DL = 180.0
HYPO_THRESHOLD_MG_DL = 70.0

# --- Target definition -------------------------------------------------------
# A hyperglycaemic excursion is >= EXCURSION_MIN_READINGS consecutive CGM
# readings strictly above HYPER_THRESHOLD_MG_DL (i.e. >= 15 min sustained).
# The prediction task: at a time t when the latest CGM reading is <= 180 mg/dL,
# will an excursion *start* in (t, t + EVENT_HORIZON_MIN]?
EXCURSION_MIN_READINGS = 3
EVENT_HORIZON_MIN = 120
# Labels are undefined (excluded) when fewer than this fraction of the future
# window's CGM readings are present and no excursion was observed.
LABEL_MIN_FUTURE_COVERAGE = 0.5

# --- Trajectory forecast horizons -------------------------------------------
FORECAST_HORIZONS_MIN = (30, 60, 90, 120)

# --- Plausible value ranges for ingestion validation -------------------------
CGM_VALID_RANGE = (20.0, 600.0)
HR_VALID_RANGE = (25.0, 230.0)
STEPS_VALID_RANGE = (0.0, 2000.0)  # per 5-minute bin
MEAL_CARBS_VALID_RANGE = (0.0, 400.0)

# --- Online engine -----------------------------------------------------------
ENGINE_HISTORY_HOURS = 26  # history retained in memory (24 h features + margin)
STALE_CGM_MIN = 20  # no prediction is issued if latest CGM is older than this
MIN_CGM_READINGS_FOR_FORECAST = 6  # >= 30 min of data in the last hour

DISCLAIMER = (
    "Research prototype on synthetic data. Not a medical device. "
    "Forecasts are not diagnoses or treatment instructions."
)
