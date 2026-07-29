"""Environment-variable compatibility helpers for the GateTruth rename."""

from __future__ import annotations

import os
from collections.abc import Mapping


def read_env(
    suffix: str,
    default: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> str | None:
    """Read GATETRUTH_<suffix>, then its SILICONBENCH_<suffix> alias."""

    source = os.environ if environ is None else environ
    primary = f"GATETRUTH_{suffix}"
    legacy = f"SILICONBENCH_{suffix}"
    if primary in source:
        return source[primary]
    if legacy in source:
        return source[legacy]
    return default
