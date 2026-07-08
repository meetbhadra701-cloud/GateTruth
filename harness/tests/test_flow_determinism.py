import subprocess
import sys

from harness.schemas.manifest import load_manifest


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
