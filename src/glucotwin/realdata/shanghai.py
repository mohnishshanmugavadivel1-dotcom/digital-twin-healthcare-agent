"""ShanghaiT2DM ingestion: read session workbooks straight from the verified zip (never extracted or modified).

Documented schema (Zhao et al., Sci Data 10, 2023, "Data Records"; NOT yet inspected locally when this was written):
one Excel table per CGM period, named ``<patientID>_<period>_<YYYYMMDD>``, with fields Date, CGM (every 15 min),
CBG, Blood ketone, Dietary intake, Insulin dose-s.c., Insulin dose-i.v., Non-insulin hypoglycemic agents,
CSII-bolus insulin, CSII-basal insulin; plus one summary sheet with one row per table. Exact header strings and
CGM units are NOT published, so they are detected here and every ambiguity is an error, not a guess.

Cleaning rules (pre-registered in experiments/shanghai_t2dm/config.json; every removal is counted):
* rows without a parseable timestamp or a numeric CGM value are not CGM readings (event-only rows, "LO"/"HI" text);
* identical duplicate (timestamp, value) pairs collapse to one; conflicting duplicates are all dropped;
* values outside the plausibility range (mg/dL) are dropped;
* a reading lying strictly between two readings one nominal interval apart (15 +- ``cadence_tolerance_min``) is an
  extra (e.g. manual scan) reading and is excluded from the regular series, as is any reading closer than
  ``min_spacing_min`` to the previous kept one (counted, never silently dropped);
* a gap longer than ``gap_max_min`` starts a new segment. Nothing is interpolated, ever.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import PurePosixPath

import numpy as np
import pandas as pd

MMOL_TO_MG_DL = 18.016  # glucose molar mass 180.16 g/mol
NAME_RE = re.compile(r"^(?P<patient>\d+)_(?P<period>\d+)_(?P<date>\d{8})$")
EXCEL_EXT = {".xlsx", ".xls"}
OPTIONAL_FIELDS = {  # documented field -> header tokens (normalised: lower case, no spaces)
    "cbg": ("cbg",),
    "blood_ketone": ("ketone",),
    "dietary_intake": ("dietary", "diet"),
    "insulin_sc": ("s.c", "insulindose-s.c"),
    "insulin_iv": ("i.v", "insulindose-i.v"),
    "non_insulin_agents": ("non-insulin", "hypoglycemicagents"),
    "csii_bolus": ("bolus",),
    "csii_basal": ("basal",),
}


class SchemaError(ValueError):
    """The workbook does not match the documented schema closely enough to parse without guessing."""


@dataclass(frozen=True)
class SessionId:
    patient_id: str
    period: int
    start_date: str
    member: str

    @property
    def session_id(self) -> str:
        return f"{self.patient_id}_{self.period}_{self.start_date}"


@dataclass
class ColumnMap:
    date: str
    cgm: str
    cgm_header_unit: str | None
    optional: dict[str, str] = field(default_factory=dict)


def _norm(h: object) -> str:
    return re.sub(r"\s+", "", str(h)).lower()


def parse_member_name(member: str) -> SessionId:
    p = PurePosixPath(member)
    m = NAME_RE.match(p.stem)
    if not m:
        raise SchemaError(f"unexpected session file name: {p.name}")
    return SessionId(m["patient"], int(m["period"]), m["date"], member)


def list_members(names: list[str], folder: str = "Shanghai_T2DM") -> tuple[list[str], str | None, list[str]]:
    """(session workbooks in ``folder``, the matching summary workbook or None, ignored names)."""
    sessions, summary, ignored = [], None, []
    for n in sorted(names):
        p = PurePosixPath(n)
        if n.endswith("/") or "__MACOSX" in p.parts or p.name.startswith("._") or p.suffix.lower() not in EXCEL_EXT:
            ignored.append(n)
        elif "summary" in p.stem.lower():
            if p.stem.lower().startswith(f"{folder.lower()}_summary"):
                if summary is not None:
                    raise SchemaError(f"two summary workbooks for {folder}: {summary}, {n}")
                summary = n
            else:
                ignored.append(n)
        elif folder in p.parts[:-1]:
            sessions.append(n)
        else:
            ignored.append(n)
    return sessions, summary, ignored


def read_workbook(zf: zipfile.ZipFile, member: str) -> pd.DataFrame:
    data = zf.read(member)
    engine = "openpyxl" if member.lower().endswith(".xlsx") else "xlrd"
    sheets = pd.read_excel(io.BytesIO(data), sheet_name=None, engine=engine, dtype=object)
    non_empty = {k: v for k, v in sheets.items() if not v.dropna(how="all").empty}
    if len(non_empty) != 1:
        raise SchemaError(f"{member}: expected exactly one non-empty sheet, found {list(non_empty)}")
    return next(iter(non_empty.values()))


def detect_columns(columns: list[object]) -> ColumnMap:
    norm = {_norm(c): str(c) for c in columns}
    dates = [orig for n, orig in norm.items() if n.startswith("date") or n in ("time", "datetime", "日期", "时间")]
    cgms = [orig for n, orig in norm.items() if n.startswith("cgm")]
    if len(dates) != 1:
        raise SchemaError(f"need exactly one Date column, found {dates} in {list(map(str, columns))}")
    if len(cgms) != 1:
        raise SchemaError(f"need exactly one CGM column, found {cgms} in {list(map(str, columns))}")
    n = _norm(cgms[0])
    unit = "mg/dL" if "mg/dl" in n else "mmol/L" if "mmol" in n else None
    optional: dict[str, str] = {}
    for key, tokens in OPTIONAL_FIELDS.items():
        hits = [orig for nn, orig in norm.items() if orig not in (dates[0], cgms[0]) and any(t in nn for t in tokens)]
        if key == "insulin_sc":
            hits = [h for h in hits if "csii" not in _norm(h)]
        if len(hits) == 1:
            optional[key] = hits[0]
    return ColumnMap(dates[0], cgms[0], unit, optional)


def resolve_unit(header_unit: str | None, values: np.ndarray, rules: dict) -> tuple[str, str]:
    """(unit, how). Header unit wins only if the values agree with it; disagreement or ambiguity is an error."""
    v = values[np.isfinite(values)]
    if v.size == 0:
        raise SchemaError("no numeric CGM values")
    med = float(np.median(v))
    looks_mmol = rules["mmol_median_range"][0] <= med <= rules["mmol_median_range"][1]
    looks_mg = rules["mg_median_range"][0] <= med <= rules["mg_median_range"][1]
    if header_unit == "mg/dL":
        if not looks_mg:
            raise SchemaError(f"header says mg/dL but median CGM is {med:.1f}")
        return "mg/dL", "header (values agree)"
    if header_unit == "mmol/L":
        if not looks_mmol:
            raise SchemaError(f"header says mmol/L but median CGM is {med:.1f}")
        return "mmol/L", "header (values agree)"
    if looks_mmol and not looks_mg:
        return "mmol/L", f"value range (median {med:.1f})"
    if looks_mg and not looks_mmol:
        return "mg/dL", f"value range (median {med:.1f})"
    raise SchemaError(f"cannot determine CGM unit (no unit in header, median {med:.1f})")


def clean_cgm(raw: pd.DataFrame, cols: ColumnMap, sid: SessionId, rules: dict) -> tuple[pd.DataFrame, dict]:
    """Regular CGM series with segment numbers, plus an audit record. Raw values are never altered except for the
    documented unit conversion; nothing is interpolated or invented."""
    a: dict = {"session_id": sid.session_id, "patient_id": sid.patient_id, "period": sid.period,
               "member": sid.member, "columns": {"date": cols.date, "cgm": cols.cgm}, "n_rows": int(len(raw))}
    ts = pd.to_datetime(raw[cols.date], errors="coerce", format="mixed")
    cgm_raw = raw[cols.cgm]
    num = pd.to_numeric(cgm_raw, errors="coerce")
    text = cgm_raw.notna() & num.isna()
    a["n_cgm_text_values"] = int(text.sum())  # e.g. "LO"/"HI": censored readings, not usable as numbers
    a["cgm_text_examples"] = sorted({str(x) for x in cgm_raw[text]})[:5]
    a["n_unparseable_timestamps_with_cgm"] = int((ts.isna() & num.notna()).sum())
    keep = ts.notna() & num.notna()
    a["n_rows_without_cgm"] = int((ts.notna() & cgm_raw.isna()).sum())
    unit, how = resolve_unit(cols.cgm_header_unit, num[keep].to_numpy(dtype=float), rules)
    a["unit"], a["unit_resolved_by"] = unit, how
    df = pd.DataFrame({"timestamp": ts[keep].to_numpy(), "glucose": num[keep].to_numpy(dtype=float)})
    if unit == "mmol/L":
        df["glucose"] = df["glucose"] * MMOL_TO_MG_DL
    a["n_cgm_numeric"] = int(len(df))
    order = df["timestamp"].to_numpy()
    a["n_out_of_order"] = int((np.diff(order.astype("datetime64[ns]").astype(np.int64)) < 0).sum()) if len(df) > 1 else 0
    df = df.sort_values("timestamp", kind="stable").reset_index(drop=True)

    dup_ts = df["timestamp"].duplicated(keep=False)
    conflict_ts = df[dup_ts].groupby("timestamp")["glucose"].nunique()
    conflict_ts = set(conflict_ts[conflict_ts > 1].index)
    a["n_identical_duplicates_removed"] = int(df[dup_ts & ~df["timestamp"].isin(conflict_ts)]
                                              .duplicated(["timestamp", "glucose"]).sum())
    a["n_conflicting_duplicates_dropped"] = int(df["timestamp"].isin(conflict_ts).sum())
    df = df[~df["timestamp"].isin(conflict_ts)].drop_duplicates(["timestamp", "glucose"]).reset_index(drop=True)

    lo, hi = rules["plausible_mg_dl"]
    bad = (df["glucose"] < lo) | (df["glucose"] > hi)
    a["n_implausible_dropped"] = int(bad.sum())
    df = df[~bad].reset_index(drop=True)
    a["n_at_sensor_limits"] = int(df["glucose"].isin(rules.get("sensor_limit_values_mg_dl", [])).sum())

    t = df["timestamp"].to_numpy().astype("datetime64[ns]").astype(np.int64) / 6e10
    kept = extra_reading_mask(t, rules["nominal_interval_min"], rules["cadence_tolerance_min"],
                              rules["min_spacing_min"])
    a["n_extra_readings_excluded"] = int((~kept).sum())
    df = df[kept].reset_index(drop=True)
    t = t[kept]

    gaps = np.diff(t) if len(t) > 1 else np.array([])
    seg = np.concatenate([[0], np.cumsum(gaps > rules["gap_max_min"])]) if len(t) else np.array([], dtype=int)
    df["segment"] = seg.astype(int)
    df.insert(0, "session_id", sid.session_id)
    df.insert(0, "patient_id", sid.patient_id)
    nominal = rules["nominal_interval_min"]
    span = float(t[-1] - t[0]) if len(t) > 1 else 0.0
    expected = int(span // nominal) + 1 if len(t) else 0
    a.update({
        "n_regular_readings": int(len(df)),
        "start": str(df["timestamp"].iloc[0]) if len(df) else None,
        "end": str(df["timestamp"].iloc[-1]) if len(df) else None,
        "duration_days": round(span / 1440, 3),
        "expected_readings_at_nominal_interval": expected,
        "missing_share": round(1 - len(df) / expected, 4) if expected else None,
        "median_interval_min": float(np.median(gaps)) if gaps.size else None,
        "share_intervals_nominal_pm2": round(float(np.mean(np.abs(gaps - nominal) <= 2)), 4) if gaps.size else None,
        "n_gaps_over_max": int((gaps > rules["gap_max_min"]).sum()),
        "longest_gap_min": float(gaps.max()) if gaps.size else None,
        "n_segments": int(seg.max() + 1) if len(seg) else 0,
    })
    return df, a


def extra_reading_mask(t: np.ndarray, nominal: float, cadence_tol: float, min_spacing: float) -> np.ndarray:
    """True = keep. A reading is an EXTRA (e.g. a manual sensor scan between the automatic 15-min readings) if it lies
    strictly between two readings that are one nominal interval apart (nominal +- cadence_tol). Afterwards any reading
    closer than ``min_spacing`` to the previous kept one is also treated as extra. ``t`` in minutes, sorted."""
    keep = np.ones(len(t), dtype=bool)
    lo, hi = nominal - cadence_tol, nominal + cadence_tol
    for i in range(len(t)):
        if not keep[i]:
            continue
        j = i + 1
        while j < len(t) and t[j] - t[i] < lo:
            j += 1
        if j < len(t) and t[j] - t[i] <= hi and j > i + 1:
            keep[i + 1:j] = False  # everything between two cadence readings
    last = -np.inf
    for i in range(len(t)):
        if keep[i]:
            if t[i] - last < min_spacing:
                keep[i] = False
            else:
                last = t[i]
    return keep


def optional_field_counts(raw: pd.DataFrame, cols: ColumnMap) -> dict:
    """Non-empty counts of the documented optional fields. Inspected only; NOT model inputs in protocol v1."""
    out = {}
    for key, col in cols.optional.items():
        s = raw[col]
        out[key] = {"column": col, "non_empty": int(s.dropna().astype(str).str.strip().ne("").sum()),
                    "numeric": int(pd.to_numeric(s, errors="coerce").notna().sum())}
    return out


def summary_overview(df: pd.DataFrame, session_ids: list[str]) -> dict:
    """Columns and row matching of the summary sheet (inspected only; not used as model inputs in protocol v1)."""
    first = df.columns[0]
    ids = df[first].dropna().astype(str).str.strip()
    return {"n_rows": int(len(df)), "columns": [str(c) for c in df.columns], "id_column": str(first),
            "rows_matching_a_session_file": int(ids.isin(session_ids).sum()),
            "sessions_without_summary_row": sorted(set(session_ids) - set(ids))[:20]}


def audit_dict(x) -> dict:
    return asdict(x)
