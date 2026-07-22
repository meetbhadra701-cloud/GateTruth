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


def _run_reproducer(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(path)],
        cwd=REPO_ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
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
