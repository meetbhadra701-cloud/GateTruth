"""Tests for the pull-request T1 reference smoke runner."""

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.ci_t1_smoke import (
    EXPECTED_T1_TASKS,
    REPO_ROOT,
    REFERENCE_SCORE,
    manifest_error,
    t1_task_ids,
)


def test_t1_selection_is_complete_and_deterministic() -> None:
    tasks = t1_task_ids()

    assert tasks == sorted(tasks)
    assert len(tasks) == EXPECTED_T1_TASKS
    assert all(task.startswith("t1_") for task in tasks)


def test_manifest_validation_rejects_score_or_gate_drift() -> None:
    passing = SimpleNamespace(
        task_score=REFERENCE_SCORE,
        stages=[
            SimpleNamespace(stage=0, name="lint", status="pass"),
            SimpleNamespace(stage=2, name="formal", status="skip"),
            SimpleNamespace(stage=5, name="power", status="pass"),
        ],
    )
    assert manifest_error(passing) is None

    wrong_score = SimpleNamespace(task_score=0.0, stages=passing.stages)
    assert "expected task_score" in manifest_error(wrong_score)

    failed_gate = SimpleNamespace(
        task_score=REFERENCE_SCORE,
        stages=[SimpleNamespace(stage=1, name="sim", status="fail")],
    )
    assert manifest_error(failed_gate) == "failed stages: 1:sim=fail"


def test_missing_t1_package_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "tasks").mkdir()

    with pytest.raises(ValueError, match="expected 20 T1 tasks, found 0"):
        t1_task_ids(tmp_path)


def test_standalone_cli_bootstraps_repository_imports(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "ci_t1_smoke.py"),
            "--help",
        ],
        cwd=tmp_path,
        env={"PATH": os.environ["PATH"]},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    assert result.returncode == 0, result.stdout
    assert "non-official T1 reference smoke" in result.stdout
