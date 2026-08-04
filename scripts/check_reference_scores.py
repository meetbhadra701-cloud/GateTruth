"""Score all 60 Track A references and reject any normalization drift."""

from __future__ import annotations

import argparse
import json
import math
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from harness.atomic_write import atomic_write_text  # noqa: E402
from harness.runner import run_task  # noqa: E402

REFERENCE_PPA = 1.0
REFERENCE_SCORE = 100.0 / 1.5


def task_ids(root: Path = REPO_ROOT) -> list[str]:
    return sorted(path.parent.name for path in (root / "tasks").glob("*/task.yaml"))


def score_reference(
    task_id: str,
    *,
    out_dir: Path,
    official: bool,
) -> dict[str, object]:
    manifest = run_task(
        task_id,
        REPO_ROOT / "tasks" / task_id / "ref" / "ref.sv",
        out_dir / f"{task_id}.json",
        official=official,
    )
    passed = (
        math.isclose(manifest.ppa, REFERENCE_PPA, rel_tol=0.0, abs_tol=1e-12)
        and math.isclose(
            manifest.task_score,
            REFERENCE_SCORE,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
    )
    return {
        "passed": passed,
        "ppa": manifest.ppa,
        "score": manifest.task_score,
        "task_id": task_id,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--official", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    tasks = task_ids()
    if len(tasks) != 60:
        raise ValueError(f"expected 60 Track A tasks, found {len(tasks)}")
    if args.jobs < 1:
        raise ValueError("--jobs must be positive")
    args.out.mkdir(parents=True, exist_ok=True)

    def run(task_id: str) -> dict[str, object]:
        return score_reference(
            task_id,
            out_dir=args.out,
            official=args.official,
        )

    with ThreadPoolExecutor(max_workers=min(args.jobs, len(tasks))) as pool:
        results = list(pool.map(run, tasks))
    for result in results:
        status = "PASS" if result["passed"] else "FAIL"
        print(
            f"{status} {result['task_id']} "
            f"ppa={result['ppa']:.12g} score={result['score']:.12g}"
        )
    failures = [str(result["task_id"]) for result in results if not result["passed"]]
    summary = {
        "failures": failures,
        "official": args.official,
        "passed": len(results) - len(failures),
        "total": len(results),
    }
    atomic_write_text(
        args.out / "summary.json", json.dumps(summary, indent=2, sort_keys=True) + "\n"
    )
    print(
        f"reference score check: {summary['passed']}/{summary['total']} "
        f"official={str(args.official).lower()}"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
