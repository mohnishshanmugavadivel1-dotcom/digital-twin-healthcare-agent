"""Record a static, clearly labelled demo snapshot from the REAL GlucoTwin API.

Drives the real FastAPI app in-process (FastAPI TestClient: real model bundle, real evaluation report, real
B-23 joint-support file) through the documented demo scenarios and saves every response the dashboard needs
as JSON under ``frontend/static-demo/demo/``. ``npm run build:static`` turns that into a static site that replays
the recorded responses: nothing is computed live, and the dashboard says so on every page.

Before writing anything, the script checks that the static replay is faithful:
  * observation and forecast-history queries answered from the recorded lists (same filtering rules as the API:
    ``timestamp > since``, at or before the replay clock, last ``limit`` items) equal the real API responses at
    sampled frames;
  * stepping the real replay by 60 min reaches exactly the recorded 5-min frames (step-size independence),
    so any multiple of 5 min can be served from the 5-min frames.
If any check fails it exits non-zero and writes nothing.

    .venv/bin/python scripts/export_static_demo.py [--out frontend/static-demo/demo]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from fastapi.testclient import TestClient  # noqa: E402

from glucotwin.api.app import create_app  # noqa: E402

STEP_MIN = 5
WINDOW_HOURS = 12  # must match WINDOW_HOURS in frontend/src/components/PatientView.tsx (it asks for 12 + 1 h)
OBS_LIMIT = 5000  # the dashboard's limit for observations and forecasts
KINDS = ("cgm", "meal", "steps", "heart_rate")
# carbs of the editable Indian meal presets (frontend/src/mealPresets.ts; a frontend test keeps them in sync)
# plus round amounts, including sizes that the B-23 check flags
PRESET_GRAMS = [25, 35, 36, 40, 45, 50]
WHATIF_GRAMS = sorted(set(PRESET_GRAMS) | {30, 60, 90, 120, 200, 300})
# the preset amounts are also recorded every PRESET_GRID_MIN minutes of each replay (all amounts at whatif_minutes)
PRESET_GRID_MIN = 15
FHIR_HOURS = 6  # CGM window of the recorded FHIR export (one export per scenario, at the replay start)
SCENARIOS = [
    {"id": "early-warning", "patient_id": "SYN-0039", "start_offset_hours": 151.833, "duration_hours": 6.0,
     "whatif_minutes": [0, 60],
     "title": "Early warning before an excursion, plus the what-if lab",
     "description": "Replay starts at 07:55 (glucose 94 mg/dL, excursion risk about 22%, no alert). Step forward to "
                    "see the alert fire at 08:55, right after the logged 140 g breakfast, 85 min before glucose first exceeds "
                    "180 mg/dL (10:20). What-ifs are recorded at "
                    "07:55 and 08:55 (2 min after the breakfast: larger hypothetical meals then fall outside training "
                    "support because the model counts carbs over the last 30 min)."},
    {"id": "unlogged-meal", "patient_id": "SYN-0019", "start_offset_hours": 253.667, "duration_hours": 6.0,
     "whatif_minutes": [0],
     "title": "Weakness: no meal logged, so the alert waits for the rise",
     "description": "Glucose rises with no logged meal. Risk stays below the 35% alert threshold until the rise has "
                    "begun: the alert fires at 14:50 (glucose 93 mg/dL, up from 70 at 14:35), 45 min before glucose "
                    "first exceeds 180 mg/dL (15:35). With a logged meal (first scenario) the warning comes earlier. "
                    "Stepping in 1-hour jumps skips the alert (14:45: 31%); the risk-history panel still shows it. "
                    "What-ifs are recorded at 13:45 only."},
]


def iso_ms(dt: datetime) -> str:
    """Same string as JavaScript's Date.toISOString() (millisecond precision, Z)."""
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def filter_obs(obs: list[dict], kind: str, since: str, clock: str) -> list[dict]:
    s, c = parse(since), parse(clock)
    out = [o for o in obs if o["kind"] == kind and parse(o["timestamp"]) > s and parse(o["timestamp"]) <= c]
    return out[-OBS_LIMIT:]


