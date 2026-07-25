"""Capture or compare all hidden-freeze task manifest signatures."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from harness.hidden import HIDDEN_LOADED_KEY, HIDDEN_ROOT_ENV  # noqa: E402
from harness.runner import run_task  # noqa: E402
from harness.trackb import run_track_b  # noqa: E402


def all_task_ids(root: Path = REPO_ROOT) -> list[str]:
    track_a = sorted(path.parent.name for path in (root / "tasks").glob("*/task.yaml"))
    track_b = sorted(path.parent.name for path in (root / "tasksB").glob("*/task.yaml"))
    return track_a + track_b


def run_manifest(
    task_id: str,
    out: Path,
    *,
    official: bool,
    root: Path = REPO_ROOT,
) -> str:
    if (root / "tasks" / task_id / "task.yaml").is_file():
        manifest = run_task(
            task_id,
            root / "tasks" / task_id / "ref" / "ref.sv",
            out,
            official=official,
        )
    elif (root / "tasksB" / task_id / "task.yaml").is_file():
        manifest = run_track_b(
            task_id,
            root / "tasksB" / task_id,
            out,
            official=official,
        )
    else:
        raise ValueError(f"unknown task: {task_id}")
    return manifest.signature


def capture(tasks: list[str], destination: Path) -> int:
    os.environ.pop(HIDDEN_ROOT_ENV, None)
    destination.mkdir(parents=True, exist_ok=True)
    for task_id in tasks:
        signature = run_manifest(
            task_id,
            destination / f"{task_id}.json",
            official=False,
        )
        print(f"captured {task_id} {signature}")
    return 0


def compare(
    tasks: list[str],
    baseline: Path,
    destination: Path,
    hidden_root: Path,
) -> int:
    os.environ[HIDDEN_ROOT_ENV] = str(hidden_root.resolve())
    destination.mkdir(parents=True, exist_ok=True)
    mismatches: list[str] = []
    for task_id in tasks:
        baseline_path = baseline / f"{task_id}.json"
        if not baseline_path.is_file():
            raise FileNotFoundError(f"baseline manifest missing: {baseline_path}")
        expected = json.loads(baseline_path.read_text(encoding="utf-8"))["signature"]
        actual = run_manifest(
            task_id,
            destination / f"{task_id}.json",
            official=True,
        )
        status = "MATCH" if actual == expected else "MISMATCH"
        print(f"{status} {task_id} expected={expected} actual={actual}")
        if actual != expected:
            mismatches.append(task_id)
    if mismatches:
        print("hidden-freeze signature mismatches: " + ", ".join(mismatches), file=sys.stderr)
        return 1
    print(f"hidden-freeze signatures match: {len(tasks)}/{len(tasks)}")
    return 0


def check_loaders(
    tasks: list[str],
    hidden_root: Path,
    root: Path = REPO_ROOT,
) -> int:
    """Import every split public testbench and require a positive hidden count."""

    os.environ[HIDDEN_ROOT_ENV] = str(hidden_root.resolve())
    total = 0
    for task_id in tasks:
        kind = "tasks" if (root / "tasks" / task_id).is_dir() else "tasksB"
        testbenches = sorted((root / kind / task_id / "tb").glob("test_*.py"))
        if len(testbenches) != 1:
            raise ValueError(f"expected one testbench for {task_id}")
        module_name = f"_siliconbench_freeze_check_{task_id}"
        spec = importlib.util.spec_from_file_location(module_name, testbenches[0])
        if spec is None or spec.loader is None:
            raise ValueError(f"cannot import testbench for {task_id}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        finally:
            sys.modules.pop(module_name, None)
        count = getattr(module, HIDDEN_LOADED_KEY, 0)
        if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
            raise ValueError(f"hidden tests did not load for {task_id}: {count!r}")
        total += count
        print(f"loaded {task_id} hidden_tests={count}")
    print(f"hidden loader check: tasks={len(tasks)} tests={total}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--capture", type=Path, metavar="DIR")
    mode.add_argument("--compare", type=Path, metavar="BASELINE_DIR")
    mode.add_argument("--check-loaders", action="store_true")
    parser.add_argument("--out", type=Path, default=Path("build/hidden-verification"))
    parser.add_argument("--hidden-root", type=Path)
    parser.add_argument("--tasks", help="comma-separated subset; default is all 68")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    available = all_task_ids()
    tasks = (
        [item.strip() for item in args.tasks.split(",") if item.strip()]
        if args.tasks
        else available
    )
    unknown = sorted(set(tasks) - set(available))
    if unknown:
        raise ValueError("unknown tasks: " + ", ".join(unknown))
    if args.capture is not None:
        return capture(tasks, args.capture)
    if args.check_loaders:
        if args.hidden_root is None:
            raise ValueError("--hidden-root is required with --check-loaders")
        return check_loaders(tasks, args.hidden_root)
    if args.hidden_root is None:
        raise ValueError("--hidden-root is required with --compare")
    return compare(tasks, args.compare, args.out, args.hidden_root)


if __name__ == "__main__":
    raise SystemExit(main())
