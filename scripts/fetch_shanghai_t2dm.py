"""B-05: fetch and verify the ShanghaiT1DM/ShanghaiT2DM archive (provenance only; no schema parsing).

Source metadata, verified 2026-10-21 via https://api.figshare.com/v2/articles/21600933 and
https://api.figshare.com/v2/collections/6310860/articles (the collection contains this one article):

* article 21600933 "diabetes_datasets.zip", version 5, DOI 10.6084/m9.figshare.21600933.v5
* authors Qinpei Zhao, Jinhao Zhu, Congrong Wang, Weixiong Rao; licence CC BY 4.0
* file id 42966622, 3,738,354 bytes, md5 4bfb61cfa506b48155fd9e841ee48e21 (supplied == computed)
* descriptor paper: Zhao et al., Scientific Data 10, 2023, https://doi.org/10.1038/s41597-023-01940-7

The archive and everything extracted from it stay under ``data/real/`` (gitignored). This script
only downloads (or accepts a manually downloaded copy via ``--archive``), verifies size and md5,
records provenance and lists archive member NAMES. It deliberately does not parse spreadsheets:
exact column headers and units are not published, and guessing them is out of scope until the
files are inspected.

    .venv/bin/python scripts/fetch_shanghai_t2dm.py                       # download (needs figshare access)
    .venv/bin/python scripts/fetch_shanghai_t2dm.py --archive ~/Downloads/diabetes_datasets.zip
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import urllib.request
import zipfile
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SOURCE = {
    "article_id": 21600933,
    "version": 5,
    "title": "diabetes_datasets.zip",
    "doi": "10.6084/m9.figshare.21600933.v5",
    "landing_page": "https://figshare.com/articles/dataset/diabetes_datasets_zip/21600933",
    "collection": "https://figshare.com/collections/Diabetes_Datasets_ShanghaiT1DM_and_ShanghaiT2DM/6310860",
    "file_id": 42966622,
    "download_url": "https://ndownloader.figshare.com/files/42966622",
    "size_bytes": 3738354,
    "md5": "4bfb61cfa506b48155fd9e841ee48e21",
    "license": "CC BY 4.0",
    "license_url": "https://creativecommons.org/licenses/by/4.0/",
    "citation": "Zhao, Qinpei; Zhu, Jinhao; Wang, Congrong; Rao, Weixiong (2022). diabetes_datasets.zip. figshare. "
                "Dataset. https://doi.org/10.6084/m9.figshare.21600933.v5",
    "descriptor_paper": "https://doi.org/10.1038/s41597-023-01940-7",
    "metadata_verified_on": "2026-10-21",
}
EXPECTED_TOP_LEVEL = ("Shanghai_T1DM", "Shanghai_T2DM")  # per the figshare description (folder names)


class VerificationError(RuntimeError):
    pass


def digests(path: Path) -> tuple[str, str, int]:
    md5, sha = hashlib.md5(), hashlib.sha256()  # md5 only because figshare publishes it; sha256 recorded too
    n = 0
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            md5.update(chunk)
            sha.update(chunk)
            n += len(chunk)
    return md5.hexdigest(), sha.hexdigest(), n


def verify(path: Path, expected_md5: str, expected_size: int) -> dict:
    md5, sha, n = digests(path)
    if n != expected_size:
        raise VerificationError(f"size mismatch: got {n} bytes, expected {expected_size}")
    if md5 != expected_md5:
        raise VerificationError(f"md5 mismatch: got {md5}, expected {expected_md5}")
    if not zipfile.is_zipfile(path):
        raise VerificationError("not a zip archive")
    try:
        with zipfile.ZipFile(path) as zf:
            bad = zf.testzip()
            names = sorted(zf.namelist())
    except (zipfile.BadZipFile, zipfile.LargeZipFile, EOFError, OSError, ValueError) as e:
        raise VerificationError(f"unreadable zip archive: {e}") from None
    if bad is not None:
        raise VerificationError(f"corrupt member {bad}")
    unsafe = [m for m in names if m.startswith("/") or ".." in Path(m).parts]
    if unsafe:
        raise VerificationError(f"unsafe member paths: {unsafe[:3]}")
    return {"md5": md5, "sha256": sha, "size_bytes": n, "members": names}


def summarize_members(names: list[str]) -> dict:
    """Counts only (names stay local). No patient-level content is read."""
    files = [m for m in names if not m.endswith("/")]
    top = sorted({Path(m).parts[0] for m in files if Path(m).parts})
    by_top: dict[str, int] = {}
    for m in files:
        parts = Path(m).parts
        key = "/".join(parts[:2]) if len(parts) > 2 else parts[0]
        by_top[key] = by_top.get(key, 0) + 1
    return {"n_files": len(files), "top_level": top, "files_per_folder": dict(sorted(by_top.items())),
            "expected_folders_present": {f: any(f in m for m in files) for f in EXPECTED_TOP_LEVEL},
            "extensions": sorted({Path(m).suffix.lower() for m in files})}


def _write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    tmp.write_text(text)
    os.replace(tmp, path)


def _remove(*paths: Path) -> None:
    for p in paths:
        p.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    """Exit codes: 0 verified (or already verified), 2 source unavailable (network / missing file),
    3 verification failed. The archive only ever appears under its final name after it verified; on any
    failure the temporary download is removed and a previously verified archive is left untouched."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", type=Path, help="manually downloaded diabetes_datasets.zip")
    ap.add_argument("--dest", type=Path, default=REPO / "data/real/shanghai")
    ap.add_argument("--force", action="store_true", help="re-acquire even if a verified archive is present")
    ap.add_argument("--expected-md5", default=SOURCE["md5"], help=argparse.SUPPRESS)  # tests only
    ap.add_argument("--expected-size", type=int, default=SOURCE["size_bytes"], help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    args.dest.mkdir(parents=True, exist_ok=True)
    target = args.dest / SOURCE["title"]
    prov_path, members_path = args.dest / "provenance.json", args.dest / "members.txt"

    # An existing archive is trusted only if it verifies now; otherwise it and any stale provenance are removed.
    if target.exists():
        try:
            verify(target, args.expected_md5, args.expected_size)
            if not args.force:
                print(f"already present and verified: {target}")
                return 0
        except (VerificationError, OSError) as e:
            print(f"removing unverified existing archive ({e})", file=sys.stderr)
            _remove(target, prov_path, members_path)
    elif prov_path.exists() or members_path.exists():
        print("removing provenance files that have no archive", file=sys.stderr)
        _remove(prov_path, members_path)

    part = args.dest / f".{SOURCE['title']}.part-{os.getpid()}"
    try:
        if args.archive:
            if not args.archive.is_file():
                print(f"BLOCKED: archive not found: {args.archive}", file=sys.stderr)
                return 2
            shutil.copyfile(args.archive, part)
            how = "manual copy"
        else:
            try:
                with urllib.request.urlopen(SOURCE["download_url"], timeout=60) as r, open(part, "wb") as fh:
                    shutil.copyfileobj(r, fh)
            except OSError as e:
                print(f"BLOCKED: could not download {SOURCE['download_url']}: {e}\n"
                      "Download it manually from the landing page and rerun with --archive PATH.", file=sys.stderr)
                return 2
            how = "download"
        try:
            v = verify(part, args.expected_md5, args.expected_size)
        except VerificationError as e:
            print(f"REJECTED: {e}", file=sys.stderr)
            return 3
        os.replace(part, target)  # atomic: the final name only ever holds a verified archive
    finally:
        _remove(part)
    prov = {"source": SOURCE, "retrieved_at": datetime.now(UTC).isoformat(), "retrieval": how,
            "verified": {"md5": v["md5"], "sha256": v["sha256"], "size_bytes": v["size_bytes"]},
            "members_summary": summarize_members(v["members"]),
            "note": "Raw archive and extracted files stay in data/real/ (gitignored). Schema not yet inspected. "
                    "A verified checksum is not schema compatibility and not external validation."}
    _write_atomic(members_path, "\n".join(v["members"]) + "\n")
    _write_atomic(prov_path, json.dumps(prov, indent=2) + "\n")
    print(f"verified {target} (md5 {v['md5']}); provenance written to {prov_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
