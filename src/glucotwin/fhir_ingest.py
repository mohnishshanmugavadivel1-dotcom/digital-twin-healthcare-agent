"""Parse an incoming FHIR R4 Bundle into GlucoTwin observations (validation only; nothing is ingested).

``POST /api/fhir/Bundle`` returns the observations this module extracts plus every skipped entry and the
reason. A client then sends the accepted observations to ``POST /api/patients/{id}/observations`` if it wants
them in a twin. A structural parser for the fields GlucoTwin uses, not a full FHIR validator, not certified and
not a compliance claim. Codes handled (LOINC, http://loinc.org):

* 99504-3 Glucose [Mass/volume] in Interstitial fluid: the CGM code, also used by our export -> ``cgm``.
* 14749-6 Glucose [Moles/volume] in Serum or Plasma: a laboratory glucose code, not a CGM code. Accepted
  because some systems send it, converted from mmol/L (x 18.016) and returned with a warning.
* 8867-4 Heart rate -> ``heart_rate`` (beats/min).
* 4548-4 Hemoglobin A1c/Hemoglobin.total in Blood -> returned under ``labs`` (a record value, not a stream).
"""

from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Any

from glucotwin.config import CGM_VALID_RANGE, HR_VALID_RANGE
from glucotwin.contracts import FhirIngestLab, FhirIngestResult, FhirIngestSkip, Observation, ObservationKind
from glucotwin.fhir_export import LOINC, REPO_URL

MAX_ENTRIES = 5000
MMOL_TO_MG_DL = 18.016  # glucose, 1 mmol/L = 18.016 mg/dL
PATIENT_ID_SYSTEM = f"{REPO_URL}/patient-id"
_SYN = re.compile(r"^SYN-\d{4}$")
_ACCEPTED_STATUS = {"final", "amended", "corrected", "preliminary"}
_GLUCOSE_MG = {"mg/dL", "mg/dl"}
_GLUCOSE_MMOL = {"mmol/L", "mmol/l"}
_HR_UNITS = {"/min", "beats/min", "{beats}/min", "bpm"}
HBA1C_RANGE = (3.0, 20.0)  # %
LAB_GLUCOSE_WARNING = (
    "LOINC 14749-6 is serum/plasma glucose (a laboratory code), not interstitial CGM (99504-3). "
    "Converted to mg/dL and returned as a glucose reading; check that this is intended."
)


def _loinc_codes(obs: dict[str, Any]) -> list[str]:
    codings = (obs.get("code") or {}).get("coding") or []
    return [c.get("code") for c in codings if isinstance(c, dict) and c.get("system") == LOINC and c.get("code")]


def _patient_id_from_bundle(entries: list[dict[str, Any]]) -> str | None:
    for e in entries:
        res = (e or {}).get("resource") or {}
        if res.get("resourceType") != "Patient":
            continue
        for ident in res.get("identifier") or []:
            if ident.get("system") == PATIENT_ID_SYSTEM and _SYN.match(str(ident.get("value", ""))):
                return str(ident["value"])
    return None


def _timestamp(obs: dict[str, Any]) -> datetime | None:
    raw = obs.get("effectiveDateTime") or (obs.get("effectivePeriod") or {}).get("start")
    if not isinstance(raw, str):
        return None
    try:
        ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo is not None else None


