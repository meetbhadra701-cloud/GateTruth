from __future__ import annotations

import hashlib
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
    assert manifest.disqualification_reason == "malformed submission: expected exactly one .sv file in design, found 2"
    assert manifest.submission_sha256 is None


def test_trackb_disqualified_for_other_reasons_still_hashes_the_design(tmp_path):
    submission = copy_fixture(tmp_path)
    tb = submission / "tb" / "test_toy_taskB.py"
    tb.write_text(tb.read_text(encoding="utf-8") + "\n# changed by agent\n", encoding="utf-8")
    design_bytes = (submission / "design" / "toy_trackb.sv").read_bytes()
    manifest = run_track_b("toy_taskB", submission, tmp_path / "disq_hashed.json")
    assert manifest.disqualified is True
    assert manifest.submission_sha256 == hashlib.sha256(design_bytes).hexdigest()


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
    solution = Path("harness/tests/fixtures/toy_taskB_solution/toy_trackb.sv")
    shutil.copy2(solution, submission / "design" / "toy_trackb.sv")
    manifest = run_track_b("toy_taskB", submission, tmp_path / "solution.json")
    assert manifest.disqualified is False
    assert manifest.sec.status == "pass"
    assert manifest.objective_pass is True
    assert manifest.task_score == 100.0
    assert manifest.ppa_delta.area_ratio is not None
    assert manifest.ppa_delta.area_ratio is not None
    assert manifest.submission_sha256 == hashlib.sha256(solution.read_bytes()).hexdigest()


def test_trackb_records_which_digest_source_actually_scored_it(tmp_path, monkeypatch):
    submission = copy_fixture(tmp_path)
    monkeypatch.setenv("GATETRUTH_DOCKER_DIGEST", "sha256:" + "dd" * 32)

    manifest = run_track_b("toy_taskB", submission, tmp_path / "env.json")

    assert manifest.docker_digest == "sha256:" + "dd" * 32
    assert manifest.docker_digest_source == "env"


def test_trackb_deterministic_signature(tmp_path):
    submission = copy_fixture(tmp_path)
    shutil.copy2(Path("harness/tests/fixtures/toy_taskB_solution/toy_trackb.sv"), submission / "design" / "toy_trackb.sv")
    first = run_track_b("toy_taskB", submission, tmp_path / "first.json")
    second = run_track_b("toy_taskB", submission, tmp_path / "second.json")
    assert first.signature == second.signature
    assert load_manifest_b(tmp_path / "first.json").signature == first.signature


def test_trackb_signature_is_stable_across_genuinely_separate_sandboxes(tmp_path):
    """GTFS-020: the test above reuses one submission directory for both runs, so
    it would still pass even with the bug this regression exists for -- two calls
    against the *same* path always agreed, bug or not. submission_dir used to
    record run_track_b()'s own tempfile.TemporaryDirectory() path (never the
    caller's submission argument at all, since run_ppa_flows etc. work inside
    their own work_root), so two byte-identical runs in genuinely independent
    sandboxes -- the real production shape -- necessarily produced different
    canonical signatures. Here each run gets its own separate submission
    directory, proving the property the paper actually claims."""

    sandbox1 = tmp_path / "sandbox1"
    sandbox2 = tmp_path / "sandbox2"
    shutil.copytree(FIXTURE, sandbox1)
    shutil.copytree(FIXTURE, sandbox2)
    solution = Path("harness/tests/fixtures/toy_taskB_solution/toy_trackb.sv")
    shutil.copy2(solution, sandbox1 / "design" / "toy_trackb.sv")
    shutil.copy2(solution, sandbox2 / "design" / "toy_trackb.sv")

    first = run_track_b("toy_taskB", sandbox1, tmp_path / "first.json")
    second = run_track_b("toy_taskB", sandbox2, tmp_path / "second.json")

    assert first.signature == second.signature
    assert first.submission_dir == second.submission_dir


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
