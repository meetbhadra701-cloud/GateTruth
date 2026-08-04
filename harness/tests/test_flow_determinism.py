import subprocess
import sys
import shutil
import time

from pathlib import Path

from harness import flows
from harness.flows import PowerResult, StaResult, SynthResult
from harness import runner
from harness.runner import (
    TaskPackage,
    run_ppa_flows,
    run_task,
    runtime_docker_digest,
    runtime_docker_digest_info,
)
from harness.schemas.manifest import load_manifest
from harness.schemas.task_yaml import load_task_yaml

TOY_REF = Path("harness/tests/fixtures/toy_task/ref/ref.sv")


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
    assert "wns_ns" not in by_stage[4]
    assert "tns_ns" not in by_stage[4]
    assert by_stage[5]["status"] == "pass"


def test_zero_ppa_metrics_fail_stages_without_crashing(tmp_path, monkeypatch):
    task_root = tmp_path / "toy_zero_metrics"
    shutil.copytree("harness/tests/fixtures/toy_task", task_root)
    task = TaskPackage(
        task_id="toy_task",
        root=task_root,
        task_yaml=load_task_yaml(task_root / "task.yaml"),
        top_module="toy",
    )
    netlist = tmp_path / "netlist.v"
    netlist.write_text("module toy; endmodule\n", encoding="utf-8")
    monkeypatch.setattr(
        runner,
        "run_synth",
        lambda **_kwargs: SynthResult(netlist, 0.0, 1, "synth"),
    )
    monkeypatch.setattr(
        runner,
        "run_sta",
        lambda **_kwargs: StaResult(10.0, 0.0, 0.0, "sta"),
    )
    monkeypatch.setattr(
        runner,
        "run_power",
        lambda **_kwargs: PowerResult(0.0, "power"),
    )

    stages, log = run_ppa_flows(
        task,
        task_root / "ref" / "ref.sv",
        tmp_path,
    )

    assert [stage["status"] for stage in stages] == ["fail", "fail", "fail"]
    assert all(
        not ({"area_um2", "wns_ns", "power_mw"} & set(stage))
        for stage in stages
    )
    assert "invalid scoring metric" in log


def test_runtime_docker_digest_tracks_baked_file(tmp_path, monkeypatch):
    rebuilt_digest = "sha256:" + "ab" * 32
    digest_file = tmp_path / "image-digest"
    digest_file.write_text(rebuilt_digest + "\n", encoding="utf-8")
    monkeypatch.delenv("GATETRUTH_DOCKER_DIGEST", raising=False)
    monkeypatch.delenv("SILICONBENCH_DOCKER_DIGEST", raising=False)
    monkeypatch.delenv("GATETRUTH_DOCKER_DIGEST_FILE", raising=False)
    monkeypatch.setenv("SILICONBENCH_DOCKER_DIGEST_FILE", str(digest_file))

    assert runtime_docker_digest() == rebuilt_digest


def test_runtime_docker_digest_prefers_gatetruth_variables(tmp_path, monkeypatch):
    primary_digest = "sha256:" + "12" * 32
    legacy_digest = "sha256:" + "34" * 32
    primary_file = tmp_path / "gatetruth-digest"
    legacy_file = tmp_path / "legacy-digest"
    primary_file.write_text(primary_digest + "\n", encoding="utf-8")
    legacy_file.write_text(legacy_digest + "\n", encoding="utf-8")
    monkeypatch.delenv("GATETRUTH_DOCKER_DIGEST", raising=False)
    monkeypatch.delenv("SILICONBENCH_DOCKER_DIGEST", raising=False)
    monkeypatch.setenv("GATETRUTH_DOCKER_DIGEST_FILE", str(primary_file))
    monkeypatch.setenv("SILICONBENCH_DOCKER_DIGEST_FILE", str(legacy_file))

    assert runtime_docker_digest() == primary_digest


def test_runtime_docker_digest_checks_primary_then_legacy_default_files(
    tmp_path,
    monkeypatch,
):
    primary_digest = "sha256:" + "56" * 32
    legacy_digest = "sha256:" + "78" * 32
    primary_file = tmp_path / "gatetruth-image-digest"
    legacy_file = tmp_path / "legacy-image-digest"
    legacy_file.write_text(legacy_digest + "\n", encoding="utf-8")
    monkeypatch.delenv("GATETRUTH_DOCKER_DIGEST", raising=False)
    monkeypatch.delenv("SILICONBENCH_DOCKER_DIGEST", raising=False)
    monkeypatch.delenv("GATETRUTH_DOCKER_DIGEST_FILE", raising=False)
    monkeypatch.delenv("SILICONBENCH_DOCKER_DIGEST_FILE", raising=False)
    monkeypatch.setattr(runner, "DEFAULT_DOCKER_DIGEST_FILE", primary_file)
    monkeypatch.setattr(runner, "LEGACY_DOCKER_DIGEST_FILE", legacy_file)

    assert runtime_docker_digest() == legacy_digest

    primary_file.write_text(primary_digest + "\n", encoding="utf-8")
    assert runtime_docker_digest() == primary_digest


