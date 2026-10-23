"""Real-data experiment (ShanghaiT2DM) — ingestion, units, chronology, gaps, windows, split leakage, models, guards.

Every data frame and workbook here is a small UNIT-TEST FIXTURE generated in the test (deterministic numbers, made-up
header strings). None of it is, or stands in for, real ShanghaiT2DM data; the real archive is never read by tests.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from glucotwin.features import FEATURE_NAMES
from glucotwin.realdata import compat, models, shanghai
from glucotwin.realdata.split import assert_disjoint, assign, patient_split
from glucotwin.realdata.windows import FEATURES, add_features, build_windows

REPO = Path(__file__).resolve().parents[1]
CFG = json.loads((REPO / "experiments/shanghai_t2dm/config.json").read_text())
RULES = CFG["cleaning"]
SID = shanghai.SessionId("2901", 0, "19990101", "Shanghai_T2DM/2901_0_19990101.xlsx")
COLS = shanghai.ColumnMap("Date", "CGM (mg / dl)", "mg/dL")


def raw(times, values) -> pd.DataFrame:
    return pd.DataFrame({"Date": pd.to_datetime(times), "CGM (mg / dl)": values})


def regular(n=20, start="2021-01-01 08:00", step=15, base=120.0) -> pd.DataFrame:
    t = pd.date_range(start, periods=n, freq=f"{step}min")
    return raw(t, base + np.arange(n, dtype=float))


# ---------------------------------------------------------------- names, members, columns, units
def test_member_names_parse_and_reject():
    s = shanghai.parse_member_name("x/Shanghai_T2DM/2998_1_19991231.xlsx")
    assert (s.patient_id, s.period, s.start_date, s.session_id) == ("2998", 1, "19991231", "2998_1_19991231")
    for bad in ("Shanghai_T2DM/2998_19991231.xlsx", "Shanghai_T2DM/abc_0_19991231.xls", "Shanghai_T2DM/2998_0_1999.xlsx"):
        with pytest.raises(shanghai.SchemaError):
            shanghai.parse_member_name(bad)


def test_member_listing_keeps_only_t2dm_workbooks_and_one_summary():
    names = ["d/Shanghai_T2DM/", "d/Shanghai_T2DM/2901_0_19990101.xlsx", "d/Shanghai_T2DM/2902_0_19990102.xls",
             "d/Shanghai_T1DM/1901_0_19990101.xlsx", "d/Shanghai_T2DM_Summary.xlsx", "d/Shanghai_T1DM_Summary.xlsx",
             "__MACOSX/d/Shanghai_T2DM/._2901_0_19990101.xlsx", "d/Shanghai_T2DM/notes.txt"]
    sessions, summary, ignored = shanghai.list_members(names)
    assert sessions == ["d/Shanghai_T2DM/2901_0_19990101.xlsx", "d/Shanghai_T2DM/2902_0_19990102.xls"]
    assert summary == "d/Shanghai_T2DM_Summary.xlsx"
    assert "d/Shanghai_T1DM/1901_0_19990101.xlsx" in ignored and len(ignored) == 5
    with pytest.raises(shanghai.SchemaError):
        shanghai.list_members(["a/Shanghai_T2DM_Summary.xlsx", "b/Shanghai_T2DM_Summary.xls"])


def test_column_detection_and_header_units():
    c = shanghai.detect_columns(["Date", "CGM (mg / dl)", "CBG (mg / dl)", "Blood Ketone (mmol / L)", "Dietary intake",
                                 "Insulin dose - s.c.", "Insulin dose - i.v.", "Non-insulin hypoglycemic agents",
                                 "CSII - bolus insulin (Novolin R, IU)", "CSII - basal insulin (Novolin R, IU / H)"])
    assert (c.date, c.cgm, c.cgm_header_unit) == ("Date", "CGM (mg / dl)", "mg/dL")
    assert set(c.optional) == {"cbg", "blood_ketone", "dietary_intake", "insulin_sc", "insulin_iv",
                               "non_insulin_agents", "csii_bolus", "csii_basal"}
    assert shanghai.detect_columns(["Date", "CGM (mmol/L)"]).cgm_header_unit == "mmol/L"
    assert shanghai.detect_columns(["Date", "CGM"]).cgm_header_unit is None
    for bad in (["Date", "CBG"], ["Date", "CGM", "CGM 2"], ["Date", "Date time", "CGM"], ["CGM"]):
        with pytest.raises(shanghai.SchemaError):
            shanghai.detect_columns(bad)


def test_unit_resolution_never_guesses():
    mg, mmol = np.array([90.0, 140.0, 200.0]), np.array([5.0, 7.8, 11.1])
    assert shanghai.resolve_unit("mg/dL", mg, RULES)[0] == "mg/dL"
    assert shanghai.resolve_unit(None, mmol, RULES)[0] == "mmol/L"
    assert shanghai.resolve_unit(None, mg, RULES)[0] == "mg/dL"
    with pytest.raises(shanghai.SchemaError):
        shanghai.resolve_unit("mg/dL", mmol, RULES)  # header and values disagree
    with pytest.raises(shanghai.SchemaError):
        shanghai.resolve_unit("mmol/L", mg, RULES)
    with pytest.raises(shanghai.SchemaError):
        shanghai.resolve_unit(None, np.array([30.0, 31.0, 32.0]), RULES)  # ambiguous
    with pytest.raises(shanghai.SchemaError):
        shanghai.resolve_unit(None, np.array([np.nan]), RULES)


def test_mmol_values_are_converted_exactly():
    r = pd.DataFrame({"Date": pd.date_range("2021-01-01", periods=4, freq="15min"), "CGM": [5.0, 6.0, 7.0, 8.0]})
    s, a = shanghai.clean_cgm(r, shanghai.ColumnMap("Date", "CGM", None), SID, RULES)
    assert a["unit"] == "mmol/L" and a["unit_resolved_by"].startswith("value range")
    assert np.allclose(s["glucose"], np.array([5.0, 6.0, 7.0, 8.0]) * 18.016)


# ---------------------------------------------------------------- chronology, duplicates, implausible, text
def test_chronology_duplicates_implausible_and_text_values():
    r = regular(8)
    r = pd.concat([r, r.iloc[[2]],  # identical duplicate
                   raw([r["Date"].iloc[4]], [999.0]),  # conflicting duplicate (also implausible): drops the whole ts
                   raw(["2021-01-01 10:00"], ["HI"]),  # censored text value
                   pd.DataFrame({"Date": ["not a date"], "CGM (mg / dl)": [130.0]}),
                   raw(["2021-01-01 10:15"], [5.0])],  # implausible
                  ignore_index=True).sample(frac=1, random_state=1)  # shuffled
    s, a = shanghai.clean_cgm(r, COLS, SID, RULES)
    assert s["timestamp"].is_monotonic_increasing and a["n_out_of_order"] > 0
    assert a["n_identical_duplicates_removed"] == 1
    assert a["n_conflicting_duplicates_dropped"] == 2
    assert a["n_cgm_text_values"] == 1 and a["cgm_text_examples"] == ["HI"]
    assert a["n_unparseable_timestamps_with_cgm"] == 1
    assert a["n_implausible_dropped"] == 1
    assert len(s) == 7 and pd.Timestamp("2021-01-01 09:00") not in set(s["timestamp"])
    assert set(s["glucose"]) <= set(regular(8)["CGM (mg / dl)"])  # values only ever come from the input


# ---------------------------------------------------------------- extra readings
def _mins(*m):
    return np.array(m, dtype=float)


def test_extra_scan_between_cadence_readings_is_excluded_and_cadence_kept():
    assert shanghai.extra_reading_mask(_mins(0, 7, 15, 30), 15, 2, 5).tolist() == [True, False, True, True]
    # the case a greedy rule gets wrong: a scan 11 min after 08:00 must not displace the 08:15 reading
    assert shanghai.extra_reading_mask(_mins(0, 11, 15, 30), 15, 2, 5).tolist() == [True, False, True, True]
    assert shanghai.extra_reading_mask(_mins(0, 3, 9, 15), 15, 2, 5).tolist() == [True, False, False, True]


def test_readings_inside_a_real_gap_are_kept_but_near_duplicates_are_not():
    # 0, then a 50-min gap with a lone scan at 25: the scan is real data, not "between two cadence readings"
    assert shanghai.extra_reading_mask(_mins(0, 25, 50, 65), 15, 2, 5).tolist() == [True, True, True, True]
    assert shanghai.extra_reading_mask(_mins(0, 2, 40), 15, 2, 5).tolist() == [True, False, True]


# ---------------------------------------------------------------- gaps and windows
def test_long_gap_starts_new_segment_and_windows_never_cross_it():
    a = regular(12, "2021-01-01 08:00")
    b = regular(12, "2021-01-01 12:00", base=200)  # 60-min gap after 10:45
    s, aud = shanghai.clean_cgm(pd.concat([a, b]), COLS, SID, RULES)
    assert aud["n_segments"] == 2 and aud["n_gaps_over_max"] == 1 and aud["longest_gap_min"] == 75
    w = add_features(build_windows(s, [15, 30, 45, 60], [30, 60, 120], 5))
    seg_end = pd.Timestamp("2021-01-01 10:45")
    first_seg = w[w["segment"] == 0]
    assert first_seg.loc[first_seg["anchor_time"] > seg_end - pd.Timedelta(minutes=30), "y_30"].isna().all()
    assert w[w["segment"] == 1]["g_m15"].iloc[0] != w[w["segment"] == 1]["g_m15"].iloc[0]  # NaN: no input across gap
    assert len(w) == len(s)  # one row per recorded reading; nothing added


def test_short_gap_leaves_missing_values_missing_no_interpolation():
    r = regular(10).drop(index=4)  # one missing reading (30-min gap) stays inside the segment
    s, aud = shanghai.clean_cgm(r, COLS, SID, RULES)
    assert aud["n_segments"] == 1 and aud["missing_share"] == pytest.approx(0.1)
    w = add_features(build_windows(s, [15, 30, 45, 60], [30], 5))
    after = w[w["anchor_time"] == pd.Timestamp("2021-01-01 09:15")].iloc[0]
    assert np.isnan(after["g_m15"]) and not after["has_inputs"]
    observed = set(s["glucose"])
    for col in ["g0", "g_m15", "g_m30", "g_m45", "g_m60", "y_30"]:
        assert set(w[col].dropna()) <= observed


def test_target_matching_tolerance_and_inputs_strictly_in_the_past():
    t = pd.to_datetime(["2021-01-01 08:00", "2021-01-01 08:15", "2021-01-01 08:30", "2021-01-01 08:45",
                        "2021-01-01 09:00", "2021-01-01 09:02", "2021-01-01 09:16"])
    s = pd.DataFrame({"patient_id": "p", "session_id": "p_0", "timestamp": t,
                      "glucose": [100.0, 110, 120, 130, 140, 150, 160], "segment": 0})
    w = build_windows(s, [15, 30, 45, 60], [60], 5).set_index("anchor_time")
    assert w.loc[pd.Timestamp("2021-01-01 08:00"), "y_60"] == 140  # exact
    assert w.loc[pd.Timestamp("2021-01-01 08:15"), "y_60"] == 160  # 09:16 is +1 min off: accepted
    assert w.loc[pd.Timestamp("2021-01-01 08:15"), "offset_60"] == pytest.approx(1.0)
    assert np.isnan(w.loc[pd.Timestamp("2021-01-01 08:30"), "y_60"])  # nearest 09:16 is 14 min off
    f = add_features(w.reset_index()).set_index("anchor_time").loc[pd.Timestamp("2021-01-01 09:00")]
    assert f["g_m15"] == 130 and f["g_m60"] == 100
    assert f["delta_15"] == 10 and f["accel_15"] == 0 and f["has_inputs"]


# ---------------------------------------------------------------- split and leakage
def test_patient_split_is_deterministic_disjoint_and_keeps_sessions_together():
    ids = [f"{2000 + i}" for i in range(20)]
    a, b = patient_split(ids, 7, (0.6, 0.2, 0.2)), patient_split(list(reversed(ids)), 7, (0.6, 0.2, 0.2))
    assert a == b and [len(a[k]) for k in ("train", "validation", "test")] == [12, 4, 4]
    assert sorted(a["train"] + a["validation"] + a["test"]) == sorted(ids)
    sessions = pd.DataFrame({"patient_id": ["2003", "2003", "2003", "2011"], "session_id": ["2003_0", "2003_1", "2003_2", "2011_0"]})
    lab = assign(sessions["patient_id"], a)
    assert len(set(lab[:3])) == 1
    with pytest.raises(AssertionError):
        assert_disjoint({"train": ["1", "2"], "validation": ["2"], "test": ["3"]})
    with pytest.raises(ValueError):
        patient_split(["1", "2"], 7, (0.6, 0.2, 0.2))


# ---------------------------------------------------------------- models and metrics
def _frame(n, seed, pid="p"):
    rng = np.random.default_rng(seed)
    f = pd.DataFrame({k: rng.normal(0, 1, n) for k in FEATURES})
    f["g0"] = 120 + rng.normal(0, 20, n)
    f["y_30"] = f["g0"] + 5 * f["delta_15"] + rng.normal(0, 1, n)
    f["patient_id"] = pid
    return f


def test_persistence_and_training_only_preprocessing():
    tr, va = _frame(300, 1), _frame(200, 2)
    assert np.array_equal(models.persistence(va), va["g0"].to_numpy())
    sel = models.select([("alpha=1", models.make_ridge(1.0)), ("alpha=1000", models.make_ridge(1000.0))], tr, va, 30)
    assert sel["chosen"] == "alpha=1"
    scaler = sel["model"].named_steps["scale"]
    assert np.allclose(scaler.mean_, tr[FEATURES].mean().to_numpy())  # statistics from training rows only
    assert models.rmse(models.predict_delta(sel["model"], va) - va["y_30"]) < models.rmse(models.persistence(va) - va["y_30"])


def test_patient_bootstrap_is_deterministic_and_paired():
    f = pd.concat([_frame(50, i, pid=f"p{i}") for i in range(6)], ignore_index=True)
    e = {"persistence": f["y_30"].to_numpy() - f["g0"].to_numpy(), "same": f["y_30"].to_numpy() - f["g0"].to_numpy()}
    a, b = (models.patient_bootstrap(f, e, "persistence", 200, 3) for _ in range(2))
    assert a == b
    lo, hi = a["ci95"]["persistence"]["rmse"]
    assert lo <= models.rmse(e["persistence"]) <= hi
    assert a["difference_vs_persistence_ci95"]["same"]["rmse"] == [0.0, 0.0]


# ---------------------------------------------------------------- frozen-model compatibility
def test_frozen_model_compatibility_covers_every_feature_and_is_incompatible():
    c = compat.frozen_model_compatibility()
    assert set(c["by_feature"]) == set(FEATURE_NAMES) and c["production_model_features"] == 33
    assert c["verdict"] == "INCOMPATIBLE"
    assert {"carbs_30", "carbs_on_board", "steps_30", "hr_rel_30", "carb_sensitivity"} <= set(c["not_recorded_features"])
    assert len(c["not_recorded_features"]) == 10
    assert "NOT been inspected" in c["basis"]
    assert compat.recheck_with_inspected_columns(["Date", "CGM (mg / dl)", "Dietary intake"])["verdict"] == "INCOMPATIBLE"
    assert compat.recheck_with_inspected_columns(["carbs (g)", "steps", "heart rate (bpm)"])["verdict"] == "REVIEW_NEEDED"


# ---------------------------------------------------------------- end to end on a fixture zip (needs openpyxl)
def _fixture_zip(tmp_path: Path) -> Path:
    pytest.importorskip("openpyxl")
    rng = np.random.default_rng(0)
    path = tmp_path / "UNIT_TEST_FIXTURE.zip"
    with zipfile.ZipFile(path, "w") as zf:
        sessions = [(f"{3000 + i}", 0) for i in range(10)] + [("3004", 1)]
        for pid, period in sessions:
            t = pd.date_range(f"2021-0{1 + period}-01 00:00", periods=4 * 24 * 3, freq="15min")
            g = 130 + 40 * np.sin(np.arange(len(t)) / 12 + int(pid) % 7) + rng.normal(0, 5, len(t))
            df = pd.DataFrame({"Date": t, "CGM (mg / dl)": g.round(1), "CBG (mg / dl)": np.nan, "Dietary intake": ""})
            df.loc[100:106, "CGM (mg / dl)"] = np.nan  # a gap
            buf = io.BytesIO()
            df.to_excel(buf, index=False)
            zf.writestr(f"fixture/Shanghai_T2DM/{pid}_{period}_2021010{1 + period}.xlsx", buf.getvalue())
        zf.writestr("fixture/Shanghai_T1DM/9999_0_19990101.xlsx", buf.getvalue())
        summ = io.BytesIO()
        pd.DataFrame({"Patient Number": [f"{p}_{k}_2021010{1 + k}" for p, k in sessions]}).to_excel(summ, index=False)
        zf.writestr("fixture/Shanghai_T2DM_Summary.xlsx", summ.getvalue())
    return path


def test_end_to_end_fixture_run_has_no_split_leakage(tmp_path):
    from glucotwin.realdata import pipeline, report
    cfg = json.loads(json.dumps(CFG))
    cfg["bootstrap"]["n_boot"] = 50
    cfg["models"]["hgb_grid"] = cfg["models"]["hgb_grid"][:1]
    res = pipeline.run_experiment(_fixture_zip(tmp_path), tmp_path / "out", tmp_path / "art", cfg, "UNIT-TEST FIXTURE", None)
    assert res["counts"]["session_workbooks"] == 11 and res["counts"]["unique_patients_parsed"] == 10
    assert res["counts"]["patients_with_multiple_sessions"] == {"3004": 2}
    assert res["leakage_checks"] == {"patients_in_more_than_one_split": 0, "sessions_in_more_than_one_split": 0}
    sp = res["split"]
    assert not (set(sp["train"]) & set(sp["test"])) and not (set(sp["validation"]) & set(sp["test"]))
    for h, t in res["test_results"].items():
        assert set(t["per_patient"]["ridge"]) <= set(sp["test"])  # only test patients are scored
        assert res["selection"][h]["n_windows"]["test"] == t["n_windows"]
        assert set(t["metrics"]) == {"persistence", "ridge", "hgb"}  # identical targets for every model
    assert res["archive_audit"]["frozen_model_recheck"]["verdict"] == "INCOMPATIBLE"
    assert (tmp_path / "art" / "models.pkl").is_file() and (tmp_path / "out" / "results.json").is_file()
    assert all((tmp_path / "out" / p).is_file() for p in res["plots"])
    assert len(res["plots"]) == len(set(res["plots"]))
    md = report.render_report(res)
    assert "UNIT-TEST FIXTURE" in md and "REAL" not in md
    assert "NOT the GlucoTwin model" in md and "creativecommons.org/licenses/by/4.0" in md
    # split is fixed from parsed patient IDs before windowing (no window information involved)
    assert res["split"]["fixed_before_windowing"] is True
    assert {k: res["split"][k] for k in ("train", "validation", "test")} == patient_split(
        [f"{3000 + i}" for i in range(10)], cfg["seed"], tuple(cfg["split"]["fractions"]))
    # artifact provenance: relative paths, hashes that match the files, saved predictions reproduce the metrics
    art = res["artifact"]
    assert not str(art["models"]).startswith("/") and len(art["models_sha256"]) == 64
    assert hashlib.sha256((tmp_path / "art" / "models.pkl").read_bytes()).hexdigest() == art["models_sha256"]
    preds = pd.read_csv(tmp_path / "art" / "test_predictions.csv")
    for h, t in res["test_results"].items():
        g = preds[preds["horizon_min"] == int(h)]
        assert len(g) == t["n_windows"]
        for m in ("persistence", "ridge", "hgb"):
            assert models.rmse((g[m] - g["target"]).to_numpy()) == pytest.approx(t["metrics"][m]["rmse"], abs=2e-3)


def test_public_summary_is_aggregate_only(tmp_path):
    from glucotwin.realdata import pipeline, public
    cfg = json.loads(json.dumps(CFG))
    cfg["bootstrap"]["n_boot"] = 50
    cfg["models"]["hgb_grid"] = cfg["models"]["hgb_grid"][:1]
    res = pipeline.run_experiment(_fixture_zip(tmp_path), tmp_path / "out", tmp_path / "art", cfg, "UNIT-TEST FIXTURE", None)
    text = json.dumps(public.public_summary(res)) + public.public_markdown(public.public_summary(res))
    for pid in [f"{3000 + i}" for i in range(10)]:
        assert pid not in text  # no patient or session identifiers
    import re
    assert not re.search(r"20\d\d-\d\d-\d\d[ T]\d\d:", text)  # no recording timestamps
    assert "2021-0" not in text and "_0_2021" not in text  # no recording dates or session names
    assert "NOT the GlucoTwin model" in text and "CC BY 4.0" in text and "21600933.v5" in text


# ---------------------------------------------------------------- CLI guards
SPEC = importlib.util.spec_from_file_location("shanghai_experiment", REPO / "scripts" / "shanghai_experiment.py")
cli = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cli)


def test_cli_blocks_without_verified_archive_and_protects_production(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "ARCHIVE", tmp_path / "missing.zip")
    monkeypatch.setattr(cli, "PROVENANCE", tmp_path / "missing.json")
    assert cli.main(["run", "--out", str(tmp_path / "o"), "--artifacts", str(tmp_path / "a")]) == 2
    assert "BLOCKED" in capsys.readouterr().err
    fake = tmp_path / "fake.zip"
    fake.write_bytes(b"not the official archive")
    (tmp_path / "prov.json").write_text(json.dumps({"verified": {"md5": hashlib.md5(b"x").hexdigest()}}))
    monkeypatch.setattr(cli, "ARCHIVE", fake)
    monkeypatch.setattr(cli, "PROVENANCE", tmp_path / "prov.json")
    assert cli.main(["audit", "--out", str(tmp_path / "o")]) == 2
    assert "REJECTED" in capsys.readouterr().err
    assert cli.main(["run", "--artifacts", str(REPO / "artifacts")]) == 4
    assert cli.main(["run", "--out", str(REPO / "reports")]) == 4
    assert cli.main(["compat", "--out", str(tmp_path / "c")]) == 0
    assert json.loads((tmp_path / "c" / "frozen_model_compatibility.json").read_text())["verdict"] == "INCOMPATIBLE"
