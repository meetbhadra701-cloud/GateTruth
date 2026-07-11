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


def test_run_partial_sim_failure_emits_score_zero_manifest(tmp_path):
    bad_popcount = tmp_path / "bad_popcount.sv"
    out = tmp_path / "bad_popcount_manifest.json"
    bad_popcount.write_text(
        "module popcount #(parameter int WIDTH=8)(input logic clk,input logic rst,\n"
        "  input logic [WIDTH-1:0] in, output logic [$clog2(WIDTH+1)-1:0] out);\n"
        "  always_ff @(posedge clk) out <= ($clog2(WIDTH+1))'(0);\n"
        "endmodule\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "harness.cli",
            "run",
            "--task",
            "t1_popcount",
            "--submission",
            str(bad_popcount),
            "--out",
            str(out),
        ],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )

    manifest = load_manifest(out)
    stages = {stage.stage: stage for stage in manifest.stages}

    assert "task_score=0.0" in result.stdout
    assert manifest.task_score == 0.0
    assert manifest.ppa == 0.0
    assert stages[1].status == "fail"
    assert stages[1].tests_run is None
    assert stages[1].tests_passed is None
