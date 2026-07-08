import pytest

from harness.schemas.canonical_json import (
    CanonicalJsonError,
    canonical_dumps,
    compute_manifest_signature,
)


def test_canonical_json_sorts_keys_and_omits_whitespace():
    assert canonical_dumps({"b": 1, "a": 2.5}) == '{"a":2.5,"b":1}'


def test_manifest_signature_ignores_nondeterministic_fields():
    base = {
        "task_id": "toy_task",
        "timestamp": "2026-07-08T00:00:00Z",
        "wall_clock_s": 1.2,
        "signature": "0" * 64,
        "ppa": 1.0,
    }
    changed = dict(base)
    changed["timestamp"] = "2026-07-08T00:00:01Z"
    changed["wall_clock_s"] = 9.9
    changed["signature"] = "f" * 64

    assert compute_manifest_signature(base) == compute_manifest_signature(changed)

    changed["ppa"] = 1.1
    assert compute_manifest_signature(base) != compute_manifest_signature(changed)


def test_canonical_json_rejects_nonfinite_float():
    with pytest.raises(CanonicalJsonError):
        canonical_dumps({"bad": float("nan")})
