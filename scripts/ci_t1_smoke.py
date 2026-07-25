"""Run the deterministic non-official T1 reference smoke used by pull-request CI."""

from __future__ import annotations

import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from harness.hidden import HIDDEN_REPORT_ENV, HIDDEN_ROOT_ENV  # noqa: E402
from harness.runner import run_task  # noqa: E402
from harness.schemas.manifest import ResultManifest  # noqa: E402
from harness.schemas.task_yaml import load_task_yaml  # noqa: E402

EXPECTED_T1_TASKS = 20
REFERENCE_SCORE = 66.67


@dataclass(frozen=True)
class SmokeResult:
    """One reference result rendered in deterministic task order."""

    task_id: str
    score: float | None
    duration_s: float
    error: str | None


def t1_task_ids(root: Path = REPO_ROOT) -> list[str]:
    """Return the canonical T1 suite and reject an incomplete checkout."""

    tasks = []
    for path in sorted((root / "tasks").glob("*/task.yaml")):
        task = load_task_yaml(path)
        if task.tier == "T1":
            tasks.append(task.id)
    if len(tasks) != EXPECTED_T1_TASKS:
        raise ValueError(
            f"expected {EXPECTED_T1_TASKS} T1 tasks, found {len(tasks)}"
        )
    return tasks


def manifest_error(manifest: ResultManifest) -> str | None:
    """Return why a reference manifest is not a CI smoke pass."""

    if round(manifest.task_score, 2) != REFERENCE_SCORE:
        return (
            f"expected task_score {REFERENCE_SCORE:.2f}, "
            f"got {manifest.task_score}"
        )
    failed = [
        f"{stage.stage}:{stage.name}={stage.status}"
        for stage in manifest.stages
        if stage.stage <= 5 and stage.status not in {"pass", "skip"}
    ]
    if failed:
        return "failed stages: " + ", ".join(failed)
    return None


def _run_reference(task_id: str, output_root: Path) -> SmokeResult:
    started = time.perf_counter()
    try:
        manifest = run_task(
            task_id,
            REPO_ROOT / "tasks" / task_id / "ref" / "ref.sv",
            output_root / f"{task_id}.json",
            official=False,
        )
        error = manifest_error(manifest)
        score: float | None = manifest.task_score
    except Exception as exc:  # noqa: BLE001 - each CI task must report, not abort the pool
        error = f"{type(exc).__name__}: {exc}"
        score = None
    return SmokeResult(
        task_id=task_id,
        score=score,
        duration_s=time.perf_counter() - started,
        error=error,
    )


def run_t1_smoke(output_root: Path, *, jobs: int = 4) -> list[SmokeResult]:
    """Score every T1 reference without loading private hidden tests."""

    if jobs < 1:
        raise ValueError("jobs must be at least 1")
    os.environ.pop(HIDDEN_ROOT_ENV, None)
    os.environ.pop(HIDDEN_REPORT_ENV, None)
    output_root.mkdir(parents=True, exist_ok=True)
    tasks = t1_task_ids()
    with ThreadPoolExecutor(max_workers=min(jobs, len(tasks))) as pool:
        results = list(
            pool.map(
                lambda task_id: _run_reference(task_id, output_root),
                tasks,
            )
        )
    return sorted(results, key=lambda result: result.task_id)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--out", type=Path, default=Path("build/ci-t1"))
    args = parser.parse_args(argv)

    started = time.perf_counter()
    results = run_t1_smoke(args.out, jobs=args.jobs)
    for result in results:
        status = "PASS" if result.error is None else "FAIL"
        score = "--" if result.score is None else f"{result.score:.2f}"
        detail = "" if result.error is None else f" error={result.error}"
        print(
            f"{status} {result.task_id} score={score} "
            f"duration_s={result.duration_s:.3f}{detail}"
        )
    failures = [result for result in results if result.error is not None]
    status = "PASS" if not failures else "FAIL"
    print(
        f"ci_t1_smoke status={status} tasks={len(results)} "
        f"mode=non-official duration_s={time.perf_counter() - started:.3f}"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