def filter_fc(fcs: list[dict], since: str, clock: str) -> list[dict]:
    s, c = parse(since), parse(clock)
    return [f for f in fcs if parse(f["issued_at"]) > s and parse(f["issued_at"]) <= c][-OBS_LIMIT:]


def ok(r, code=200):
    if r.status_code != code:
        raise SystemExit(f"API call failed: {r.request.method} {r.request.url} -> {r.status_code} {r.text[:300]}")
    return r.json()


def strip_ids(x, extra: tuple[str, ...] = ()):
    """Drop per-call random identifiers (and any ``extra`` keys) before comparing two responses."""
    if isinstance(x, dict):
        return {k: strip_ids(v, extra) for k, v in x.items() if k not in ("forecast_id", "session_id", *extra)}
    if isinstance(x, list):
        return [strip_ids(v, extra) for v in x]
    return x


def record_scenario(c: TestClient, sc: dict) -> dict:
    pid = sc["patient_id"]
    record = ok(c.get(f"/api/patients/{pid}"))
    st = ok(c.post("/api/replay", json={"patient_id": pid, "start_offset_hours": sc["start_offset_hours"],
                                         "duration_hours": sc["duration_hours"]}), 201)
    sid = st["session_id"]
    frames, summaries, whatifs, probes = [], [], [], []
    n_frames = int(sc["duration_hours"] * 60 / STEP_MIN) + 1
    probe_at = {0, 7, n_frames // 2, n_frames - 1}
    for i in range(n_frames):
        if i > 0:
            st = ok(c.post(f"/api/replay/{sid}/step", json={"minutes": STEP_MIN}))
        frames.append(st)
        summaries.append(next(p for p in ok(c.get("/api/patients")) if p["patient_id"] == pid))
        if i == 0:
            fhir = {"frame_index": 0, "hours": FHIR_HOURS,
                    "bundle": ok(c.get(f"/api/patients/{pid}/fhir", params={"hours": FHIR_HOURS}))}
        grams = (WHATIF_GRAMS if i * STEP_MIN in sc["whatif_minutes"]
                 else PRESET_GRAMS if (i * STEP_MIN) % PRESET_GRID_MIN == 0 else [])
        if grams:
            for g in grams:
                whatifs.append({"frame_index": i, "grams": g,
                                "result": ok(c.post(f"/api/patients/{pid}/counterfactual", json={"meal_grams": g}), 201)})
        if i in probe_at:  # real API answers to the exact queries the dashboard makes at this frame
            since = iso_ms(parse(st["clock"]) - timedelta(hours=WINDOW_HOURS + 1))
            probes.append({"frame_index": i, "since": since, "clock": st["clock"],
                           "obs": {k: ok(c.get(f"/api/patients/{pid}/observations",
                                               params={"kind": k, "since": since, "limit": OBS_LIMIT})) for k in KINDS},
                           "forecasts": ok(c.get(f"/api/patients/{pid}/forecasts", params={"since": since, "limit": OBS_LIMIT}))})
    first_since = iso_ms(parse(frames[0]["clock"]) - timedelta(hours=WINDOW_HOURS + 1))
    observations = []
    for k in KINDS:
        observations += ok(c.get(f"/api/patients/{pid}/observations", params={"kind": k, "since": first_since, "limit": 20000}))
    observations.sort(key=lambda o: (o["timestamp"], o["kind"]))
    forecasts = ok(c.get(f"/api/patients/{pid}/forecasts", params={"since": first_since, "limit": 5000}))
    if len(forecasts) >= 5000:
        raise SystemExit("forecast history hit the API limit; shorten the scenario")

    # check 1: the static filtering reproduces the real API at the probed frames
    for p in probes:
        for k in KINDS:
            if filter_obs(observations, k, p["since"], p["clock"]) != p["obs"][k]:
                raise SystemExit(f"{sc['id']}: static observation replay differs from the API ({k}, frame {p['frame_index']})")
        if strip_ids(filter_fc(forecasts, p["since"], p["clock"])) != strip_ids(p["forecasts"]):
            raise SystemExit(f"{sc['id']}: static forecast-history replay differs from the API (frame {p['frame_index']})")
    # check 2: a fresh replay stepped by 60 min lands exactly on the recorded 5-min frames
    st2 = ok(c.post("/api/replay", json={"patient_id": pid, "start_offset_hours": sc["start_offset_hours"],
                                          "duration_hours": sc["duration_hours"]}), 201)
    for i in range(0, n_frames, 60 // STEP_MIN):
        if i > 0:
            st2 = ok(c.post(f"/api/replay/{st2['session_id']}/step", json={"minutes": 60}))
        # state.version counts state updates, so it depends on the step size by design; everything else must match
        if strip_ids(st2, ("version",)) != strip_ids(frames[i], ("version",)):
            raise SystemExit(f"{sc['id']}: 60-min stepping differs from 5-min frames at frame {i}")
    if not frames[-1]["finished"]:
        raise SystemExit(f"{sc['id']}: the last recorded frame is not the end of the replay")
    return {**{k: sc[k] for k in ("id", "patient_id", "start_offset_hours", "duration_hours", "title", "description")},
            "step_minutes": STEP_MIN, "record": record, "frames": frames, "summaries": summaries,
            "observations": observations, "forecasts": forecasts, "whatifs": whatifs, "fhir": fhir,
            "checks": {"probed_frames": sorted(probe_at), "observation_and_forecast_replay_equals_api": True,
                       "step_60_equals_step_5_frames": True,
                       "step_comparison_ignores": ["forecast_id", "session_id",
                                                   "state.version (update counter; depends on step size)"]}}


def all_amount_frames(s: dict) -> set[int]:
    by: dict[int, set[int]] = {}
    for w in s["whatifs"]:
        by.setdefault(w["frame_index"], set()).add(w["grams"])
    return {i for i, g in by.items() if g >= set(WHATIF_GRAMS)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(REPO / "frontend/static-demo/demo"))
    args = ap.parse_args()
    c = TestClient(create_app())
    health = ok(c.get("/api/health"))
    model = ok(c.get("/api/model"))
    evaluation = ok(c.get("/api/evaluation"))
    scenarios = [record_scenario(c, sc) for sc in SCENARIOS]
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain"], cwd=REPO, capture_output=True, text=True).stdout.strip())
    b23 = REPO / "reports/research/b23_joint_support.json"
    manifest = {
        "kind": "glucotwin-static-demo-snapshot/1",
        "notice": "Static recorded snapshot of the GlucoTwin research prototype. Every response was recorded from the real "
                  "API; nothing is computed live. Synthetic patients only. Not a medical device.",
        "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "generator": "scripts/export_static_demo.py",
        "git_head": head, "working_tree_dirty_at_recording": dirty,
        "model_version": health["model_version"],
        "b23_joint_support_sha256": hashlib.sha256(b23.read_bytes()).hexdigest() if b23.exists() else None,
        "whatif_grams": WHATIF_GRAMS, "preset_grams": PRESET_GRAMS, "preset_grid_minutes": PRESET_GRID_MIN,
        "health": health, "model": model, "evaluation": evaluation,
        "scenarios": [{"id": s["id"], "patient_id": s["patient_id"], "start_offset_hours": s["start_offset_hours"],
                       "title": s["title"], "description": s["description"], "file": f"{s['id']}.json",
                       "start_clock": s["frames"][0]["clock"], "end_clock": s["frames"][-1]["clock"],
                       # clocks with every amount recorded; preset_clocks have the preset amounts only
                       "whatif_clocks": sorted({s["frames"][i]["clock"] for i in all_amount_frames(s)}),
                       "preset_clocks": sorted({s["frames"][w["frame_index"]]["clock"] for w in s["whatifs"]}),
                       "fhir_clock": s["frames"][s["fhir"]["frame_index"]]["clock"],
                       "n_frames": len(s["frames"])} for s in scenarios],
    }
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for s in scenarios:
        (out / f"{s['id']}.json").write_text(json.dumps(s, separators=(",", ":")) + "\n")
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    sizes = {p.name: p.stat().st_size for p in sorted(out.glob("*.json"))}
    print(f"wrote {out}: {sizes}")


if __name__ == "__main__":
    main()
