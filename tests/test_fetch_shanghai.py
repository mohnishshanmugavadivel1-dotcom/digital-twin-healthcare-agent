"""B-05: archive verification for scripts/fetch_shanghai_t2dm.py.

Uses a tiny SYNTHETIC zip built in a temp dir (placeholder text, no data and no real patient files)
to exercise the size/md5/zip checks. Nothing here touches the network or the real archive.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import zipfile
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "fetch_shanghai_t2dm", Path(__file__).resolve().parents[1] / "scripts" / "fetch_shanghai_t2dm.py")
fetch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fetch)


def _fixture_zip(tmp_path: Path, members: dict[str, str]) -> Path:
    p = tmp_path / "synthetic_fixture.zip"
    with zipfile.ZipFile(p, "w") as zf:
        for name, text in members.items():
            zf.writestr(name, text)
    return p


MEMBERS = {"Shanghai_T1DM/placeholder_a.txt": "synthetic placeholder",
           "Shanghai_T2DM/placeholder_b.txt": "synthetic placeholder",
           "Shanghai_T2DM_Summary.txt": "synthetic placeholder"}


def test_verified_source_metadata_is_pinned():
    s = fetch.SOURCE
    assert s["article_id"] == 21600933 and s["version"] == 5 and s["license"] == "CC BY 4.0"
    assert s["md5"] == "4bfb61cfa506b48155fd9e841ee48e21" and s["size_bytes"] == 3738354


def test_accepts_matching_archive_and_writes_provenance(tmp_path):
    z = _fixture_zip(tmp_path, MEMBERS)
    md5 = hashlib.md5(z.read_bytes()).hexdigest()
    dest = tmp_path / "out"
    rc = fetch.main(["--archive", str(z), "--dest", str(dest), "--expected-md5", md5,
                     "--expected-size", str(z.stat().st_size)])
    assert rc == 0
    prov = json.loads((dest / "provenance.json").read_text())
    assert prov["verified"]["md5"] == md5 and prov["retrieval"] == "manual copy"
    assert prov["members_summary"]["expected_folders_present"] == {"Shanghai_T1DM": True, "Shanghai_T2DM": True}
    assert prov["source"]["license"] == "CC BY 4.0"


def test_rejects_wrong_checksum_and_removes_the_copy(tmp_path):
    z = _fixture_zip(tmp_path, MEMBERS)
    dest = tmp_path / "out"
    rc = fetch.main(["--archive", str(z), "--dest", str(dest), "--expected-size", str(z.stat().st_size)])
    assert rc == 3  # md5 of the fixture != the real archive md5
    assert not (dest / "diabetes_datasets.zip").exists() and not (dest / "provenance.json").exists()


def test_rejects_wrong_size_and_unsafe_paths(tmp_path):
    z = _fixture_zip(tmp_path, MEMBERS)
    with pytest.raises(fetch.VerificationError, match="size"):
        fetch.verify(z, hashlib.md5(z.read_bytes()).hexdigest(), z.stat().st_size + 1)
    sub = tmp_path / "unsafe"
    sub.mkdir()
    bad = _fixture_zip(sub, {"../escape.txt": "x"})
    with pytest.raises(fetch.VerificationError, match="unsafe"):
        fetch.verify(bad, hashlib.md5(bad.read_bytes()).hexdigest(), bad.stat().st_size)


# --- failure behaviour (pre-commit review): nothing unverified may sit under the final name -------------

def _args(z: Path, dest: Path, *extra: str) -> list[str]:
    return ["--dest", str(dest), "--expected-md5", hashlib.md5(z.read_bytes()).hexdigest(),
            "--expected-size", str(z.stat().st_size), *extra]


def _listing(dest: Path) -> list[str]:
    return sorted(p.name for p in dest.iterdir())


def test_truncated_archive_rejected_even_with_matching_digest(tmp_path):
    z = _fixture_zip(tmp_path, MEMBERS)
    t = tmp_path / "truncated.zip"
    t.write_bytes(z.read_bytes()[: z.stat().st_size // 2])
    dest = tmp_path / "out"
    assert fetch.main(["--archive", str(t), *_args(t, dest)]) == 3
    assert _listing(dest) == []


def test_invalid_zip_rejected(tmp_path):
    bad = tmp_path / "not_a_zip.zip"
    bad.write_bytes(b"synthetic bytes that are not a zip archive")
    dest = tmp_path / "out"
    assert fetch.main(["--archive", str(bad), *_args(bad, dest)]) == 3
    assert _listing(dest) == []


def test_missing_archive_is_a_clean_blocked_exit(tmp_path, capsys):
    z = _fixture_zip(tmp_path, MEMBERS)
    dest = tmp_path / "out"
    assert fetch.main(["--archive", str(tmp_path / "absent.zip"), *_args(z, dest)]) == 2
    assert "archive not found" in capsys.readouterr().err
    assert _listing(dest) == []


def test_network_failure_leaves_nothing(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise OSError("simulated network failure")
    monkeypatch.setattr(fetch.urllib.request, "urlopen", boom)
    z = _fixture_zip(tmp_path, MEMBERS)
    dest = tmp_path / "out"
    assert fetch.main(_args(z, dest)) == 2
    assert _listing(dest) == []


def test_interrupted_download_leaves_no_partial_archive(tmp_path, monkeypatch):
    z = _fixture_zip(tmp_path, MEMBERS)
    payload = z.read_bytes()

    class Interrupted(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, n=-1):
            if self.tell() > 100:
                raise OSError("connection reset mid-download")
            return super().read(64)

    monkeypatch.setattr(fetch.urllib.request, "urlopen", lambda *a, **k: Interrupted(payload))
    dest = tmp_path / "out"
    assert fetch.main(_args(z, dest)) == 2
    assert _listing(dest) == []  # neither the final name nor a .part file survives


def test_successful_download_path(tmp_path, monkeypatch):
    z = _fixture_zip(tmp_path, MEMBERS)
    monkeypatch.setattr(fetch.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(z.read_bytes()))
    dest = tmp_path / "out"
    assert fetch.main(_args(z, dest)) == 0
    assert _listing(dest) == ["diabetes_datasets.zip", "members.txt", "provenance.json"]
    assert json.loads((dest / "provenance.json").read_text())["retrieval"] == "download"


def test_existing_verified_archive_survives_a_failed_forced_rerun(tmp_path):
    z = _fixture_zip(tmp_path, MEMBERS)
    dest = tmp_path / "out"
    assert fetch.main(["--archive", str(z), *_args(z, dest)]) == 0
    before = {n: (dest / n).read_bytes() for n in _listing(dest)}
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"not a zip")
    assert fetch.main(["--archive", str(bad), *_args(z, dest), "--force"]) == 3
    assert {n: (dest / n).read_bytes() for n in _listing(dest)} == before


def test_existing_verified_archive_is_not_reacquired(tmp_path):
    z = _fixture_zip(tmp_path, MEMBERS)
    dest = tmp_path / "out"
    assert fetch.main(["--archive", str(z), *_args(z, dest)]) == 0
    # the output file itself as --archive (same-file case) must not crash
    assert fetch.main(["--archive", str(dest / "diabetes_datasets.zip"), *_args(z, dest)]) == 0
    assert fetch.main(["--archive", str(dest / "diabetes_datasets.zip"), *_args(z, dest), "--force"]) == 0


def test_corrupt_existing_archive_and_its_stale_provenance_are_removed(tmp_path):
    z = _fixture_zip(tmp_path, MEMBERS)
    dest = tmp_path / "out"
    assert fetch.main(["--archive", str(z), *_args(z, dest)]) == 0
    (dest / "diabetes_datasets.zip").write_bytes(b"corrupted after the fact")
    assert fetch.main(["--archive", str(tmp_path / "absent.zip"), *_args(z, dest)]) == 2
    assert _listing(dest) == []  # no stale provenance describing a file that is no longer valid


def test_orphaned_provenance_without_archive_is_removed(tmp_path):
    z = _fixture_zip(tmp_path, MEMBERS)
    dest = tmp_path / "out"
    dest.mkdir()
    (dest / "provenance.json").write_text("{}")
    (dest / "members.txt").write_text("x\n")
    assert fetch.main(["--archive", str(tmp_path / "absent.zip"), *_args(z, dest)]) == 2
    assert _listing(dest) == []
