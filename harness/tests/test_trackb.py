from __future__ import annotations

import json
import shutil
from pathlib import Path

from harness.schemas.manifest_b import load_manifest_b
from harness.trackb import run_track_b

FIXTURE = Path("harness/tests/fixtures/toy_taskB")


def copy_fixture(tmp_path: Path) -> Path:
    dst = tmp_path / "toy_taskB"
    shutil.copytree(FIXTURE, dst)
    return dst


def test_trackb_disqualifies_tb_change(tmp_path):
    submission = copy_fixture(tmp_path)
    tb = submission / "tb" / "test_toy_taskB.py"
    tb.write_text(tb.read_text(encoding="utf-8") + "\n# changed by agent\n", encoding="utf-8")
    manifest = run_track_b("toy_taskB", submission, tmp_path / "disq.json")
    assert manifest.disqualified is True
    assert manifest.task_score == 0.0
    assert "immutable file differs: tb" in manifest.disqualification_reason


def test_trackb_disqualifies_multiple_design_files(tmp_path):
    submission = copy_fixture(tmp_path)
    (submission / "design" / "extra.sv").write_text(
        "module extra(input logic a, output logic y); assign y = a; endmodule\n",
        encoding="utf-8",
    )
    manifest = run_track_b("toy_taskB", submission, tmp_path / "multiple_design_files.json")
    assert manifest.disqualified is True
    assert manifest.task_score == 0.0
    assert manifest.objective_pass is False
    assert manifest.disqualification_reason == "expected exactly one .sv file in design, found 2"


def test_trackb_sec_has_teeth(tmp_path):
    submission = copy_fixture(tmp_path)
    design = submission / "design" / "toy_trackb.sv"
    text = design.read_text(encoding="utf-8")
    design.write_text(text.replace("y <= a ^ b;", "y <= ~(a ^ b);"), encoding="utf-8")
    manifest = run_track_b("toy_taskB", submission, tmp_path / "sec_fail.json")
    assert manifest.disqualified is False
    assert manifest.sec.status == "fail"
    assert manifest.objective_pass is False
    assert manifest.task_score == 0.0


def test_trackb_objective_pass_path(tmp_path):
    submission = copy_fixture(tmp_path)
    shutil.copy2(Path("harness/tests/fixtures/toy_taskB_solution/toy_trackb.sv"), submission / "design" / "toy_trackb.sv")
    manifest = run_track_b("toy_taskB", submission, tmp_path / "solution.json")
    assert manifest.disqualified is False
    assert manifest.sec.status == "pass"
    assert manifest.objective_pass is True
    assert manifest.task_score == 100.0
    assert manifest.ppa_delta.area_ratio is not None
    assert manifest.ppa_delta.area_ratio is not None


def test_trackb_deterministic_signature(tmp_path):
    submission = copy_fixture(tmp_path)
    shutil.copy2(Path("harness/tests/fixtures/toy_taskB_solution/toy_trackb.sv"), submission / "design" / "toy_trackb.sv")
    first = run_track_b("toy_taskB", submission, tmp_path / "first.json")
    second = run_track_b("toy_taskB", submission, tmp_path / "second.json")
    assert first.signature == second.signature
    assert load_manifest_b(tmp_path / "first.json").signature == first.signature


def test_trackb_manifest_signature_validation(tmp_path):
    submission = copy_fixture(tmp_path)
    run_track_b("toy_taskB", submission, tmp_path / "manifest.json")
    data = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    data["task_score"] = 42.0
    tampered = tmp_path / "tampered.json"
    tampered.write_text(json.dumps(data), encoding="utf-8")
    try:
        load_manifest_b(tampered)
    except ValueError as exc:
        assert "signature" in str(exc)
    else:
        raise AssertionError("tampered manifest validated")
