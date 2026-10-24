"""Find deterministic, honest demo moments on HELD-OUT test patients (backlog B-11).

A good demo moment is an excursion onset where the served model's alert came on well before the onset,
stayed on until the onset ("sustained"), started while glucose was still comfortably in range, and
followed a logged meal. Also lists a MISSED onset so the demo can show a failure honestly.

Usage:  .venv/bin/python scripts/find_demo_scenario.py  [--top 5]
Prints the dashboard deep link (?patient=...&start=...) that starts the replay 60 min before the alert.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from glucotwin.dataset import build_patient_table
from glucotwin.features import FEATURE_NAMES, split_streams
from glucotwin.labels import excursion_onsets, to_grid
from glucotwin.models.bundle import ModelBundle
from glucotwin.synth.generator import generate_cohort

GAP = pd.Timedelta(minutes=10)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--bundle", default="artifacts/model_bundle.pkl")
    args = ap.parse_args()
    bundle = ModelBundle.load(Path(args.bundle))
    cohort = generate_cohort(**bundle.cohort_params)
    thr = bundle.alert_threshold
    good, missed = [], []
    for rec in (r for r in cohort.records if r.split == "test"):
        obs = cohort.patient_observations(rec.patient_id)
        streams = split_streams(obs)
        table = build_patient_table(obs, rec)
        elig = table.dropna(subset=["y_event"]).copy()
        elig["p"] = bundle.event_model.predict_proba(elig[FEATURE_NAMES])
        elig["alert"] = elig["p"] >= thr
        ts = pd.DatetimeIndex(elig["timestamp"])
        al = elig["alert"].to_numpy()
        data_start = obs["timestamp"].min().floor("5min")
        local = pd.Timedelta(minutes=rec.utc_offset_minutes)
        meals = streams["meal"]
        for onset in excursion_onsets(to_grid(streams["cgm"])):
            win = (ts >= onset - pd.Timedelta(minutes=120)) & (ts < onset)
            if not win.any() or (onset - data_start) < pd.Timedelta(hours=30):
                continue
            last = np.flatnonzero(win)[-1]
            hour = (onset + local).hour
            if not al[last]:
                if 8 <= hour <= 21:
                    missed.append((rec.patient_id, (onset + local).tz_localize(None), float(elig["p"].iloc[last])))
                continue
            k = last  # walk back to the start of the continuous alert episode
            while k > 0 and al[k - 1] and (ts[k] - ts[k - 1]) <= GAP:
                k -= 1
            start = ts[k]
            lead = (onset - start).total_seconds() / 60
            g0 = float(elig["glucose"].iloc[k])
            meal_before = meals[(meals.index <= start) & (meals.index > start - pd.Timedelta(minutes=45))]
            if 60 <= lead <= 115 and g0 <= 150 and 8 <= hour <= 21 and len(meal_before):
                prior = (ts >= start - pd.Timedelta(hours=3)) & (ts < start) & al
                peak = float(streams["cgm"].loc[onset: onset + pd.Timedelta(hours=2)].max())
                good.append(dict(patient=rec.patient_id, name=rec.display_name, alert_start_local=(start + local).tz_localize(None),
                                 onset_local=(onset + local).tz_localize(None), lead_min=lead, glucose_at_alert=g0,
                                 p_at_alert=float(elig["p"].iloc[k]), meal_g=float(meal_before.iloc[-1]),
                                 peak_after=peak, alerts_in_prior_3h=int(prior.sum()),
                                 start_offset_h=round(((start - pd.Timedelta(minutes=60)) - data_start) / pd.Timedelta(hours=1), 3)))
    df = pd.DataFrame(good).sort_values(["alerts_in_prior_3h", "lead_min"], ascending=[True, False])
    pd.set_option("display.width", 220)
    print(f"served threshold {thr}; {len(df)} candidate demo moments on test patients\n")
    print(df.head(args.top).to_string(index=False))
    if len(df):
        b = df.iloc[0]
        print(f"\nDeep link: /?patient={b.patient}&start={b.start_offset_h}   (then press '+1 h' once to reach the alert)")
    print(f"\nMissed onsets (alert off just before onset), first 5 of {len(missed)}:")
    for pid, onset, p in missed[:5]:
        print(f"  {pid} onset {onset} (local)  p just before onset={p:.2f}")


if __name__ == "__main__":
    main()
