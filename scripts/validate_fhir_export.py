"""Validate GlucoTwin's FHIR export against the FHIR R4 (4.0.1) resource model classes.

Uses the third-party ``fhir.resources`` 6.4.0 package (R4 4.0.1 default; it needs pydantic v1, so it runs in a
separate environment and is NOT a project dependency). It checks structure, cardinality and datatypes; it
does NOT check terminology bindings or national profiles. Codes are checked separately in tests/test_fhir_export.py.

    python -m venv /tmp/fhirval && /tmp/fhirval/bin/pip install "fhir.resources==6.4.0" "pydantic<2"
    /tmp/fhirval/bin/python scripts/validate_fhir_export.py path/to/bundle.json [...]
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import fhir.resources
from fhir.resources.bundle import Bundle


def main(paths: list[str]) -> int:
    print(f"fhir.resources {fhir.resources.__version__}; FHIR {fhir.resources.__fhir_version__}")
    failed = 0
    for p in paths:
        data = json.loads(Path(p).read_text())
        try:
            bundle = Bundle.parse_obj(data)  # validates every contained resource against its R4 model
        except Exception as exc:  # pydantic ValidationError lists every violation
            failed += 1
            print(f"FAIL {p}\n{exc}")
            continue
        kinds = Counter(e.resource.resource_type for e in bundle.entry or [])
        print(f"OK   {p}: {sum(kinds.values())} resources {dict(sorted(kinds.items()))}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
