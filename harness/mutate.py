"""Deterministic RTL mutation runner.

Reports a *simulation-testbench* kill rate: the fraction of mutants that a
compiling reference design's cocotb testbench alone catches. Lint failures
mean the mutant never became a runnable design (excluded from the
denominator, not a testbench kill); formal detections are disclosed
separately and never inflate this metric; and the unmodified reference is
run through the identical pipeline first, so a broken harness/hidden-test
setup fails the whole task closed instead of misreporting every mutant as
"killed" by the same setup error.
"""

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
from harness.runner import HIDDEN_FAILURE_PREFIX, resolve_task, run_formal, run_lint, run_sim

SCHEMA_VERSION = 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run deterministic RTL mutation tests for one task")
    parser.add_argument("--task", required=True)
    parser.add_argument("--min-kill", type=float, default=95.0)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--official", action="store_true")
    parser.add_argument("--json", dest="json_path")
    args = parser.parse_args(argv)

    report = run_mutation(
        task_id=args.task,
        min_kill=args.min_kill,
        seed=args.seed,
        jobs=args.jobs,
        official=args.official,
    )
    if args.json_path:
        path = Path(args.json_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if report["status"] != "ok":
        print(
            "task=%s status=%s reason=%s"
            % (report["task"], report["status"], report["status_reason"])
        )
        return 1

    print(
        "task=%s killed=%d/%d kill_rate=%.2f%% stillborn=%d setup_errors=%d "
        "formal_only=%d indeterminate=%d seed=%d"
        % (
            report["task"],
            report["killed"],
            report["total"],
            report["kill_rate"],
            report["stillborn"],
            report["setup_errors"],
            report["formal_only_kills"],
            report["indeterminate"],
            report["seed"],
        )
    )
    for survivor in report["survivors"]:
        print("SURVIVED %s %s" % (survivor["id"], survivor["description"]))
    return 0 if report["kill_rate"] >= args.min_kill else 1


def run_mutation(
    *,
    task_id: str,
    min_kill: float,
    seed: int,
    jobs: int = 1,
    official: bool = False,
) -> dict[str, Any]:
    task = resolve_task(task_id)
    ref = task.root / "ref" / "ref.sv"
    source = ref.read_text(encoding="utf-8")

    baseline = _run_baseline(task_id, source, official=official)
    if baseline["status"] != "pass":
        return {
            "schema_version": SCHEMA_VERSION,
            "task": task_id,
            "seed": seed,
            "jobs": jobs,
            "official": official,
            "min_kill": min_kill,
            "status": "setup_error",
            "status_reason": (
                f"unmodified reference failed its own {baseline['stage']} stage "
                f"before any mutant was generated: {baseline['log'][:2000]}"
            ),
            "baseline": baseline,
            "total_generated": 0,
            "stillborn": 0,
            "setup_errors": 0,
            "total": 0,
            "killed": 0,
            "formal_only_kills": 0,
            "survived": 0,
            "indeterminate": 0,
            "kill_rate": 0.0,
            "survivors": [],
            "results": [],
        }

    mutants = generate_mutants(task_id, source)
    rng = random.Random(seed)
    rng.shuffle(mutants)

    if jobs <= 1:
        results = [_run_one(task_id, mutant, official=official) for mutant in mutants]
    else:
        # Parallel execution is exploratory only. Certification calls this with jobs=1.
        with ThreadPoolExecutor(max_workers=jobs) as pool:
            results = list(
                pool.map(
                    lambda mutant: _run_one(task_id, mutant, official=official),
                    mutants,
                )
            )

    setup_error_mutants = [result for result in results if result["setup_error"]]
    stillborn = [
        result for result in results if result["stillborn"] and not result["setup_error"]
    ]
    excluded = [result for result in results if result["stillborn"]]
    valid = [result for result in results if not result["stillborn"]]
    killed = [result for result in valid if result["killed_by"] == "sim"]
    indeterminate = [result for result in valid if result["indeterminate"]]
    survived = [
        result
        for result in valid
        if result["killed_by"] != "sim" and not result["indeterminate"]
    ]
    formal_only_kills = [result for result in survived if result["killed_by"] == "formal"]

    assert len(killed) + len(survived) + len(indeterminate) == len(valid), (
        "kill/survive/indeterminate partition invariant violated"
    )
    assert len(valid) + len(excluded) == len(results), (
        "valid/excluded partition invariant violated"
    )

    if not valid:
        return {
            "schema_version": SCHEMA_VERSION,
            "task": task_id,
            "seed": seed,
            "jobs": jobs,
            "official": official,
            "min_kill": min_kill,
            "status": "unsupported",
            "status_reason": (
                f"{len(stillborn)} lint failure(s) and {len(setup_error_mutants)} "
                f"harness setup error(s) out of {len(results)} generated mutants; "
                "zero valid mutants remain for the simulation-testbench denominator"
            ),
            "baseline": baseline,
            "total_generated": len(results),
            "stillborn": len(stillborn),
            "setup_errors": len(setup_error_mutants),
            "total": 0,
            "killed": 0,
            "formal_only_kills": 0,
            "survived": 0,
            "indeterminate": 0,
            "kill_rate": 0.0,
            "survivors": [],
            "results": results,
        }

    kill_rate = 100.0 * len(killed) / len(valid)
    return {
        "schema_version": SCHEMA_VERSION,
        "task": task_id,
        "seed": seed,
        "jobs": jobs,
        "official": official,
        "min_kill": min_kill,
        "status": "ok",
        "status_reason": None,
        "baseline": baseline,
        "total_generated": len(results),
        "stillborn": len(stillborn),
        "setup_errors": len(setup_error_mutants),
        "total": len(valid),
        "killed": len(killed),
        "formal_only_kills": len(formal_only_kills),
        "survived": len(survived),
        "indeterminate": len(indeterminate),
        "kill_rate": round(kill_rate, 4),
        "survivors": survived,
        "results": results,
    }


def _run_baseline(task_id: str, source: str, *, official: bool) -> dict[str, Any]:
    """Run the unmodified reference through the exact mutant pipeline first.

    A baseline that doesn't pass cleanly means the harness/hidden-test setup
    is broken (most commonly: official mode with no hidden root mounted) --
    every mutant would then fail the same way for the same reason, which is
    not a testbench signal. Fail the whole task closed instead of silently
    reporting a meaningless 100% kill rate.
    """

    task = resolve_task(task_id)
    with tempfile.TemporaryDirectory(prefix=f"gatetruth-mut-baseline-{task_id}-") as temp:
        work_root = Path(temp)
        candidate = work_root / "baseline.sv"
        candidate.write_text(source, encoding="utf-8")

        stage, log = run_lint(candidate)
        if stage["status"] != "pass":
            return {"status": "fail", "stage": "lint", "log": log}

        stage, log = run_sim(task, candidate, work_root, official=official)
        if stage["status"] != "pass":
            return {"status": "fail", "stage": "sim", "log": log}

        stage, log = run_formal(task, candidate, work_root)
        if stage["status"] == "fail":
            return {"status": "fail", "stage": "formal", "log": log}

        return {"status": "pass", "stage": None, "log": ""}


def _run_one(
    task_id: str,
    mutant: Mutant,
    *,
    official: bool,
) -> dict[str, Any]:
    task = resolve_task(task_id)
    with tempfile.TemporaryDirectory(prefix=f"gatetruth-mut-{task_id}-") as temp:
        work_root = Path(temp)
        mutated = work_root / "mutant.sv"
        mutated.write_text(mutant.source, encoding="utf-8")

        stage, log = run_lint(mutated)
        if stage["status"] != "pass":
            return _result(mutant, stillborn=True, killed_by=None, log=log)

        stage, log = run_sim(task, mutated, work_root, official=official)
        if stage["status"] != "pass":
            if HIDDEN_FAILURE_PREFIX in log:
                # A per-mutant harness/hidden-test setup error, not a mutant-caused
                # failure. The baseline check above should already have caught this
                # for the whole task; this is defense in depth against a setup that
                # broke mid-run (e.g. a hidden mount disappearing).
                return _result(
                    mutant, stillborn=True, killed_by=None, log=log, setup_error=True
                )
            if _is_timeout(log):
                retry_root = work_root / "timeout_retry"
                retry_root.mkdir()
                retry_stage, retry_log = run_sim(
                    task,
                    mutated,
                    retry_root,
                    timeout_s=60,
                    official=official,
                )
                if retry_stage["status"] == "pass":
                    stage, log = retry_stage, retry_log
                elif _is_timeout(retry_log):
                    return _result(
                        mutant,
                        killed_by=None,
                        log=retry_log,
                        indeterminate=True,
                    )
                else:
                    return _result(mutant, killed_by="sim", log=retry_log)
            else:
                return _result(mutant, killed_by="sim", log=log)

        stage, log = run_formal(task, mutated, work_root)
        if stage["status"] == "fail":
            return _result(mutant, killed_by="formal", log=log)

        return _result(mutant, killed_by=None, log=log)


def _is_timeout(log: str) -> bool:
    return "TIMEOUT after" in log


def _result(
    mutant: Mutant,
    *,
    killed_by: str | None,
    log: str,
    stillborn: bool = False,
    indeterminate: bool = False,
    setup_error: bool = False,
) -> dict[str, Any]:
    return {
        "id": mutant.id,
        "operator": mutant.operator,
        "description": mutant.description,
        "stillborn": stillborn,
        "setup_error": setup_error,
        "killed_by": killed_by,
        "indeterminate": indeterminate,
    }


if __name__ == "__main__":
    raise SystemExit(main())
