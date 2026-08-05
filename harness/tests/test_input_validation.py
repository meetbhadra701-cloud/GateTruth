from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from harness import runner, trackb
from harness.agentb import ActionRejected, execute_action
from harness.runner import run_task
from harness.trackb import run_track_b
from harness.validation import MAX_SOURCE_BYTES

TRACKB_FIXTURE = Path("harness/tests/fixtures/toy_taskB")


def _oversized_valid_source(source: str) -> str:
    padding = MAX_SOURCE_BYTES - len(source.encode("utf-8")) + 1024
    return source + "\n/*" + ("x" * padding) + "*/\n"


def _copy_trackb(tmp_path: Path) -> Path:
    destination = tmp_path / "toy_taskB"
    shutil.copytree(TRACKB_FIXTURE, destination)
    return destination


def test_track_a_oversized_valid_source_scores_zero_before_tool(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "oversized.sv"
    source.write_text(
        _oversized_valid_source(
            "module toy(input logic clk, rst, a, output logic y); "
            "always_ff @(posedge clk) y <= rst ? 1'b0 : a; endmodule"
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        runner,
        "run_lint",
        lambda *_args, **_kwargs: pytest.fail("tool must not run"),
    )
    out = tmp_path / "manifest.json"

    manifest = run_task("toy_task", source, out)

    assert manifest.task_score == 0.0
    assert manifest.ppa == 0.0
    assert "rejected before tool execution" in out.with_suffix(".log").read_text(
        encoding="utf-8"
    )


def test_track_b_oversized_valid_source_is_disqualified_before_tool(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    submission = _copy_trackb(tmp_path)
    design = submission / "design" / "toy_trackb.sv"
    design.write_text(
        _oversized_valid_source(design.read_text(encoding="utf-8")),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        trackb,
        "run_lint",
        lambda *_args, **_kwargs: pytest.fail("tool must not run"),
    )

    manifest = run_track_b("toy_taskB", submission, tmp_path / "trackb.json")

    assert manifest.disqualified is True
    assert manifest.task_score == 0.0
    assert "source exceeds" in manifest.disqualification_reason


def test_agent_write_rejects_oversized_source_before_disk_write(
    tmp_path: Path,
) -> None:
    sandbox = _copy_trackb(tmp_path)
    design = sandbox / "design" / "toy_trackb.sv"
    before = design.read_bytes()

    with pytest.raises(ActionRejected, match="source exceeds"):
        execute_action(
            {
                "tool": "write_design",
                "content": _oversized_valid_source(
                    before.decode("utf-8")
                ),
            },
            sandbox=sandbox,
            task_id="toy_taskB",
            top_module="toy_trackb",
            clock_target_ns=10.0,
            work_root=tmp_path / "work",
        )

    assert design.read_bytes() == before


def test_track_b_rejects_metacharacter_filename_before_tool(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    submission = _copy_trackb(tmp_path)
    source = submission / "design" / "toy_trackb.sv"
    source.rename(submission / "design" / "bad name;exec.sv")
    monkeypatch.setattr(
        trackb,
        "run_lint",
        lambda *_args, **_kwargs: pytest.fail("tool must not run"),
    )

    manifest = run_track_b("toy_taskB", submission, tmp_path / "bad-name.json")

    assert manifest.disqualified is True
    assert "invalid SystemVerilog filename" in manifest.disqualification_reason


def test_track_b_rejects_non_allowlisted_module_name_before_tool(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    submission = _copy_trackb(tmp_path)
    source = submission / "design" / "toy_trackb.sv"
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            "module toy_trackb",
            r"module \bad;exec",
            1,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        trackb,
        "run_lint",
        lambda *_args, **_kwargs: pytest.fail("tool must not run"),
    )

    manifest = run_track_b("toy_taskB", submission, tmp_path / "bad-module.json")

    assert manifest.disqualified is True
    assert "invalid module name" in manifest.disqualification_reason


def test_track_a_copies_submission_to_fixed_harness_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GTFS-011: run_task() used to pass the untrusted submission's own path
    straight into run_lint/run_sim/run_formal/run_ppa_flows, which embed it into
    generated Python (run_sim's cocotb runner script) and Yosys/Tcl source -- a
    quote or newline in that path could break out of the interpolation. Every
    stage must now only ever see a harness-chosen fixed filename."""

    source = tmp_path / "it's a design; exec('bad').sv"
    source.write_text("module toy; endmodule\n", encoding="utf-8")
    seen: list[Path] = []

    def capture_lint(path: Path):
        seen.append(path)
        return {"stage": 0, "name": "lint", "status": "fail"}, "stopped"

    monkeypatch.setattr(runner, "run_lint", capture_lint)

    run_task("toy_task", source, tmp_path / "fixed.json")

    assert [path.name for path in seen] == ["submission.sv"]


def test_track_a_quote_containing_path_does_not_break_the_generated_sim_script(
    tmp_path: Path,
) -> None:
    """End-to-end proof, not just that the copy happens: a real submission at a
    path containing a single quote (the exact character that would break out of
    run_sim's f"...[r'{submission}']" interpolation before the fix) must score
    exactly like the same content at a normal path, via the real EDA toolchain."""

    toy_ref = Path("harness/tests/fixtures/toy_task/ref/ref.sv").read_text(encoding="utf-8")
    dangerous = tmp_path / "attacker's \"submission\".sv"
    dangerous.write_text(toy_ref, encoding="utf-8")

    manifest = run_task("toy_task", dangerous, tmp_path / "dangerous.json")

    assert manifest.task_score == pytest.approx(66.6666666667)
    assert manifest.ppa == pytest.approx(1.0)
    assert all(stage.status in {"pass", "skip"} for stage in manifest.stages)


def test_track_b_copies_valid_design_to_fixed_harness_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    submission = _copy_trackb(tmp_path)
    seen: list[Path] = []

    def capture_lint(path: Path):
        seen.append(path)
        return {"stage": 0, "name": "lint", "status": "fail"}, "stopped"

    monkeypatch.setattr(trackb, "run_lint", capture_lint)

    manifest = run_track_b("toy_taskB", submission, tmp_path / "fixed.json")

    assert manifest.disqualified is False
    assert [path.name for path in seen] == ["submission.sv"]
