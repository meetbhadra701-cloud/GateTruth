import json
import subprocess
import sys

from harness.schemas.manifest import load_manifest


def test_score_cli_prints_task_score():
    result = subprocess.run(
        [sys.executable, "-m", "harness.cli", "score", "--manifest", "harness/tests/fixtures/valid_manifest.json"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )

    assert result.stdout.strip() == "66.6666666667"


def test_assert_score_reference_helper():
    subprocess.run(
        [sys.executable, "-m", "harness.tests.assert_score", "harness/tests/fixtures/valid_manifest.json", "--reference"],
        check=True,
    )


def test_run_toy_fixture_reference(tmp_path):
    out = tmp_path / "toy_manifest.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "harness.cli",
            "run",
            "--task",
            "toy_task",
            "--submission",
            "harness/tests/fixtures/toy_task/ref/ref.sv",
            "--out",
            str(out),
        ],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )

    manifest = load_manifest(out)
    assert "task_score=" in result.stdout
    assert manifest.task_id == "toy_task"
    assert {stage.stage: stage.status for stage in manifest.stages}[0] == "pass"
    assert {stage.stage: stage.status for stage in manifest.stages}[1] == "pass"
    assert {stage.stage: stage.status for stage in manifest.stages}[2] == "skip"
    assert json.loads(out.read_text())["signature"] == manifest.signature
