"""Can the FROZEN production model (synthetic-trained bundle) legitimately consume ShanghaiT2DM sessions?

Checked feature by feature against the DOCUMENTED schema (Zhao et al. 2023, "Data Records") before the data are
available, and re-checked against the real headers by ``recheck_with_inspected_columns`` once the archive is audited.
The production model consumes all 33 ``glucotwin.features.FEATURE_NAMES`` (trajectory and event models alike).
"""

from __future__ import annotations

from glucotwin.config import CGM_INTERVAL_MIN
from glucotwin.features import FEATURE_GROUPS, FEATURE_NAMES

DOC_SOURCE = "Zhao et al., Scientific Data 10 (2023), Data Records + Methods; https://doi.org/10.1038/s41597-023-01940-7"

# status: available | out_of_distribution | needs_inspection | not_recorded
_GROUP_ASSESSMENT = {
    "glucose_level": ("out_of_distribution",
                      f"Computable from CGM, but the production pipeline assumes a {CGM_INTERVAL_MIN}-min grid "
                      "(labels.to_grid) and was trained on 5-min synthetic CGM. ShanghaiT2DM CGM is documented as "
                      "every 15 min (FreeStyle Libre H), so windowed statistics use about 4-5 instead of 12-13 "
                      "readings per hour."),
    "glucose_trend": ("out_of_distribution",
                      "Computable at 15/30/60 min from 15-min readings, but the production code interpolates the "
                      "5-min grid (limit 3 steps) and shifts by grid steps; inputs would differ in kind from training."),
    "history_24h": ("out_of_distribution", "Computable from CGM; same sampling-density caveat."),
    "time_of_day": ("available", "Computable from the recorded local wall-clock timestamps."),
    "meals": ("not_recorded",
              "Requires carbohydrate GRAMS per logged meal. The dataset documents 'self-reported time and weighed "
              "food intake', i.e. foods and weights, not carbohydrate grams. Deriving grams would need a "
              "food-composition table (an estimate, not a recording). Leaving them empty makes the production "
              "pipeline compute carbs = 0 / no recent meal, which asserts that the patient did not eat."),
    "activity": ("not_recorded",
                 "Requires step counts and heart rate. Neither is documented for ShanghaiT2DM. The production "
                 "pipeline would emit steps = 0 (asserting inactivity) and a missing heart-rate feature."),
    "record": ("needs_inspection",
               "Age, BMI, HbA1c, fasting plasma glucose, diabetes duration and eGFR are documented in the summary "
               "sheet (headers and units unpublished; fasting glucose may need mmol/L conversion). The 4 binary "
               "medication-class features need a manual mapping from recorded drug names, which is unverified."),
}


def frozen_model_compatibility() -> dict:
    by_feature = {}
    for gid, _label, _rep, feats in FEATURE_GROUPS:
        status, why = _GROUP_ASSESSMENT[gid]
        for f in feats:
            by_feature[f] = {"group": gid, "status": status, "reason": why}
    missing = sorted(set(FEATURE_NAMES) - set(by_feature))
    if missing:
        raise RuntimeError(f"features without an assessment: {missing}")
    counts: dict[str, int] = {}
    for v in by_feature.values():
        counts[v["status"]] = counts.get(v["status"], 0) + 1
    not_recorded = sorted(f for f, v in by_feature.items() if v["status"] == "not_recorded")
    return {
        "basis": "documented schema only; the archive had NOT been inspected locally when this was generated",
        "documentation": DOC_SOURCE,
        "production_model_features": len(FEATURE_NAMES),
        "status_counts": dict(sorted(counts.items())),
        "not_recorded_features": not_recorded,
        "by_feature": by_feature,
        "verdict": "INCOMPATIBLE",
        "decision": (f"No frozen-model evaluation on ShanghaiT2DM: {len(not_recorded)} of {len(FEATURE_NAMES)} "
                     "production inputs (meal carbohydrate grams; steps; heart rate) have no recorded source, and "
                     "running the model would require fabricating them (0 g carbs, 0 steps). In addition the CGM "
                     "sampling (15 min) differs from the training data (5 min). Persistence and a separately "
                     "trained CGM-only real-data model are evaluated instead."),
        "would_change_if": ("the inspected workbooks contained recorded carbohydrate grams AND step counts AND "
                            "heart rate (rechecked automatically against the real headers by the audit stage)"),
    }


def recheck_with_inspected_columns(all_headers: list[str]) -> dict:
    """Re-run the decisive part of the check against the headers actually found in the workbooks."""
    h = " | ".join(all_headers).lower()
    found = {
        "carbohydrate_grams": any(t in h for t in ("carb", "碳水")),
        "steps": any(t in h for t in ("step", "步")),
        "heart_rate": any(t in h for t in ("heart", "hr ", "心率")),
    }
    return {"basis": "headers of the inspected workbooks", "decisive_inputs_found": found,
            "verdict": "INCOMPATIBLE" if not all(found.values()) else "REVIEW_NEEDED",
            "note": "REVIEW_NEEDED would mean the documented-schema verdict must be revisited by hand; "
                    "nothing is run automatically."}
