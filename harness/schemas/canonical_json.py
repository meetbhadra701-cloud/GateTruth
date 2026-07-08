"""Canonical JSON and manifest signature helpers.

The frozen manifest contract defines deterministic JSON as sorted UTF-8 JSON with
no insignificant whitespace. Python's JSON encoder uses a stable repr-style float
format for finite floats, which is the formatting rule the contract names.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from typing import Any

SIGNATURE_EXCLUDED_FIELDS = frozenset({"timestamp", "signature", "wall_clock_s"})


class CanonicalJsonError(ValueError):
    """Raised when an object cannot be represented as canonical JSON."""


def _normalize(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return _normalize(value.model_dump(mode="json"))
    if isinstance(value, Mapping):
        return {str(key): _normalize(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [_normalize(item) for item in value]
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CanonicalJsonError("canonical JSON forbids NaN and infinity")
        return float(repr(value))
    return value


def canonical_dumps(value: Any) -> str:
    """Return canonical JSON text for a JSON-compatible object."""

    normalized = _normalize(value)
    return json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def canonical_bytes(value: Any) -> bytes:
    """Return UTF-8 encoded canonical JSON bytes."""

    return canonical_dumps(value).encode("utf-8")


def manifest_signature_payload(value: Mapping[str, Any]) -> dict[str, Any]:
    """Drop nondeterministic manifest fields before signature computation."""

    return {
        key: item
        for key, item in value.items()
        if key not in SIGNATURE_EXCLUDED_FIELDS
    }


def compute_manifest_signature(value: Mapping[str, Any]) -> str:
    """Return the lowercase SHA-256 hex signature for a manifest object."""

    payload = manifest_signature_payload(value)
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()
