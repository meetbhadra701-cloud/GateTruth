"""Deterministic RTL mutation runner."""

from __future__ import annotations

import argparse
import json
import random
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.mutators import Mutant, generate_mutants
from harness.runner import resolve_task, run_formal, run_lint, run_sim


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run deterministic RTL mutation tests for one task")
    parser.add_argument("--task", required=True)
    parser.add_argument("--min-kill", type=float, default=95.0)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--json", dest="json_path")
    args = parser.parse_args(argv)

    report = run_mutation(task_id=args.task, min_kill=args.min_kill, seed=args.seed)
    if args.json_path:
        path = Path(args.json_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(
        "task=%s killed=%d/%d kill_rate=%.2f%% seed=%d"
        % (report["task"], report["killed"], report["total"], report["kill_rate"], report["seed"])
    )
    for survivor in report["survivors"]:
        print("SURVIVED %s %s" % (survivor["id"], survivor["description"]))
    return 0 if report["kill_rate"] >= args.min_kill else 1


def run_mutation(*, task_id: str, min_kill: float, seed: int) -> dict[str, Any]:
    task = resolve_task(task_id)
    ref = task.root / "ref" / "ref.sv"
    source = ref.read_text(encoding="utf-8")
    mutants = generate_mutants(task_id, source)
    rng = random.Random(seed)
    rng.shuffle(mutants)

    # Each mutant is isolated in its own temporary directory, so bounded parallelism
    # shortens the 60-task audit without changing report order or seeded determinism.
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda mutant: _run_one(task_id, mutant), mutants))
    killed = [result for result in results if result["killed"]]
    indeterminate = [result for result in results if result["indeterminate"]]
    survivors = [result for result in results if not result["killed"]]
    kill_rate = 100.0 if not results else (100.0 * len(killed) / len(results))
    return {
        "task": task_id,
        "seed": seed,
        "min_kill": min_kill,
        "total": len(results),
        "killed": len(killed),
        "survived": len(survivors),
        "indeterminate": len(indeterminate),
        "kill_rate": round(kill_rate, 4),
        "survivors": survivors,
        "results": results,
    }


def _run_one(task_id: str, mutant: Mutant) -> dict[str, Any]:
    task = resolve_task(task_id)
    with tempfile.TemporaryDirectory(prefix=f"siliconbench-mut-{task_id}-") as temp:
        work_root = Path(temp)
        mutated = work_root / "mutant.sv"
        mutated.write_text(mutant.source, encoding="utf-8")

        stage, log = run_lint(mutated)
        if stage["status"] != "pass":
            return _result(mutant, killed=True, killed_by="lint", log=log)

        stage, log = run_sim(task, mutated, work_root)
        if stage["status"] != "pass":
            if _is_timeout(log):
                retry_root = work_root / "timeout_retry"
                retry_root.mkdir()
                retry_stage, retry_log = run_sim(task, mutated, retry_root, timeout_s=60)
                if retry_stage["status"] == "pass":
                    stage, log = retry_stage, retry_log
                elif _is_timeout(retry_log):
                    return _result(
                        mutant,
                        killed=False,
                        killed_by="sim-timeout",
                        log=retry_log,
                        indeterminate=True,
                    )
                else:
                    return _result(mutant, killed=True, killed_by="sim", log=retry_log)
            else:
                return _result(mutant, killed=True, killed_by="sim", log=log)

        stage, log = run_formal(task, mutated, work_root)
        if stage["status"] == "fail":
            return _result(mutant, killed=True, killed_by="formal", log=log)

        return _result(mutant, killed=False, killed_by=None, log=log)


def _is_timeout(log: str) -> bool:
    return "TIMEOUT after" in log


def _result(
    mutant: Mutant,
    *,
    killed: bool,
    killed_by: str | None,
    log: str,
    indeterminate: bool = False,
) -> dict[str, Any]:
    return {
        "id": mutant.id,
        "operator": mutant.operator,
        "description": mutant.description,
        "killed": killed,
        "killed_by": killed_by,
        "indeterminate": indeterminate,
    }


if __name__ == "__main__":
    raise SystemExit(main())
