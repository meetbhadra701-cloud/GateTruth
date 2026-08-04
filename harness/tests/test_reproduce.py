"""End-to-end checks for the public manifest reproducer."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from harness.runner import run_task
from harness.schemas.canonical_json import compute_manifest_signature

REPO_ROOT = Path(__file__).resolve().parents[2]
TASK_ID = "t1_gray_counter"
REFERENCE = REPO_ROOT / "tasks" / TASK_ID / "ref" / "ref.sv"
SCRIPT = REPO_ROOT / "scripts" / "reproduce.py"


@pytest.fixture(scope="module")
def fresh_reference_manifest(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("reproduce") / "reference.json"
    run_task(TASK_ID, REFERENCE, path)
    return path


def _run_reproducer(
    path: Path, *, official: bool = False, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    args = [sys.executable, str(SCRIPT), str(path)]
    if official:
        args.append("--official")
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


def test_fresh_reference_manifest_reproduces(
    fresh_reference_manifest: Path,
) -> None:
    result = _run_reproducer(fresh_reference_manifest)

    assert result.returncode == 0, result.stderr
    assert f"MATCH task={TASK_ID}" in result.stdout
    assert "signature=" in result.stdout


def test_resigned_tampered_score_is_detected(
    fresh_reference_manifest: Path,
    tmp_path: Path,
) -> None:
    raw = json.loads(fresh_reference_manifest.read_text(encoding="utf-8"))
    raw["task_score"] = 0.0
    raw["signature"] = compute_manifest_signature(raw)
    tampered = tmp_path / "tampered.json"
    tampered.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")

    result = _run_reproducer(tampered)

    assert result.returncode == 1
    assert "MISMATCH" in result.stderr
    assert '"task_score": 0.0' in result.stderr
    assert '"task_score": 66.66666666666667' in result.stderr


def test_forced_official_flag_without_hidden_root_fails_closed(
    fresh_reference_manifest: Path,
) -> None:
    """fresh_reference_manifest was produced non-officially, so auto-inference alone
    would already choose official=False here -- this test specifically forces
    --official to prove the explicit-override path also fails closed rather than
    silently reporting a false MATCH when no hidden root is mounted."""

    import os

    env = dict(os.environ)
    env.pop("GATETRUTH_HIDDEN_ROOT", None)
    env.pop("SILICONBENCH_HIDDEN_ROOT", None)

    result = _run_reproducer(fresh_reference_manifest, official=True, env=env)

    assert result.returncode != 0
    assert "MATCH task=" not in result.stdout


def test_official_mode_is_inferred_from_hidden_module_sha256_without_the_flag(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """The manifest schema now records hidden_module_sha256 whenever a real
    hidden-vector mount was resolved during an official run -- reproduce.py should
    use that to infer official mode automatically, not require the caller to
    separately remember and pass --official."""

    import os

    hidden_root = REPO_ROOT.parent / "codex-SB-101" / "build" / "hidden-staging"
    if not hidden_root.is_dir():
        pytest.skip("real hidden-staging tree not present on this machine")

    env = dict(os.environ)
    env["GATETRUTH_HIDDEN_ROOT"] = str(hidden_root)

    official_path = tmp_path_factory.mktemp("reproduce-official") / "official.json"
    subprocess.run(
        [
            sys.executable,
            "-c",
            "from harness.runner import run_task; import sys; "
            f"run_task({TASK_ID!r}, {str(REFERENCE)!r}, {str(official_path)!r}, official=True)",
        ],
        cwd=REPO_ROOT,
        env=env,
        check=True,
        timeout=120,
    )
    recorded = json.loads(official_path.read_text(encoding="utf-8"))
    assert recorded["hidden_module_sha256"], "fixture setup did not actually score officially"

    # No --official flag passed; auto-inference must still choose official=True and
    # therefore still require (and here, receive) the hidden root to reproduce correctly.
    result = _run_reproducer(official_path, env=env)

    assert result.returncode == 0, result.stderr
    assert f"MATCH task={TASK_ID}" in result.stdout
    assert "official=True" in result.stdout

    # Same manifest, no hidden root this time, still no --official flag: auto-inference
    # must still choose official=True from hidden_module_sha256 alone and therefore still
    # fail closed, not silently fall back to a non-official (and therefore vacuous) match.
    env_without_root = dict(os.environ)
    env_without_root.pop("GATETRUTH_HIDDEN_ROOT", None)
    env_without_root.pop("SILICONBENCH_HIDDEN_ROOT", None)
    result = _run_reproducer(official_path, env=env_without_root)

    assert result.returncode != 0
    assert "MATCH task=" not in result.stdout
