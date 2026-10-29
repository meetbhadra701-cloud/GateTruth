"""Adapter tests using mocked subprocess outputs; no simulator execution claimed."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

AUDIT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AUDIT_ROOT.parent
for import_root in (REPO_ROOT, AUDIT_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root)

import pytest

from archxbench_pilot import ArchXBenchRunner, under
from auditor.protocol import Verdict, TbResult


def proc(out="", code=0):
    return subprocess.CompletedProcess(["mock"], code, stdout=out, stderr="")


@pytest.fixture
def runner(tmp_path):
    tb = tmp_path / "tb.v"
    tb.write_text("module tb; endmodule\n")
    return ArchXBenchRunner(tb, "foo", "tb_foo")


@pytest.mark.parametrize("stdout,returncode,expected", [
    ('{"module": "foo", "passed": 8, "failed": 0}\n', 0, Verdict.PASS),
    ("[PASS] all tests\n", 0, Verdict.NOT_RUNNABLE),
    ('{"module": "foo", "passed": 3, "failed": 1}\n', 0, Verdict.FAIL),
    ("crashed\n", 1, Verdict.NOT_RUNNABLE),
    ('{"module": "bar", "passed": 8, "failed": 0}\n', 0, Verdict.NOT_RUNNABLE),
])
def test_verdict_not_inferred_from_exit_only(tmp_path, runner, stdout, returncode, expected):
    with patch("archxbench_pilot.subprocess.run",
               side_effect=[proc(), proc(stdout, returncode)]):
        result = runner.run("foo", "module foo; endmodule", tmp_path / "run",
                            timeout_s=3.0)
    assert result.verdict == expected


def test_compile_failure_is_separately_labeled(tmp_path, runner):
    with patch("archxbench_pilot.subprocess.run", return_value=proc("error", 1)):
        result = runner.run("foo", "invalid rtl", tmp_path / "run", timeout_s=3.0)
    assert result == TbResult(Verdict.FAIL, "compile")


def test_timeout_never_claimed_as_kill(tmp_path, runner):
    with patch("archxbench_pilot.subprocess.run",
               side_effect=subprocess.TimeoutExpired("iverilog", 3)):
        result = runner.run("foo", "invalid rtl", tmp_path / "run", timeout_s=3.0)
    assert result.verdict == Verdict.TIMEOUT


def test_path_traversal_rejected(tmp_path):
    with pytest.raises(ValueError):
        under(tmp_path, "../outside.txt")


def test_bad_module_identifier_rejected(tmp_path):
    with pytest.raises(ValueError):
        ArchXBenchRunner(tmp_path / "tb.v", "foo; rm -rf", "tb")
