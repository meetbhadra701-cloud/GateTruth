from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from harness import runner
from harness.runner import resolve_task, run_sim


@pytest.mark.parametrize(
    ("xml", "expected"),
    [
        ('<testsuite tests="0" failures="0" errors="0" skipped="0"/>', (0, 0)),
        (
            '<testsuite tests="2" failures="0" errors="0" skipped="1">'
            '<testcase name="pass"/><testcase name="skip"><skipped/></testcase>'
            "</testsuite>",
            (2, 1),
        ),
    ],
)
def test_zero_or_skipped_cocotb_results_fail_closed(
    xml: str,
    expected: tuple[int, int],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    work_root = tmp_path / "work"
    work_root.mkdir()

    def fake_run(*_args, **_kwargs):
        (work_root / "results.xml").write_text(xml, encoding="utf-8")
        return subprocess.CompletedProcess([], 0, "sim completed")

    monkeypatch.setattr(runner, "_run", fake_run)
    task = resolve_task("toy_task")

    stage, _log, _hidden_sha256, _hidden_test_count = run_sim(
        task,
        task.root / "ref" / "ref.sv",
        work_root,
    )

    assert runner._parse_cocotb_results(work_root / "results.xml") == expected
    assert stage["status"] == "fail"
