"""Run the schedule-ready GateTruth nightly regression inside gatetruth:v1."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
RESULTS_ROOT = REPO_ROOT / "results" / "nightly"
REFERENCE_SCORE = 66.67
ROTATION_SIZE = 6
ROTATION_NIGHTS = 10


def task_ids(root: Path = REPO_ROOT) -> list[str]:
    """Return the frozen Track A task ids in deterministic order."""

    return sorted(path.parent.name for path in (root / "tasks").glob("*/task.yaml"))


def rotation_for_day(tasks: list[str], day_of_year: int) -> list[str]:
    """Select six tasks so ten consecutive rotation slots cover the 60-task suite."""

    if len(tasks) != ROTATION_SIZE * ROTATION_NIGHTS:
        raise ValueError(f"rotation requires 60 tasks, found {len(tasks)}")
    if day_of_year < 1 or day_of_year > 366:
        raise ValueError("day_of_year must be in 1..366")
    slot = (day_of_year - 1) % ROTATION_NIGHTS
    start = slot * ROTATION_SIZE
    return tasks[start : start + ROTATION_SIZE]


def aggregate_failures(
    acceptance: list[dict[str, Any]],
    mutation: list[dict[str, Any]],
    site: dict[str, Any],
) -> list[str]:
    """Return stable failure labels for the nightly exit decision."""

    failures = [
        f"acceptance:{result['task']}"
        for result in acceptance
        if result.get("status") != "pass"
    ]
    failures.extend(
        f"mutation:{result['task']}"
        for result in mutation
        if result.get("status") != "pass"
    )
    if site.get("status") != "pass":
        failures.append("site")
    return failures


def run_nightly(
    *,
    run_date: date,
    only_task: str | None = None,
    root: Path = REPO_ROOT,
) -> tuple[dict[str, Any], str]:
    """Run acceptance, sequential mutation, and site stages and persist results."""

    started = time.perf_counter()
    tasks = task_ids(root)
    if len(tasks) != 60:
        raise ValueError(f"expected 60 Track A tasks, found {len(tasks)}")
    if only_task is not None and only_task not in tasks:
        raise ValueError(f"unknown --only-task: {only_task}")
    acceptance_tasks = [only_task] if only_task else tasks
    mutation_tasks = [only_task] if only_task else rotation_for_day(
        tasks,
        run_date.timetuple().tm_yday,
    )
    work_root = root / "results" / "nightly" / "work" / run_date.isoformat()
    work_root.mkdir(parents=True, exist_ok=True)

    with ThreadPoolExecutor(max_workers=min(4, len(acceptance_tasks))) as pool:
        acceptance = list(
            pool.map(
                lambda task: _run_acceptance(task, root, work_root),
                acceptance_tasks,
            )
        )
    mutation = [
        _run_mutation(task, root, work_root)
        for task in mutation_tasks
    ]
    site = _run_site(root)
    failures = aggregate_failures(acceptance, mutation, site)
    status = "PASS" if not failures else "FAIL"
    duration = round(time.perf_counter() - started, 3)
    summary: dict[str, Any] = {
        "acceptance": acceptance,
        "date": run_date.isoformat(),
        "duration_s": duration,
        "failures": failures,
        "git_sha": _git_sha(root),
        "mutation": mutation,
        "mutation_seed": 1337,
        "site": site,
        "status": status,
    }
    output_root = root / "results" / "nightly"
    output_root.mkdir(parents=True, exist_ok=True)
    output_path = output_root / f"{run_date.isoformat()}.json"
    output_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    acceptance_passed = sum(item["status"] == "pass" for item in acceptance)
    mutation_passed = sum(item["status"] == "pass" for item in mutation)
    line = (
        f"{run_date.isoformat()} status={status} "
        f"acceptance={acceptance_passed}/{len(acceptance)} "
        f"mutation={mutation_passed}/{len(mutation)} "
        f"site={site['status']} duration_s={duration:.3f}"
    )
    with (output_root / "log.txt").open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(line + "\n")
    return summary, line


def _run_acceptance(task: str, root: Path, work_root: Path) -> dict[str, Any]:
    manifest = work_root / "acceptance" / f"{task}.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "harness.cli",
        "run",
        "--task",
        task,
        "--submission",
        f"tasks/{task}/ref/ref.sv",
        "--out",
        str(manifest),
    ]
    result = _run(command, root, timeout_s=300)
    score: float | None = None
    error: str | None = None
    if result.returncode == 0:
        try:
            score = float(json.loads(manifest.read_text(encoding="utf-8"))["task_score"])
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            error = f"invalid manifest: {exc}"
    else:
        error = _tail(result.stdout)
    passed = result.returncode == 0 and score is not None and round(score, 2) == REFERENCE_SCORE
    if not passed and error is None:
        error = f"expected score {REFERENCE_SCORE:.2f}, got {score}"
    return {"error": error, "score": score, "status": "pass" if passed else "fail", "task": task}


def _run_mutation(task: str, root: Path, work_root: Path) -> dict[str, Any]:
    report_path = work_root / "mutation" / f"{task}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "harness.mutate",
        "--task",
        task,
        "--min-kill",
        "95",
        "--seed",
        "1337",
        "--json",
        str(report_path),
    ]
    result = _run(command, root, timeout_s=900)
    kill_rate: float | None = None
    error: str | None = None
    try:
        kill_rate = float(json.loads(report_path.read_text(encoding="utf-8"))["kill_rate"])
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        error = f"invalid mutation report: {exc}"
    passed = result.returncode == 0 and kill_rate is not None and kill_rate >= 95.0
    if not passed and error is None:
        error = _tail(result.stdout) or f"kill rate below threshold: {kill_rate}"
    return {
        "error": error,
        "kill_rate": kill_rate,
        "status": "pass" if passed else "fail",
        "task": task,
    }


def _run_site(root: Path) -> dict[str, Any]:
    result = _run([sys.executable, "-m", "harness.cli", "site"], root, timeout_s=60)
    return {
        "error": None if result.returncode == 0 else _tail(result.stdout),
        "status": "pass" if result.returncode == 0 else "fail",
    }


def _run(command: list[str], root: Path, *, timeout_s: int) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or ""
        return subprocess.CompletedProcess(command, 124, f"{output}\nTIMEOUT after {timeout_s}s")


def _git_sha(root: Path) -> str:
    # -c safe.directory=<root>: see paper/data/generate_tables.py's _git_sha() for why
    # plain `git rev-parse` silently returns "unknown" here -- the same dubious-
    # ownership refusal fires whenever this runs against a bind-mounted checkout owned
    # by a different user than the container's, which is exactly how ci.yml stages
    # source for every sandboxed docker run in this project.
    result = _run(
        ["git", "-c", f"safe.directory={root}", "rev-parse", "HEAD"],
        root,
        timeout_s=10,
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def _tail(text: str, limit: int = 1000) -> str:
    return text[-limit:].strip()


def _parse_date(value: str | None) -> date:
    if value is None:
        return datetime.now(UTC).date()
    return date.fromisoformat(value)


def _print_plan(run_date: date, only_task: str | None) -> None:
    tasks = task_ids()
    if only_task is not None and only_task not in tasks:
        raise ValueError(f"unknown --only-task: {only_task}")
    acceptance = [only_task] if only_task else tasks
    mutation = [only_task] if only_task else rotation_for_day(
        tasks,
        run_date.timetuple().tm_yday,
    )
    print(f"date={run_date.isoformat()} day_of_year={run_date.timetuple().tm_yday}")
    print(f"acceptance_tasks={len(acceptance)} parallelism={min(4, len(acceptance))}")
    print("mutation_tasks=" + ",".join(mutation) + " sequential=true seed=1337")
    print("site_rebuild=true scheduling_registration=false")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--only-task")
    parser.add_argument("--date", help="UTC date override (YYYY-MM-DD), primarily for verification")
    args = parser.parse_args(argv)
    try:
        run_date = _parse_date(args.date)
        if args.dry_run:
            _print_plan(run_date, args.only_task)
            return 0
        summary, line = run_nightly(run_date=run_date, only_task=args.only_task)
    except (OSError, ValueError) as exc:
        print(f"nightly: refused: {exc}", file=sys.stderr)
        return 2
    print(line)
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