def test_runtime_docker_digest_info_reports_env_as_the_source(monkeypatch):
    monkeypatch.setenv("GATETRUTH_DOCKER_DIGEST", "sha256:" + "aa" * 32)

    digest, source = runtime_docker_digest_info()

    assert digest == "sha256:" + "aa" * 32
    assert source == "env"


def test_runtime_docker_digest_info_reports_file_as_the_source(tmp_path, monkeypatch):
    digest_file = tmp_path / "image-digest"
    digest_file.write_text("sha256:" + "bb" * 32 + "\n", encoding="utf-8")
    monkeypatch.delenv("GATETRUTH_DOCKER_DIGEST", raising=False)
    monkeypatch.delenv("SILICONBENCH_DOCKER_DIGEST", raising=False)
    monkeypatch.setenv("GATETRUTH_DOCKER_DIGEST_FILE", str(digest_file))

    digest, source = runtime_docker_digest_info()

    assert digest == "sha256:" + "bb" * 32
    assert source == "file"


def test_runtime_docker_digest_info_reports_default_as_the_source(tmp_path, monkeypatch):
    monkeypatch.delenv("GATETRUTH_DOCKER_DIGEST", raising=False)
    monkeypatch.delenv("SILICONBENCH_DOCKER_DIGEST", raising=False)
    monkeypatch.delenv("GATETRUTH_DOCKER_DIGEST_FILE", raising=False)
    monkeypatch.delenv("SILICONBENCH_DOCKER_DIGEST_FILE", raising=False)
    monkeypatch.setattr(runner, "DEFAULT_DOCKER_DIGEST_FILE", tmp_path / "absent-primary")
    monkeypatch.setattr(runner, "LEGACY_DOCKER_DIGEST_FILE", tmp_path / "absent-legacy")

    digest, source = runtime_docker_digest_info()

    assert digest == runner.DEFAULT_DOCKER_DIGEST
    assert source == "default"


def test_run_task_manifest_records_which_digest_source_actually_scored_it(
    tmp_path, monkeypatch
):
    """P0-7: a manifest's docker_digest is meaningless without knowing whether it came
    from an operator-verified `docker inspect` (env) or a self-declared, unverifiable
    fallback (file/default) -- see runtime_docker_digest_info()'s docstring for why
    those are not equivalent claims."""

    monkeypatch.setenv("GATETRUTH_DOCKER_DIGEST", "sha256:" + "cc" * 32)
    manifest = run_task("toy_task", TOY_REF, tmp_path / "env.json")
    assert manifest.docker_digest == "sha256:" + "cc" * 32
    assert manifest.docker_digest_source == "env"

    monkeypatch.delenv("GATETRUTH_DOCKER_DIGEST", raising=False)
    monkeypatch.delenv("SILICONBENCH_DOCKER_DIGEST", raising=False)
    monkeypatch.delenv("GATETRUTH_DOCKER_DIGEST_FILE", raising=False)
    monkeypatch.delenv("SILICONBENCH_DOCKER_DIGEST_FILE", raising=False)
    monkeypatch.setattr(runner, "DEFAULT_DOCKER_DIGEST_FILE", tmp_path / "absent-primary")
    monkeypatch.setattr(runner, "LEGACY_DOCKER_DIGEST_FILE", tmp_path / "absent-legacy")
    manifest = run_task("toy_task", TOY_REF, tmp_path / "default.json")
    assert manifest.docker_digest == runner.DEFAULT_DOCKER_DIGEST
    assert manifest.docker_digest_source == "default"


def test_flow_subprocess_timeout_is_bounded_and_reported():
    started = time.monotonic()

    result = flows._run(
        [sys.executable, "-c", "import time; time.sleep(10)"],
        timeout_s=0.05,
    )

    assert time.monotonic() - started < 1.0
    assert result.returncode == 124
    assert "TIMEOUT after 0.05 seconds" in result.stdout
