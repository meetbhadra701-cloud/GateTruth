import subprocess
import sys
import shutil

from harness.runner import TaskPackage, run_ppa_flows, runtime_docker_digest
from harness.schemas.manifest import load_manifest
from harness.schemas.task_yaml import load_task_yaml


def test_toy_flow_determinism(tmp_path):
    left = tmp_path / "toy_a.json"
    right = tmp_path / "toy_b.json"
    command = [
        sys.executable,
        "-m",
        "harness.cli",
        "run",
        "--task",
        "toy_task",
        "--submission",
        "harness/tests/fixtures/toy_task/ref/ref.sv",
    ]
    subprocess.run([*command, "--out", str(left)], check=True)
    subprocess.run([*command, "--out", str(right)], check=True)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "harness.tests.assert_manifest_equal_except",
            str(left),
            str(right),
            "timestamp",
            "signature",
            "wall_clock_s",
        ],
        check=True,
    )
    manifest = load_manifest(left)
    stages = {stage.stage: stage for stage in manifest.stages}
    assert stages[3].status == "pass"
    assert stages[3].area_um2 > 0
    assert stages[3].cell_count > 0
    assert stages[4].status == "pass"
    assert stages[4].wns_ns > 0
    assert stages[4].tns_ns == 0
    assert stages[4].fmax_mhz > 0
    assert stages[5].status == "pass"
    assert stages[5].power_mw >= 0


def test_negative_timing_slack_fails_sta_stage(tmp_path):
    task_root = tmp_path / "toy_tight_clock"
    shutil.copytree("harness/tests/fixtures/toy_task", task_root)
    task_yaml_path = task_root / "task.yaml"
    task_yaml_path.write_text(
        task_yaml_path.read_text(encoding="utf-8").replace("clock_target_ns: 10.0", "clock_target_ns: 0.1"),
        encoding="utf-8",
    )
    (task_root / "constraints.sdc").write_text(
        "create_clock -name clk -period 0.1 [get_ports clk]\n"
        "set_input_delay -clock clk 0.0 [get_ports {rst a}]\n"
        "set_output_delay -clock clk 0.0 [get_ports y]\n",
        encoding="utf-8",
    )
    task = TaskPackage(
        task_id="toy_task",
        root=task_root,
        task_yaml=load_task_yaml(task_yaml_path),
        top_module="toy",
    )

    work_root = tmp_path / "work"
    work_root.mkdir()
    stages, _log = run_ppa_flows(task, task_root / "ref" / "ref.sv", work_root)
    by_stage = {stage["stage"]: stage for stage in stages}

    assert by_stage[3]["status"] == "pass"
    assert by_stage[4]["status"] == "fail"
    assert by_stage[4]["wns_ns"] < 0
    assert by_stage[4]["tns_ns"] < 0
    assert by_stage[5]["status"] == "pass"


def test_runtime_docker_digest_tracks_baked_file(tmp_path, monkeypatch):
    rebuilt_digest = "sha256:" + "ab" * 32
    digest_file = tmp_path / "image-digest"
    digest_file.write_text(rebuilt_digest + "\n", encoding="utf-8")
    monkeypatch.delenv("SILICONBENCH_DOCKER_DIGEST", raising=False)
    monkeypatch.setenv("SILICONBENCH_DOCKER_DIGEST_FILE", str(digest_file))

    assert runtime_docker_digest() == rebuilt_digest
