"""Patient-level split: every session (CGM period) of a patient goes to the same split, decided BEFORE windows exist."""

from __future__ import annotations

import numpy as np

SPLITS = ("train", "validation", "test")


def patient_split(patient_ids: list[str], seed: int, fractions: tuple[float, float, float]) -> dict[str, list[str]]:
    ids = sorted(set(patient_ids))
    if len(ids) < 3:
        raise ValueError(f"need at least 3 patients for a 3-way split, got {len(ids)}")
    if abs(sum(fractions) - 1) > 1e-9:
        raise ValueError("fractions must sum to 1")
    order = np.random.default_rng(seed).permutation(len(ids))
    n_test = max(1, round(fractions[2] * len(ids)))
    n_val = max(1, round(fractions[1] * len(ids)))
    test = sorted(ids[i] for i in order[:n_test])
    val = sorted(ids[i] for i in order[n_test:n_test + n_val])
    train = sorted(ids[i] for i in order[n_test + n_val:])
    out = {"train": train, "validation": val, "test": test}
    assert_disjoint(out)
    return out


def assert_disjoint(split: dict[str, list[str]]) -> None:
    seen: dict[str, str] = {}
    for name in SPLITS:
        for pid in split[name]:
            if pid in seen:
                raise AssertionError(f"patient {pid} is in both {seen[pid]} and {name}")
            seen[pid] = name


def assign(patient_ids, split: dict[str, list[str]]) -> np.ndarray:
    lookup = {pid: name for name in SPLITS for pid in split[name]}
    return np.array([lookup[p] for p in patient_ids], dtype=object)
