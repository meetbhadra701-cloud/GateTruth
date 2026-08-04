"""Run the bounded, no-network GateTruth final-acceptance probes."""

from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from harness.env_compat import read_env  # noqa: E402
from harness.runner import DEFAULT_DOCKER_DIGEST_FILE, run_task  # noqa: E402
from harness.schemas.canonical_json import compute_manifest_signature  # noqa: E402
from harness.schemas.manifest import load_manifest  # noqa: E402
from harness.schemas.manifest_b import load_agent_manifest_b  # noqa: E402
from harness.trackb import run_track_b  # noqa: E402
from harness.validation import MAX_SOURCE_BYTES  # noqa: E402

DETERMINISM_TASKS = (
    "t1_gray_counter",
    "t2_sync_fifo",
    "t3_hamming74_codec",
)
TRACK_A_MODELS = ("claude-opus-4-8", "claude-sonnet-4-6")
TRACK_B_MODEL = "claude-haiku-4-5-20251001"
TRACK_B_SEC_TASKS = (
    "b1_close_timing_mac",
    "b2_close_timing_multiplier",
    "b4_reduce_power_iir",
)


class AcceptanceError(RuntimeError):
    """Raised when one final-acceptance invariant is false."""


def _load_signed_json(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    actual = raw.get("signature")
    expected = compute_manifest_signature(raw)
    if actual != expected:
        raise AcceptanceError(f"signature mismatch: {path}")
    return raw


def _model_dir(root: Path, model: str) -> Path:
    path = root / model / model
    if not path.is_dir():
        raise AcceptanceError(f"model result directory missing: {path}")
    return path


def check_track_a(eval_root: Path) -> tuple[int, set[str]]:
    manifests = 0
    digests: set[str] = set()
    for model in TRACK_A_MODELS:
        root = _model_dir(eval_root, model)
        summary = _load_signed_json(root / "summary.json")
        if summary.get("official") is not True:
            raise AcceptanceError(f"Track A summary is not official: {model}")
        if len(summary.get("task_ids", [])) != 60:
            raise AcceptanceError(f"Track A task count is not 60: {model}")
        for task_id in summary["task_ids"]:
            task = summary["tasks"][task_id]
            if task.get("skipped"):
                raise AcceptanceError(f"Track A task unexpectedly skipped: {model}/{task_id}")
            for sample in task["samples"]:
                path = root / sample["manifest"]
                manifest = load_manifest(path)
                if manifest.signature != sample["manifest_signature"]:
                    raise AcceptanceError(f"Track A summary link mismatch: {path}")
                if manifest.task_id != task_id:
                    raise AcceptanceError(f"Track A task id mismatch: {path}")
                digests.add(manifest.docker_digest)
                manifests += 1
    print(f"CHECK3 PASS models=2 manifests={manifests} signed=true official=true")
    return manifests, digests


def check_track_b(eval_root: Path) -> tuple[int, set[str]]:
    root = _model_dir(eval_root, TRACK_B_MODEL)
    summary = _load_signed_json(root / "summary.json")
    if summary.get("official") is not True:
        raise AcceptanceError("Track B summary is not official")
    digests: set[str] = set()
    for task_id in TRACK_B_SEC_TASKS:
        path = root / summary["tasks"][task_id]["manifest"]
        # load_agent_manifest_b applies the same schema + semantic-rule
        # validation (field types, patterns, disqualified-must-score-zero,
        # ...) that check_track_a's load_manifest already applies to Track A
        # -- a raw signature-only dict read would let a malformed field slip
        # through this release gate on the Track B side alone.
        manifest = load_agent_manifest_b(path)
        if manifest.task_id != task_id:
            raise AcceptanceError(f"Track B task id mismatch: {path}")
        if manifest.sec.status != "pass":
            raise AcceptanceError(f"Track B SEC is not pass: {task_id}")
        if manifest.disqualified:
            raise AcceptanceError(f"Track B run is disqualified: {task_id}")
        digests.add(manifest.docker_digest)
    print("CHECK4 PASS agent=claude-haiku-4-5 tasks=3 sec=3/3 signed=true")
    return len(TRACK_B_SEC_TASKS), digests


def _run_reference(task_id: str, out: Path, *, official: bool) -> str:
    manifest = run_task(
        task_id,
        REPO_ROOT / "tasks" / task_id / "ref" / "ref.sv",
        out,
        official=official,
    )
    if manifest.task_score <= 0:
        raise AcceptanceError(f"reference failed: {task_id}")
    return manifest.signature


def _all_task_ids() -> list[str]:
    return sorted(path.parent.name for path in (REPO_ROOT / "tasks").glob("*/task.yaml"))


def check_determinism(
    root: Path,
    *,
    official: bool,
    baseline_dir: Path | None,
) -> None:
    if baseline_dir is not None:
        tasks = _all_task_ids()
        if len(tasks) != 60:
            raise AcceptanceError(f"expected 60 Track A tasks, found {len(tasks)}")
        baseline = {
            task_id: load_manifest(baseline_dir / f"{task_id}.json").signature
            for task_id in tasks
        }

        def rerun(task_id: str) -> tuple[str, str | None]:
            try:
                signature = _run_reference(
                    task_id,
                    root / "order-shuffled" / f"{task_id}.json",
                    official=official,
                )
            except AcceptanceError:
                signature = None
            return task_id, signature

        with ThreadPoolExecutor(max_workers=2) as pool:
            parallel_results = dict(pool.map(rerun, reversed(tasks)))
        retry_ids = sorted(
            task_id for task_id, signature in parallel_results.items() if signature is None
        )
        shuffled = {
            task_id: signature
            for task_id, signature in parallel_results.items()
            if signature is not None
        }
        for task_id in retry_ids:
            shuffled[task_id] = _run_reference(
                task_id,
                root / "order-shuffled-solo-retry" / f"{task_id}.json",
                official=official,
            )
        if baseline != shuffled:
            mismatches = sorted(
                task_id
                for task_id in tasks
                if baseline[task_id] != shuffled[task_id]
            )
            raise AcceptanceError(f"determinism mismatch: {mismatches}")
        print(
            "CHECK6 PASS shuffled_tasks=60 signature_matches=60/60 "
            f"contention_retries={len(retry_ids)}"
        )
        return

    first = {
        task_id: _run_reference(
            task_id,
            root / "order-a" / f"{task_id}.json",
            official=official,
        )
        for task_id in DETERMINISM_TASKS
    }
    second = {
        task_id: _run_reference(
            task_id,
            root / "order-b" / f"{task_id}.json",
            official=official,
        )
        for task_id in reversed(DETERMINISM_TASKS)
    }
    if first != second:
        raise AcceptanceError(f"determinism mismatch: {first!r} != {second!r}")
    print("CHECK6 PASS shuffled_tasks=3 signature_matches=3/3")


def check_submission_outcomes(root: Path, *, official: bool) -> None:
    task_id = "t1_gray_counter"
    reference = REPO_ROOT / "tasks" / task_id / "ref" / "ref.sv"
    source = reference.read_text(encoding="utf-8")
    baseline = run_task(
        task_id,
        reference,
        root / "baseline.json",
        official=official,
    )

    cosmetic = root / "cosmetic.sv"
    cosmetic.write_text(
        source + "\n// final-acceptance cosmetic-only change\n",
        encoding="utf-8",
    )
    cosmetic_manifest = run_task(
        task_id,
        cosmetic,
        root / "cosmetic.json",
        official=official,
    )
    if not math.isclose(
        baseline.task_score,
        cosmetic_manifest.task_score,
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise AcceptanceError("cosmetic source changed task score")
    print(f"CHECK7 PASS score={cosmetic_manifest.task_score:.12g}")

    corrupt = root / "corrupt.sv"
    corrupt.write_text(
        "module gray_counter; this is not valid SystemVerilog; endmodule\n",
        encoding="utf-8",
    )
    corrupt_out = root / "corrupt.json"
    corrupt_manifest = run_task(task_id, corrupt, corrupt_out, official=official)
    if corrupt_manifest.task_score != 0.0 or not corrupt_out.with_suffix(".log").is_file():
        raise AcceptanceError("corrupt source did not produce a complete score-zero result")
    print("CHECK8 PASS corrupt_score=0 manifest=true log=true")

    oversized = root / "oversized-valid.sv"
    padding = MAX_SOURCE_BYTES - len(source.encode("utf-8")) + 4096
    oversized.write_text(
        source + "\n/*" + ("x" * padding) + "*/\n",
        encoding="utf-8",
    )
    oversized_out = root / "oversized.json"
    oversized_manifest = run_task(
        task_id,
        oversized,
        oversized_out,
        official=official,
    )
    oversized_log = oversized_out.with_suffix(".log").read_text(encoding="utf-8")
    if oversized_manifest.task_score != 0.0 or "rejected before tool" not in oversized_log:
        raise AcceptanceError("oversized valid source was not rejected before tools")

    empty = root / "empty.sv"
    empty.write_text("module gray_counter; endmodule\n", encoding="utf-8")
    empty_manifest = run_task(
        task_id,
        empty,
        root / "empty.json",
        official=official,
    )
    if empty_manifest.task_score != 0.0:
        raise AcceptanceError("empty module did not score zero")
    print(
        f"CHECK9 PASS oversized_bytes={oversized.stat().st_size} "
        "oversized_score=0 pretool=true empty_score=0"
    )


def check_track_b_tamper(root: Path, *, official: bool) -> None:
    task_id = "b8_axi_byte_enables"
    submission = root / task_id
    shutil.copytree(REPO_ROOT / "tasksB" / task_id, submission)
    testbench = next((submission / "tb").glob("test_*.py"))
    testbench.write_text(
        testbench.read_text(encoding="utf-8") + "\n# tamper probe\n",
        encoding="utf-8",
    )
    manifest = run_track_b(
        task_id,
        submission,
        root / "trackb-tamper.json",
        official=official,
    )
    if not manifest.disqualified or "immutable file differs: tb" not in (
        manifest.disqualification_reason or ""
    ):
        raise AcceptanceError("Track B testbench tamper was not disqualified")
    print("CHECK10 PASS disqualified=true reason=immutable_file_differs_tb")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eval-root", type=Path, default=Path("results/eval/official"))
    parser.add_argument("--agent-eval-root", type=Path, default=Path("results/evalB/official"))
    parser.add_argument("--determinism-baseline", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    official = bool(read_env("HIDDEN_ROOT"))

    track_a_count, track_a_digests = check_track_a(args.eval_root)
    track_b_count, track_b_digests = check_track_b(args.agent_eval_root)
    marker = DEFAULT_DOCKER_DIGEST_FILE.read_text(encoding="utf-8").strip()
    artifact_digests = track_a_digests | track_b_digests
    if artifact_digests != {marker}:
        raise AcceptanceError(
            f"artifact image markers differ: {artifact_digests!r} != {marker!r}"
        )
    print(
        f"CHECK1 PASS image_marker={marker} "
        f"signed_artifacts={track_a_count + track_b_count}"
    )

    with tempfile.TemporaryDirectory(
        prefix="gatetruth-final-acceptance-",
        dir=args.out,
    ) as temp:
        root = Path(temp)
        check_determinism(
            root,
            official=official,
            baseline_dir=args.determinism_baseline,
        )
        check_submission_outcomes(root, official=official)
        check_track_b_tamper(root, official=official)
    print("FINAL_ACCEPTANCE_PROBE PASS checks=1,3,4,6,7,8,9,10")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
