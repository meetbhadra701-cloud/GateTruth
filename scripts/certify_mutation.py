"""Certify all Track A mutation gates sequentially and reproducibly."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from datetime import UTC, datetime  # noqa: E402

from harness.atomic_write import atomic_write_text  # noqa: E402
from harness.git_provenance import harness_git  # noqa: E402
from harness.mutate import run_mutation  # noqa: E402
from harness.runner import (  # noqa: E402
    runtime_docker_digest_info,
    self_declared_image_marker,
)
from harness.schemas.canonical_json import compute_manifest_signature  # noqa: E402
from harness.schemas.mutation_certification import MutationCertificationSummary  # noqa: E402

EXPECTED_TASKS = 60


def task_ids(root: Path = REPO_ROOT) -> list[str]:
    return sorted(path.parent.name for path in (root / "tasks").glob("*/task.yaml"))


def write_json(path: Path, value: dict[str, Any]) -> None:
    atomic_write_text(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=1337)
    parser.add_argument(
        "--out",
        type=Path,
        default=REPO_ROOT / "results" / "mutation" / "certification",
    )
    parser.add_argument("--min-kill", type=float, default=95.0)
    parser.add_argument(
        "--no-task-specs",
        dest="include_task_specs",
        action="store_false",
        default=True,
        help=(
            "generic-only mutation profile (matches the paper's described fixed "
            "operator set and external-audit/auditor/audit.py's own condition) -- "
            "GTFS-003. Default keeps include_task_specs=True, the condition every "
            "committed certification report was actually certified under; freezing "
            "which condition the paper claims is a methodology decision, not "
            "something this flag's default silently makes for you"
        ),
    )
    args = parser.parse_args(argv)

    tasks = task_ids()
    if len(tasks) != EXPECTED_TASKS:
        raise ValueError(f"expected {EXPECTED_TASKS} Track A tasks, found {len(tasks)}")
    args.out.mkdir(parents=True, exist_ok=True)

    task_summaries: dict[str, dict[str, int | float | str | None]] = {}
    all_above_floor = True
    any_unsupported = False
    for index, task_id in enumerate(tasks, start=1):
        report = run_mutation(
            task_id=task_id,
            min_kill=args.min_kill,
            seed=args.seed,
            jobs=1,
            official=True,
            include_task_specs=args.include_task_specs,
        )
        write_json(args.out / f"{task_id}.json", report)
        task_summaries[task_id] = {
            "status": report["status"],
            "total_generated": report["total_generated"],
            "indeterminate": report["indeterminate"],
            "kill_rate": report["kill_rate"],
            "killed": report["killed"],
            "survived": report["survived"],
            "stillborn": report["stillborn"],
            "setup_errors": report["setup_errors"],
            "formal_only_kills": report["formal_only_kills"],
            "total": report["total"],
            "task_package_sha256": report["task_package_sha256"],
            "reference_rtl_sha256": report["reference_rtl_sha256"],
            "public_testbench_sha256": report["public_testbench_sha256"],
            "hidden_module_sha256": report["hidden_module_sha256"],
            "hidden_test_count": report["hidden_test_count"],
        }
        if report["status"] != "ok":
            any_unsupported = True
            all_above_floor = False
            print(
                f"[{index:02d}/{EXPECTED_TASKS}] "
                f"BROKEN {task_id} status={report['status']} "
                f"reason={report['status_reason']}"
            )
            continue
        passed = report["kill_rate"] >= args.min_kill
        all_above_floor = all_above_floor and passed
        print(
            f"[{index:02d}/{EXPECTED_TASKS}] "
            f"{'PASS' if passed else 'FAIL'} {task_id} "
            f"kill_rate={report['kill_rate']:.4f}%"
        )

    docker_digest, docker_digest_source = runtime_docker_digest_info()
    summary = {
        "schema_version": 5,
        "all_above_floor": all_above_floor,
        "any_unsupported": any_unsupported,
        "docker_digest": docker_digest,
        "docker_digest_source": docker_digest_source,
        "image_marker": self_declared_image_marker(),
        "harness_git": harness_git(),
        "include_task_specs": args.include_task_specs,
        "jobs": 1,
        "metric": "simulation_testbench_kill_rate",
        "min_kill": args.min_kill,
        "official": True,
        "seed": args.seed,
        "tasks": task_summaries,
        "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "signature": "0" * 64,
    }
    summary["signature"] = compute_manifest_signature(summary)
    # GTFS-030: validate and sign before writing -- MutationCertificationSummary is the
    # same schema scripts/verify_mutation_certification.py checks a committed summary
    # against later, so a summary that fails this pydantic validation should never reach
    # disk as if it were a clean certification run.
    MutationCertificationSummary.model_validate(summary)
    write_json(args.out / "summary.json", summary)
    ok_tasks = [item for item in task_summaries.values() if item["status"] == "ok"]
    print(
        f"mutation certification: "
        f"{sum(item['kill_rate'] >= args.min_kill for item in ok_tasks)}"
        f"/{EXPECTED_TASKS} at or above {args.min_kill:.2f}% "
        f"({len(task_summaries) - len(ok_tasks)} broken/unsupported)"
    )
    if any_unsupported:
        print(
            "mutation certification: refusing to call this a clean run -- "
            "at least one task's baseline or mutant set was broken, not just "
            "below the floor",
            file=sys.stderr,
        )
    return 0 if all_above_floor else 1


if __name__ == "__main__":
    raise SystemExit(main())
