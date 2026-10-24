"""The served model bundle: everything the online twin needs to issue a forecast."""

from __future__ import annotations

import logging
import pickle
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pandas as pd

from glucotwin.config import EVENT_HORIZON_MIN, FORECAST_HORIZONS_MIN
from glucotwin.contracts import ExcursionRisk, ForecastPoint, ModelCard, RiskFactor
from glucotwin.features import FEATURE_GROUPS, FEATURE_NAMES
from glucotwin.labels import EVENT_DEFINITION

log = logging.getLogger(__name__)

BUNDLE_FORMAT = 1


@dataclass
class ModelBundle:
    model_version: str
    trained_at: datetime
    trajectory_model: object
    event_model: object  # must provide predict_proba and contributions (LogisticEventModel)
    alert_threshold: float
    interval_half_width: dict[int, float]  # split-conformal half-widths per horizon (validation residuals)
    interval_level: float
    training_data: str
    cohort_params: dict = field(default_factory=dict)  # n_patients, days, seed used for training
    feature_names: list[str] = field(default_factory=lambda: list(FEATURE_NAMES))
    format: int = BUNDLE_FORMAT

    # ------------------------------------------------------------------ io
    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as fh:
            pickle.dump(self, fh)
        log.info("saved model bundle %s -> %s", self.model_version, path)

    @staticmethod
    def load(path: Path) -> ModelBundle:
        # Only load bundles produced locally by `glucotwin train` (pickle is not safe for untrusted files).
        with open(path, "rb") as fh:
            bundle = pickle.load(fh)
        if not isinstance(bundle, ModelBundle) or bundle.format != BUNDLE_FORMAT:
            raise ValueError(f"incompatible model bundle at {path}")
        return bundle

    # -------------------------------------------------------------- predict
    def risk_band(self, p: float) -> str:
        if p >= self.alert_threshold:
            return "high"
        if p >= 0.5 * self.alert_threshold:
            return "moderate"
        return "low"

    def predict_row(self, row: pd.DataFrame, issued_at: pd.Timestamp, top_k: int = 5):
        """Forecast for a single feature row (DataFrame with one row, FEATURE_NAMES columns)."""
        row = row[self.feature_names]
        traj = self.trajectory_model.predict(row).iloc[0]
        points = []
        for h in FORECAST_HORIZONS_MIN:
            g = float(traj[h])
            w = self.interval_half_width[h]
            points.append(ForecastPoint(
                horizon_min=h,
                timestamp=(issued_at + pd.Timedelta(minutes=h)).to_pydatetime(),
                glucose_mg_dl=round(g, 1),
                lower_mg_dl=round(max(g - w, 40.0), 1),
                upper_mg_dl=round(min(g + w, 400.0), 1),
            ))
        excursion = None
        current = float(row["glucose"].iloc[0])
        if current <= 180.0:
            p = float(self.event_model.predict_proba(row)[0])
            contrib = dict(zip(self.feature_names, self.event_model.contributions(row)[0], strict=True))
            groups = []
            for gid, label, rep, members in FEATURE_GROUPS:
                total = float(sum(contrib[m] for m in members if m in contrib))
                val = None if rep is None or pd.isna(row[rep].iloc[0]) else round(float(row[rep].iloc[0]), 2)
                groups.append(RiskFactor(feature=gid, label=label, value=val, contribution=round(total, 3)))
            factors = sorted(groups, key=lambda f: -abs(f.contribution))[:top_k]
            excursion = ExcursionRisk(
                event_definition=EVENT_DEFINITION,
                horizon_min=EVENT_HORIZON_MIN,
                probability=round(p, 4),
                alert_threshold=self.alert_threshold,
                alert=p >= self.alert_threshold,
                risk_band=self.risk_band(p),
                top_factors=factors,
            )
        return points, excursion

    def card(self) -> ModelCard:
        return ModelCard(
            model_version=self.model_version,
            trained_at=self.trained_at,
            feature_names=self.feature_names,
            event_model=getattr(self.event_model, "name", type(self.event_model).__name__),
            trajectory_model=getattr(self.trajectory_model, "name", type(self.trajectory_model).__name__),
            alert_threshold=self.alert_threshold,
            interval_level=self.interval_level,
            target_definition=EVENT_DEFINITION,
            training_data=self.training_data,
            intended_use="Research and education demo of a glucose digital twin. Not for clinical use.",
            limitations=[
                "Trained and evaluated only on synthetic patients from a simplified simulator.",
                "Performance on real patients is unknown and likely lower.",
                "Excursion risk is only issued when current glucose is <= 180 mg/dL.",
                "Explanations are associative (logistic-regression contributions), not causal.",
            ],
        )
