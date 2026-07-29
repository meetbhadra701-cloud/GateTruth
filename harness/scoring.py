"""Single-source PPA scoring helpers for GateTruth manifests."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from harness.schemas.manifest import ResultManifest, load_manifest

PPA_CAP = 1.5
REFERENCE_METRICS_VERSION = "1"
REFERENCE_METRICS_PATH = Path(__file__).with_name("reference_metrics.json")


@dataclass(frozen=True)
class PpaMetrics:
    """The three strictly-positive physical quantities used by the score."""

    area_um2: float
    delay_ns: float
    power_mw: float
    clock_target_ns: float

    def __post_init__(self) -> None:
        for name in ("area_um2", "delay_ns", "power_mw", "clock_target_ns"):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and greater than zero")


def delay_from_wns(clock_target_ns: float, wns_ns: float) -> float:
    """Return worst-path delay from the task period and OpenSTA slack."""

    if not math.isfinite(clock_target_ns) or clock_target_ns <= 0:
        raise ValueError("clock_target_ns must be finite and greater than zero")
    if not math.isfinite(wns_ns):
        raise ValueError("wns_ns must be finite")
    delay_ns = clock_target_ns - wns_ns
    if delay_ns <= 0:
        raise ValueError("derived delay_ns must be greater than zero")
    return delay_ns


def ppa_from_metrics(reference: PpaMetrics, measured: PpaMetrics) -> float:
    """Return the ADR-0003 geometric mean of reference-to-design ratios."""

    ratios = (
        reference.area_um2 / measured.area_um2,
        reference.delay_ns / measured.delay_ns,
        reference.power_mw / measured.power_mw,
    )
    return math.prod(ratios) ** (1.0 / len(ratios))


def reference_metrics_path(task_id: str) -> Path:
    """Return the committed metric table used to normalize one task."""

    if task_id == "toy_task":
        toy_path = (
            Path(__file__).parent
            / "tests"
            / "fixtures"
            / "toy_task"
            / "reference_metrics.json"
        )
        if toy_path.is_file():
            return toy_path
    return REFERENCE_METRICS_PATH


def load_reference_metrics(
    task_id: str,
    path: str | Path | None = None,
) -> PpaMetrics:
    """Load and validate one task's committed scoring denominator."""

    metrics_path = Path(path) if path is not None else reference_metrics_path(task_id)
    try:
        raw = json.loads(metrics_path.read_text(encoding="utf-8"))
        if raw.get("schema_version") != REFERENCE_METRICS_VERSION:
            raise ValueError("unsupported reference-metrics schema_version")
        task_raw = raw["tasks"][task_id]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ValueError(
            f"missing or invalid reference metrics for {task_id}: {metrics_path}"
        ) from exc
    if not isinstance(task_raw, dict):
        raise ValueError(f"reference metrics for {task_id} must be an object")
    return _metrics_from_mapping(task_raw)


def _metrics_from_mapping(raw: dict[str, Any]) -> PpaMetrics:
    try:
        return PpaMetrics(
            area_um2=float(raw["area_um2"]),
            delay_ns=float(raw["delay_ns"]),
            power_mw=float(raw["power_mw"]),
            clock_target_ns=float(raw["clock_target_ns"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("reference metrics contain invalid physical values") from exc


def task_score_from_ppa(ppa: float) -> float:
    if not math.isfinite(ppa) or ppa < 0:
        raise ValueError("ppa must be finite and non-negative")
    return 100.0 * min(ppa, PPA_CAP) / PPA_CAP


def correctness_gates_passed(manifest: ResultManifest) -> bool:
    required = {0, 1, 2}
    stages = {stage.stage: stage for stage in manifest.stages}
    return all(
        stages.get(stage) is not None
        and stages[stage].status in {"pass", "skip"}
        for stage in required
    )


def ppa_gates_passed(manifest: ResultManifest) -> bool:
    required = {3, 4, 5}
    stages = {stage.stage: stage for stage in manifest.stages}
    return all(
        stages.get(stage) is not None and stages[stage].status == "pass"
        for stage in required
    )


def score_manifest(path: str | Path) -> float:
    manifest = load_manifest(path)
    if not correctness_gates_passed(manifest) or not ppa_gates_passed(manifest):
        expected = 0.0
    else:
        expected = task_score_from_ppa(manifest.ppa)
    if not math.isclose(manifest.task_score, expected, abs_tol=1e-9):
        raise ValueError(
            f"stored task_score {manifest.task_score} does not match "
            f"ppa-derived score {expected}"
        )
    return manifest.task_score
