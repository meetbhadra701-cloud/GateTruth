"""End-to-end checks for the public Track B manifest reproducer."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from harness.agentb import run_agent_task
from harness.providers.mock import MockProvider
from harness.schemas.canonical_json import compute_manifest_signature
from harness.trackb import run_track_b

REPO_ROOT = Path(__file__).resolve().parents[2]
TASK_ID = "toy_taskB"
SOLUTION = REPO_ROOT / "harness" / "tests" / "fixtures" / "toy_taskB_solution" / "toy_trackb.sv"
SCRIPT = REPO_ROOT / "scripts" / "reproduce_trackb.py"


@pytest.fixture(scope="module")
def fresh_agent_manifest(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("reproduce-trackb") / "agent.json"
    script = [
        {"tool": "write_design", "content": SOLUTION.read_text(encoding="utf-8")},
        {"tool": "done"},
    ]
    run_agent_task(TASK_ID, MockProvider(script), out=path)
    return path


def _run_reproducer(
    path: Path, *, official: bool | None = None, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    args = [sys.executable, str(SCRIPT), str(path)]
    if official is True:
        args.append("--official")
    elif official is False:
        args.append("--no-official")
    return subprocess.run(
        args,
        cwd=REPO_ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
        env=env,
    )


def test_fresh_agent_manifest_reproduces(fresh_agent_manifest: Path) -> None:
    result = _run_reproducer(fresh_agent_manifest)

    assert result.returncode == 0, result.stderr
    assert f"MATCH task={TASK_ID}" in result.stdout
    assert "official=False" in result.stdout


def test_resigned_tampered_score_is_detected(
    fresh_agent_manifest: Path, tmp_path: Path
) -> None:
    raw = json.loads(fresh_agent_manifest.read_text(encoding="utf-8"))
    raw["task_score"] = 0.0
    raw["objective_pass"] = False
    raw["signature"] = compute_manifest_signature(raw)
    tampered = tmp_path / "tampered.json"
    tampered.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    shutil.copy2(fresh_agent_manifest.with_suffix(".sv"), tampered.with_suffix(".sv"))

    result = _run_reproducer(tampered)

    assert result.returncode == 1
    assert "MISMATCH" in result.stderr
    assert '"task_score": 0.0' in result.stderr
    assert '"task_score": 100.0' in result.stderr


def test_tampered_design_sidecar_is_detected(
    fresh_agent_manifest: Path, tmp_path: Path
) -> None:
    tampered = tmp_path / "tampered_design.json"
    shutil.copy2(fresh_agent_manifest, tampered)
    sidecar = tampered.with_suffix(".sv")
    sidecar.write_text(
        fresh_agent_manifest.with_suffix(".sv").read_text(encoding="utf-8") + "\n// tampered\n",
        encoding="utf-8",
    )

    result = _run_reproducer(tampered)

    assert result.returncode == 2
    assert "does not match the recorded submission_sha256" in result.stderr


def test_missing_sidecar_fails_closed(fresh_agent_manifest: Path, tmp_path: Path) -> None:
    manifest_only = tmp_path / "no_sidecar.json"
    shutil.copy2(fresh_agent_manifest, manifest_only)

    result = _run_reproducer(manifest_only)

    assert result.returncode == 2
    assert "design not found" in result.stderr


def test_bare_evaluator_manifest_without_budget_exceeded_reproduces(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """run_track_b() (no agent driver) still produces a real TrackBManifest, not an
    AgentTrackBManifest -- no budget_exceeded field at all, not even null. The
    reproducer must load and reproduce this shape too, not only agent-driven runs."""

    work = tmp_path_factory.mktemp("reproduce-trackb-bare")
    submission = work / "submission"
    shutil.copytree(REPO_ROOT / "harness" / "tests" / "fixtures" / "toy_taskB", submission)
    shutil.copy2(SOLUTION, submission / "design" / "toy_trackb.sv")
    manifest_path = work / "bare.json"
    run_track_b(TASK_ID, submission, manifest_path)
    shutil.copy2(SOLUTION, manifest_path.with_suffix(".sv"))

    result = _run_reproducer(manifest_path)

    assert result.returncode == 0, result.stderr
    assert f"MATCH task={TASK_ID}" in result.stdout


def test_official_mode_is_inferred_from_hidden_module_sha256_without_the_flag(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """Mirrors harness/tests/test_reproduce.py's Track A equivalent: TrackBManifest now
    records hidden_module_sha256 whenever a real hidden-vector mount was resolved
    during an official Track B run, and reproduce_trackb.py should infer official mode
    from that alone."""

    import os

    hidden_root = REPO_ROOT.parent / "codex-SB-101" / "build" / "hidden-staging"
    if not hidden_root.is_dir():
        pytest.skip("real hidden-staging tree not present on this machine")

    env = dict(os.environ)
    env["GATETRUTH_HIDDEN_ROOT"] = str(hidden_root)

    task_id = "b1_close_timing_mac"
    work = tmp_path_factory.mktemp("reproduce-trackb-official")
    submission = work / "submission"
    subprocess.run(
        [
            sys.executable,
            "-c",
            "from harness.trackb import resolve_track_b_task, run_track_b; import shutil; "
            f"package = resolve_track_b_task({task_id!r}); "
            f"shutil.copytree(package.root, {str(submission)!r}); "
            f"run_track_b({task_id!r}, {str(submission)!r}, {str(work / 'official.json')!r}, official=True)",
        ],
        cwd=REPO_ROOT,
        env=env,
        check=True,
        timeout=120,
    )
    official_path = work / "official.json"
    shutil.copy2(submission / "design" / "mac.sv", official_path.with_suffix(".sv"))
    recorded = json.loads(official_path.read_text(encoding="utf-8"))
    assert recorded["hidden_module_sha256"], "fixture setup did not actually score officially"

    result = _run_reproducer(official_path, env=env)

    assert result.returncode == 0, result.stderr
    assert f"MATCH task={task_id}" in result.stdout
    assert "official=True" in result.stdout

    env_without_root = dict(os.environ)
    env_without_root.pop("GATETRUTH_HIDDEN_ROOT", None)
    env_without_root.pop("SILICONBENCH_HIDDEN_ROOT", None)
    result = _run_reproducer(official_path, env=env_without_root)

    assert result.returncode != 0
    assert "MATCH task=" not in result.stdout
