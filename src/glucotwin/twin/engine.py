"""The patient state engine: one virtual patient that updates as observations arrive.

Lifecycle
---------
1. ``ingest(batch)`` validates each observation (range, unit, timezone, ordering) and
   appends accepted ones to the history. Exact duplicates (same kind + timestamp) are
   ignored, so re-delivery is idempotent. Out-of-order observations (older than the
   latest accepted of the same kind) are rejected rather than silently re-sorted.
2. If at least one CGM reading was accepted, features are computed with the *same*
   function used in training (features.build_feature_frame) and a forecast is issued for
   each new CGM reading (mode="every") or only the latest one (mode="last").
3. ``TwinState`` is recomputed and its ``version`` incremented.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np
import pandas as pd

from glucotwin.config import (
    CGM_VALID_RANGE,
    ENGINE_HISTORY_HOURS,
    HR_VALID_RANGE,
    HYPER_THRESHOLD_MG_DL,
    HYPO_THRESHOLD_MG_DL,
    MEAL_CARBS_VALID_RANGE,
    MIN_CGM_READINGS_FOR_FORECAST,
    STALE_CGM_MIN,
    STEPS_VALID_RANGE,
)
from glucotwin.contracts import (
    OBSERVATION_UNITS,
    DataQuality,
    Forecast,
    ForecastSummary,
    GlycaemicSummary,
    IngestResult,
    Observation,
    ObservationKind,
    PatientRecord,
    PersonalParameters,
    TwinState,
)
from glucotwin.features import (
    FEATURE_NAMES,
    build_feature_frame,
    carb_sensitivity_prior,
    meal_responses,
    personal_carb_sensitivity,
)
from glucotwin.labels import to_grid
from glucotwin.models.bundle import ModelBundle

log = logging.getLogger(__name__)

VALID_RANGES = {
    ObservationKind.cgm: CGM_VALID_RANGE,
    ObservationKind.meal: MEAL_CARBS_VALID_RANGE,
    ObservationKind.steps: STEPS_VALID_RANGE,
    ObservationKind.heart_rate: HR_VALID_RANGE,
}
MAX_FORECAST_HISTORY = 5000


def feats_frame_empty() -> pd.DataFrame:
    """Empty feature frame with the serving columns (for withheld what-if forecasts)."""
    return pd.DataFrame(columns=FEATURE_NAMES)


@dataclass
class _Stream:
    times: list[pd.Timestamp]
    values: list[float]


class TwinEngine:
    def __init__(self, record: PatientRecord, bundle: ModelBundle):
        self.record = record
        self.bundle = bundle
        self.reset()

    # ------------------------------------------------------------------ state
    def reset(self) -> None:
        self._streams: dict[ObservationKind, _Stream] = {k: _Stream([], []) for k in ObservationKind}
        self.version = 0
        self.ingested = 0
        self.state: TwinState | None = None
        self.latest_forecast: Forecast | None = None
        self.forecast_history: list[ForecastSummary] = []

    @property
    def as_of(self) -> pd.Timestamp | None:
        last = [s.times[-1] for s in self._streams.values() if s.times]
        return max(last) if last else None

    def history_frame(self, since: pd.Timestamp | None = None) -> pd.DataFrame:
        frames = []
        for kind, s in self._streams.items():
            if not s.times:
                continue
            t = pd.DatetimeIndex(s.times)
            v = np.asarray(s.values, dtype=float)
            if since is not None:
                keep = t > since
                t, v = t[keep], v[keep]
            frames.append(pd.DataFrame({"timestamp": t, "kind": kind.value, "value": v}))
        if not frames:
            return pd.DataFrame(columns=["timestamp", "kind", "value"])
        return pd.concat(frames, ignore_index=True).sort_values(["timestamp", "kind"]).reset_index(drop=True)

    # ----------------------------------------------------------------- ingest
    def _validate(self, obs: Observation) -> str | None:
        if obs.patient_id != self.record.patient_id:
            return f"patient_id mismatch: {obs.patient_id}"
        expected_unit = OBSERVATION_UNITS[obs.kind]
        if obs.unit is not None and obs.unit != expected_unit:
            return f"{obs.kind.value} at {obs.timestamp.isoformat()}: unit '{obs.unit}' != '{expected_unit}'"
        lo, hi = VALID_RANGES[obs.kind]
        if not (lo <= obs.value <= hi) or not np.isfinite(obs.value):
            return f"{obs.kind.value} at {obs.timestamp.isoformat()}: value {obs.value} outside [{lo}, {hi}]"
        return None

    def ingest(self, observations: Iterable[Observation], forecast_mode: str = "every") -> IngestResult:
        accepted = duplicates = rejected = 0
        errors: list[str] = []
        new_cgm_times: list[pd.Timestamp] = []
        for obs in sorted(observations, key=lambda o: o.timestamp):
            err = self._validate(obs)
            if err:
                rejected += 1
                errors.append(err)
                continue
            ts = pd.Timestamp(obs.timestamp).tz_convert("UTC")
            stream = self._streams[obs.kind]
            if stream.times and ts <= stream.times[-1]:
                if ts in stream.times[-50:] or ts in stream.times:
                    duplicates += 1
                else:
                    rejected += 1
                    errors.append(f"{obs.kind.value} at {ts.isoformat()}: out of order (latest {stream.times[-1].isoformat()})")
                continue
            stream.times.append(ts)
            stream.values.append(float(obs.value))
            accepted += 1
            if obs.kind == ObservationKind.cgm:
                new_cgm_times.append(ts)
        self.ingested += accepted
        if accepted:
            if new_cgm_times:
                self._forecast(new_cgm_times, forecast_mode)
            self._update_state()
        return IngestResult(accepted=accepted, duplicates=duplicates, rejected=rejected, errors=errors[:50],
                            state=self.state, forecast=self.latest_forecast)

    def ingest_frame(self, frame: pd.DataFrame, forecast_mode: str = "every") -> IngestResult:
        """Fast path for trusted internal frames (replay): columns timestamp, kind, value."""
        obs = [
            Observation(patient_id=self.record.patient_id, timestamp=ts.to_pydatetime(), kind=ObservationKind(k), value=v)
            for ts, k, v in zip(frame["timestamp"], frame["kind"], frame["value"], strict=True)
        ]
        return self.ingest(obs, forecast_mode=forecast_mode) if obs else IngestResult(accepted=0, duplicates=0, rejected=0)

    # --------------------------------------------------------------- forecast
    def _responses(self, hist: pd.DataFrame) -> pd.DataFrame:
        cgm = hist[hist["kind"] == "cgm"]
        meals = hist[hist["kind"] == "meal"]
        grid = to_grid(pd.Series(cgm["value"].to_numpy(), index=pd.DatetimeIndex(cgm["timestamp"])))
        return meal_responses(grid, pd.Series(meals["value"].to_numpy(), index=pd.DatetimeIndex(meals["timestamp"])))

    def _forecast(self, new_cgm_times: list[pd.Timestamp], mode: str) -> None:
        targets = new_cgm_times if mode == "every" else new_cgm_times[-1:]
        full = self.history_frame()
        responses = self._responses(full)
        window = full[full["timestamp"] > targets[0] - pd.Timedelta(hours=ENGINE_HISTORY_HOURS)]
        feats = build_feature_frame(window, self.record, responses=responses,
                                    only_last=(len(targets) == 1 and targets[0] == full["timestamp"].max()))
        cgm_times = pd.DatetimeIndex(self._streams[ObservationKind.cgm].times)
        for t in targets:
            t_grid = t.round("5min")
            recent = cgm_times[(cgm_times > t - pd.Timedelta(minutes=60)) & (cgm_times <= t)]
            fid = uuid.uuid4().hex[:12]
            if len(recent) < MIN_CGM_READINGS_FOR_FORECAST or t_grid not in feats.index:
                fc = Forecast(forecast_id=fid, patient_id=self.record.patient_id, issued_at=t.to_pydatetime(),
                              model_version=self.bundle.model_version, status="insufficient_data",
                              reason=f"only {len(recent)} CGM readings in the last 60 min "
                                     f"(need {MIN_CGM_READINGS_FOR_FORECAST})",
                              current_glucose_mg_dl=None)
            else:
                row = feats.loc[[t_grid]]
                points, excursion = self.bundle.predict_row(row, t)
                fc = Forecast(forecast_id=fid, patient_id=self.record.patient_id, issued_at=t.to_pydatetime(),
                              model_version=self.bundle.model_version, status="ok",
                              current_glucose_mg_dl=float(row["glucose"].iloc[0]), trajectory=points,
                              excursion=excursion, interval_level=self.bundle.interval_level)
            self.latest_forecast = fc
            self.forecast_history.append(ForecastSummary(
                issued_at=fc.issued_at, status=fc.status, current_glucose_mg_dl=fc.current_glucose_mg_dl,
                probability=fc.excursion.probability if fc.excursion else None,
                alert=bool(fc.excursion and fc.excursion.alert),
                predicted={str(p.horizon_min): p.glucose_mg_dl for p in fc.trajectory},
            ))
        if len(self.forecast_history) > MAX_FORECAST_HISTORY:
            self.forecast_history = self.forecast_history[-MAX_FORECAST_HISTORY:]

    # ----------------------------------------------------------- counterfactual
    def counterfactual_forecast(self, meal_grams: float) -> tuple[Forecast, Forecast]:
        """Simulate "what if the patient ate ``meal_grams`` of carbs right now".

        Runs entirely on a local copy of the observation history: the hypothetical
        meal is NEVER ingested into this twin — streams, state, version,
        ``latest_forecast`` and ``forecast_history`` are untouched (enforced by
        tests/test_counterfactual.py). Returns ``(baseline, scenario)`` where the
        baseline is the forecast the twin would issue at ``as_of`` right now and
        the scenario adds one hypothetical meal at ``as_of`` before rebuilding the
        same features through the same served models. Simulated output only.
        """
        if not 1.0 <= float(meal_grams) <= 300.0:
            raise ValueError(f"meal_grams must be within [1, 300], got {meal_grams}")
        hist = self.history_frame()
        if hist.empty or not (hist["kind"] == ObservationKind.cgm.value).any():
            raise ValueError("counterfactual needs at least one CGM observation")
        t0 = pd.Timestamp(hist["timestamp"].max()).round("5min")
        # Same sufficiency gate as the served forecast path: a what-if must never look
        # more confident than the twin itself would be on the same evidence.
        cgm_mask = hist["kind"] == ObservationKind.cgm.value
        n_recent = int((cgm_mask & (hist["timestamp"] > t0 - pd.Timedelta(minutes=60))
                        & (hist["timestamp"] <= t0)).sum())
        if n_recent < MIN_CGM_READINGS_FOR_FORECAST:
            reason = f"only {n_recent} CGM readings in the last 60 min (need {MIN_CGM_READINGS_FOR_FORECAST})"
            empty = feats_frame_empty()
            return self._forecast_at(t0, empty, reason=reason), self._forecast_at(t0, empty, reason=reason)

        def features_for(frame: pd.DataFrame) -> pd.DataFrame:
            window = frame[frame["timestamp"] > t0 - pd.Timedelta(hours=ENGINE_HISTORY_HOURS)]
            return build_feature_frame(window, self.record, responses=self._responses(frame))

        baseline = self._forecast_at(t0, features_for(hist))
        scenario_hist = (
            pd.concat(
                [hist, pd.DataFrame({"timestamp": [t0], "kind": [ObservationKind.meal.value], "value": [float(meal_grams)]})],
                ignore_index=True,
            )
            .sort_values(["timestamp", "kind"])
            .reset_index(drop=True)
        )
        scenario = self._forecast_at(t0, features_for(scenario_hist))
        return baseline, scenario

    def _forecast_at(self, t: pd.Timestamp, feats: pd.DataFrame, reason: str | None = None) -> Forecast:
        """Standalone forecast builder for what-if scenarios (does NOT touch twin state)."""
        fid = uuid.uuid4().hex[:12]
        if reason is not None or t not in feats.index or pd.isna(feats.loc[t, "glucose"]):
            return Forecast(
                forecast_id=fid, patient_id=self.record.patient_id, issued_at=t.to_pydatetime(),
                model_version=self.bundle.model_version, status="insufficient_data",
                reason=reason or "not enough recent CGM data for a what-if forecast", current_glucose_mg_dl=None,
            )
        points, excursion = self.bundle.predict_row(feats.loc[[t]], t)
        return Forecast(
            forecast_id=fid, patient_id=self.record.patient_id, issued_at=t.to_pydatetime(),
            model_version=self.bundle.model_version, status="ok",
            current_glucose_mg_dl=float(feats.loc[t, "glucose"]),
            trajectory=points, excursion=excursion, interval_level=self.bundle.interval_level,
        )

    # ------------------------------------------------------------------ state
    def _update_state(self) -> None:
        now = self.as_of
        cgm_t = pd.DatetimeIndex(self._streams[ObservationKind.cgm].times)
        cgm_v = np.asarray(self._streams[ObservationKind.cgm].values, dtype=float)
        last_g = float(cgm_v[-1]) if cgm_v.size else None
        mins_since_cgm = (now - cgm_t[-1]).total_seconds() / 60 if cgm_v.size else None

        trend = None
        arrow = "unknown"
        if cgm_v.size:
            past = cgm_t[(cgm_t <= cgm_t[-1] - pd.Timedelta(minutes=10)) & (cgm_t >= cgm_t[-1] - pd.Timedelta(minutes=20))]
            if len(past):
                ref_t = past[-1]
                ref_v = cgm_v[cgm_t.get_loc(ref_t)]
                trend = (cgm_v[-1] - ref_v) / ((cgm_t[-1] - ref_t).total_seconds() / 60)
                a = abs(trend)
                arrow = "stable" if a < 1 else ("rising" if trend > 0 else "falling") if a < 2 else (
                    "rising_fast" if trend > 0 else "falling_fast")

        day = cgm_v[cgm_t > now - pd.Timedelta(hours=24)] if cgm_v.size else np.array([])
        summary = GlycaemicSummary(
            window_hours=24, n_readings=int(day.size),
            mean_mg_dl=round(float(day.mean()), 1) if day.size else None,
            cv_percent=round(float(100 * day.std() / day.mean()), 1) if day.size > 1 else None,
            time_in_range_pct=round(float(100 * np.mean((day >= HYPO_THRESHOLD_MG_DL) & (day <= HYPER_THRESHOLD_MG_DL))), 1) if day.size else None,
            time_above_range_pct=round(float(100 * np.mean(day > HYPER_THRESHOLD_MG_DL)), 1) if day.size else None,
            time_below_range_pct=round(float(100 * np.mean(day < HYPO_THRESHOLD_MG_DL)), 1) if day.size else None,
        )

        meals = self._streams[ObservationKind.meal]
        mt = pd.DatetimeIndex(meals.times)
        mv = np.asarray(meals.values, dtype=float)
        cob = 0.0
        mins_since_meal = None
        if mv.size:
            dt = (now - mt).total_seconds().to_numpy() / 60
            active = (dt >= 0) & (dt < 180)
            cob = float(np.sum(mv[active] * (1 - dt[active] / 180)))
            mins_since_meal = float(dt[-1])
        steps = self._streams[ObservationKind.steps]
        st = pd.DatetimeIndex(steps.times)
        steps_60 = float(np.sum(np.asarray(steps.values)[st > now - pd.Timedelta(minutes=60)])) if steps.times else 0.0
        hr = self._streams[ObservationKind.heart_rate]
        ht = pd.DatetimeIndex(hr.times)
        hr_recent = np.asarray(hr.values)[ht > now - pd.Timedelta(minutes=30)] if hr.times else np.array([])

        prior = carb_sensitivity_prior(self.record)
        responses = self._responses(self.history_frame())
        sens, k = personal_carb_sensitivity(responses, prior, pd.DatetimeIndex([now]))

        recent3 = cgm_t[cgm_t > now - pd.Timedelta(hours=3)] if cgm_v.size else []
        day_t = cgm_t[cgm_t > now - pd.Timedelta(hours=24)] if cgm_v.size else pd.DatetimeIndex([])
        gaps = int(np.sum(np.diff(day_t.asi8) > 30 * 60 * 1e9)) if len(day_t) > 1 else 0

        self.version += 1
        self.state = TwinState(
            patient_id=self.record.patient_id, as_of=now.to_pydatetime(), version=self.version,
            observations_ingested=self.ingested, last_glucose_mg_dl=last_g,
            glucose_trend_mg_dl_per_min=None if trend is None else round(float(trend), 2), trend_arrow=arrow,
            carbs_on_board_g=round(cob, 1), minutes_since_last_meal=None if mins_since_meal is None else round(mins_since_meal, 1),
            steps_last_60min=steps_60,
            mean_heart_rate_30min=round(float(hr_recent.mean()), 1) if hr_recent.size else None,
            summary_24h=summary,
            personal=PersonalParameters(carb_sensitivity_mg_dl_per_g=round(float(sens[0]), 3),
                                        carb_sensitivity_prior=round(prior, 3), meals_used=int(k[0])),
            data_quality=DataQuality(
                cgm_completeness_3h=round(min(len(recent3) / 36.0, 1.0), 3),
                minutes_since_last_cgm=None if mins_since_cgm is None else round(mins_since_cgm, 1),
                stale=mins_since_cgm is None or mins_since_cgm > STALE_CGM_MIN,
                gaps_over_30min_24h=gaps,
            ),
        )
