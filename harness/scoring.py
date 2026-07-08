"""Scoring helpers for SiliconBench manifests."""

from __future__ import annotations

from pathlib import Path

from harness.schemas.manifest import ResultManifest, load_manifest

PPA_CAP = 1.5
REFERENCE_PPA = 1.0


def task_score_from_ppa(ppa: float) -> float:
    if ppa < 0:
        raise ValueError("ppa must be non-negative")
    return 100.0 * min(ppa, PPA_CAP) / PPA_CAP


def correctness_gates_passed(manifest: ResultManifest) -> bool:
    required = {0, 1, 2}
    stages = {stage.stage: stage for stage in manifest.stages}
    return all(stages.get(stage) is not None and stages[stage].status in {"pass", "skip"} for stage in required)


def score_manifest(path: str | Path) -> float:
    manifest = load_manifest(path)
    return manifest.task_score