def parse_bundle(bundle: dict[str, Any], patient_id: str | None = None) -> FhirIngestResult:
    """Extract observations from ``bundle``. ``patient_id`` overrides the Patient identifier in the bundle."""
    if not isinstance(bundle, dict) or bundle.get("resourceType") != "Bundle":
        raise ValueError("expected a FHIR Bundle (resourceType 'Bundle')")
    entries = bundle.get("entry") or []
    if not isinstance(entries, list):
        raise ValueError("Bundle.entry must be a list")
    if len(entries) > MAX_ENTRIES:
        raise ValueError(f"Bundle has {len(entries)} entries; the limit is {MAX_ENTRIES}")
    pid = patient_id or _patient_id_from_bundle(entries)
    if pid is None or not _SYN.match(pid):
        raise ValueError(
            "no synthetic patient ID: pass ?patient_id=SYN-#### or include a Patient with identifier system "
            f"{PATIENT_ID_SYSTEM}")

    observations: list[Observation] = []
    labs: list[FhirIngestLab] = []
    skipped: list[FhirIngestSkip] = []
    warnings: set[str] = set()

    def skip(i: int, rtype: str | None, reason: str) -> None:
        skipped.append(FhirIngestSkip(index=i, resource_type=rtype, reason=reason))

    for i, e in enumerate(entries):
        res = (e or {}).get("resource") if isinstance(e, dict) else None
        rtype = res.get("resourceType") if isinstance(res, dict) else None
        if rtype != "Observation":
            if rtype not in ("Patient", "Condition", "MedicationStatement", "RiskAssessment"):
                skip(i, rtype, "not an Observation")
            continue
        if res.get("status") not in _ACCEPTED_STATUS:
            skip(i, rtype, f"status '{res.get('status')}' is not final/amended/corrected/preliminary")
            continue
        codes = _loinc_codes(res)
        code = next((c for c in ("99504-3", "14749-6", "8867-4", "4548-4") if c in codes), None)
        if code is None:
            skip(i, rtype, f"no supported LOINC code (found {codes or 'none'})")
            continue
        ts = _timestamp(res)
        if ts is None:
            skip(i, rtype, "effectiveDateTime missing, unparseable or without a time-zone offset")
            continue
        q = res.get("valueQuantity") or {}
        value, unit = q.get("value"), q.get("code") or q.get("unit")
        if not isinstance(value, int | float) or isinstance(value, bool) or not math.isfinite(value):
            skip(i, rtype, "valueQuantity.value missing or not a number")
            continue
        value = float(value)

        if code == "4548-4":
            if unit != "%":
                skip(i, rtype, f"HbA1c unit '{unit}' is not '%'")
            elif not HBA1C_RANGE[0] <= value <= HBA1C_RANGE[1]:
                skip(i, rtype, f"HbA1c {value} outside {HBA1C_RANGE}")
            else:
                labs.append(FhirIngestLab(loinc=code, name="HbA1c", value=value, unit="%", effective=ts))
            continue

        if code in ("99504-3", "14749-6"):
            if unit in _GLUCOSE_MMOL:
                value = round(value * MMOL_TO_MG_DL, 1)
            elif unit not in _GLUCOSE_MG:
                skip(i, rtype, f"glucose unit '{unit}' is not mg/dL or mmol/L")
                continue
            kind, lo_hi = ObservationKind.cgm, CGM_VALID_RANGE
            if code == "14749-6":
                warnings.add(LAB_GLUCOSE_WARNING)
            unit_out = "mg/dL"
        else:  # 8867-4
            if unit not in _HR_UNITS:
                skip(i, rtype, f"heart-rate unit '{unit}' is not beats/min")
                continue
            kind, lo_hi, unit_out = ObservationKind.heart_rate, HR_VALID_RANGE, "bpm"
        if not lo_hi[0] <= value <= lo_hi[1]:
            skip(i, rtype, f"{kind.value} value {value} outside [{lo_hi[0]:g}, {lo_hi[1]:g}]")
            continue
        observations.append(Observation(patient_id=pid, timestamp=ts, kind=kind, value=value, unit=unit_out,
                                        source=f"fhir:{code}"))

    observations.sort(key=lambda o: (o.timestamp, o.kind.value))
    counts: dict[str, int] = {}
    for o in observations:
        counts[o.kind.value] = counts.get(o.kind.value, 0) + 1
    if labs:
        counts["hba1c"] = len(labs)
    return FhirIngestResult(patient_id=pid, observations=observations, labs=labs, skipped=skipped,
                            warnings=sorted(warnings), counts=counts, entries=len(entries))
