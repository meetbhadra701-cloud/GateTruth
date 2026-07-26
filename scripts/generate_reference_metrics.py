"""Generate the committed Track A PPA normalization table."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from harness.schemas.manifest import ResultManifest, load_manifest  # noqa: E402
from harness.schemas.task_yaml import load_task_yaml  # noqa: E402
from harness.scoring import (  # noqa: E402
    REFERENCE_METRICS_PATH,
    REFERENCE_METRICS_VERSION,
    PpaMetrics,
    delay_from_wns,
)

EXPECTED_TASKS = 60


def generate_reference_metrics(
    *,
    input_dir: str | Path,
    tasks_root: str | Path = REPO_ROOT / "tasks",
) -> dict[str, Any]:
    """Build a deterministic table from signed reference result manifests."""

    source = Path(input_dir)
    task_paths = sorted(Path(tasks_root).glob("*/task.yaml"))
    if len(task_paths) != EXPECTED_TASKS:
        raise ValueError(
            f"expected {EXPECTED_TASKS} Track A tasks, found {len(task_paths)}"
        )
    task_ids = {path.parent.name for path in task_paths}
    manifest_ids = {path.stem for path in source.glob("*.json")}
    if manifest_ids != task_ids:
        missing = sorted(task_ids - manifest_ids)
        extra = sorted(manifest_ids - task_ids)
        raise ValueError(
            f"reference manifest set mismatch: missing={missing}, extra={extra}"
        )

    records: dict[str, dict[str, Any]] = {}
    digests: set[str] = set()
    for task_path in task_paths:
        task = load_task_yaml(task_path)
        manifest_path = source / f"{task.id}.json"
        manifest = load_manifest(manifest_path)
        if manifest.task_id != task.id:
            raise ValueError(
                f"reference manifest id mismatch: {manifest_path} "
                f"contains {manifest.task_id}"
            )
        metrics = _manifest_metrics(manifest, task.clock_target_ns)
        records[task.id] = {
            "area_um2": metrics.area_um2,
            "clock_target_ns": metrics.clock_target_ns,
            "delay_ns": metrics.delay_ns,
            "power_mw": metrics.power_mw,
            "source_manifest_signature": manifest.signature,
            "wns_ns": task.clock_target_ns - metrics.delay_ns,
        }
        digests.add(manifest.docker_digest)

    if len(records) != EXPECTED_TASKS:
        raise ValueError(
            f"expected {EXPECTED_TASKS} reference manifests, found {len(records)}"
        )
    if len(digests) != 1:
        raise ValueError("reference manifests do not share one Docker digest")
    return {
        "schema_version": REFERENCE_METRICS_VERSION,
        "suite_version": "v0.2",
        "docker_digest": next(iter(digests)),
        "delay_definition": "clock_target_ns - wns_ns",
        "generated_from": "signed results/refs/<task_id>.json manifests",
        "tasks": records,
    }


def _manifest_metrics(
    manifest: ResultManifest,
    clock_target_ns: float,
) -> PpaMetrics:
    stages = {stage.stage: stage for stage in manifest.stages}
    for stage_id in range(6):
        stage = stages.get(stage_id)
        if stage is None or stage.status not in {"pass", "skip"}:
            raise ValueError(
                f"reference {manifest.task_id} does not pass stage {stage_id}"
            )
    synth = stages[3]
    sta = stages[4]
    power = stages[5]
    if (
        synth.area_um2 is None
        or sta.wns_ns is None
        or power.power_mw is None
    ):
        raise ValueError(f"reference {manifest.task_id} is missing PPA metrics")
    return PpaMetrics(
        area_um2=synth.area_um2,
        delay_ns=delay_from_wns(clock_target_ns, sta.wns_ns),
        power_mw=power.power_mw,
        clock_target_ns=clock_target_ns,
    )


def _render(raw: dict[str, Any]) -> str:
    return json.dumps(raw, indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", default="results/refs")
    parser.add_argument("--tasks-root", default="tasks")
    parser.add_argument("--out", default=str(REFERENCE_METRICS_PATH))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    try:
        rendered = _render(
            generate_reference_metrics(
                input_dir=args.input_dir,
                tasks_root=args.tasks_root,
            )
        )
        output = Path(args.out)
        if args.check:
            if not output.is_file() or output.read_text(encoding="utf-8") != rendered:
                print(f"reference metrics are stale: {output}", file=sys.stderr)
                return 1
            print("reference metrics check: PASS (60 tasks)")
            return 0
        if output.is_file() and output.read_text(encoding="utf-8") == rendered:
            print(f"reference metrics unchanged: {output}")
            return 0
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8", newline="\n")
        print(f"wrote {len(json.loads(rendered)['tasks'])} tasks to {output}")
        return 0
    except (OSError, ValueError) as exc:
        print(f"reference metrics generation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
