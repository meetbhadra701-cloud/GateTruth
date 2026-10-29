"""Adapter and analysis tests.

Mocked-subprocess tests exercise verdict logic without a simulator. Tests marked
``needs_iverilog`` use the real simulator and are skipped (never silently passed) when it
is absent; the pinned Docker image runs all of them.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

AUDIT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AUDIT_ROOT.parent
for import_root in (REPO_ROOT, AUDIT_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

import archxbench_analysis as analysis  # noqa: E402
import archxbench_oracles as oracles  # noqa: E402
from archxbench_pilot import (  # noqa: E402
    ArchXBenchRunner,
    declares_module,
    sim_env,
    under,
    verify_vendor,
)
from auditor.protocol import TbResult, Verdict  # noqa: E402

PILOT = AUDIT_ROOT / "archxbench-pilot"
needs_iverilog = pytest.mark.skipif(
    shutil.which("iverilog") is None or shutil.which("vvp") is None,
    reason="Icarus Verilog not installed (run inside the pinned gatetruth:v1 image)",
)

GOOD = '{"module": "foo", "passed": 8, "failed": 0}\n'


def proc(out="", code=0):
    return subprocess.CompletedProcess(["mock"], code, stdout=out, stderr="")


@pytest.fixture
def runner(tmp_path):
    tb = tmp_path / "tb.v"
    tb.write_bytes(b"module tb_foo; endmodule\r\n")
    return ArchXBenchRunner(tb, "foo", "tb_foo")


def run_mock(runner, tmp_path, stdout, returncode=0, name="run"):
    with patch("archxbench_pilot.subprocess.run", side_effect=[proc(), proc(stdout, returncode)]):
        return runner.run("foo", "module foo; endmodule", tmp_path / name, timeout_s=3.0)


@pytest.mark.parametrize(
    "stdout,returncode,expected,outcome",
    [
        (GOOD, 0, Verdict.PASS, "PASS"),
        ("[PASS] all tests\n", 0, Verdict.NOT_RUNNABLE, "MALFORMED_SUMMARY"),
        ('{"module": "foo", "passed": 3, "failed": 1}\n', 0, Verdict.FAIL, "TB_FAIL"),
        ('{"module": "foo", "passed": 3, "failed": 1}\n', 1, Verdict.FAIL, "TB_FAIL"),
        ("crashed\n", 1, Verdict.NOT_RUNNABLE, "MALFORMED_SUMMARY"),
        ('{"module": "bar", "passed": 8, "failed": 0}\n', 0, Verdict.NOT_RUNNABLE, "MALFORMED_SUMMARY"),
        (GOOD, 1, Verdict.NOT_RUNNABLE, "NONZERO_EXIT_WITHOUT_FAILURES"),
        ('{"module": "foo", "passed": 0, "failed": 0}\n', 0, Verdict.NOT_RUNNABLE,
         "NONZERO_EXIT_WITHOUT_FAILURES"),
        ('{"module": "foo", "passed": true, "failed": 0}\n', 0, Verdict.NOT_RUNNABLE, "MALFORMED_SUMMARY"),
        ('{"module": "foo", "passed": -1, "failed": 0}\n', 0, Verdict.NOT_RUNNABLE, "MALFORMED_SUMMARY"),
        ('{"module": "foo", "passed": 8\n', 0, Verdict.NOT_RUNNABLE, "MALFORMED_SUMMARY"),
        (GOOD + GOOD, 0, Verdict.NOT_RUNNABLE, "MALFORMED_SUMMARY"),
        (GOOD + '{"module": "foo", "passed": 0, "failed": 8}\n', 0, Verdict.NOT_RUNNABLE,
         "MALFORMED_SUMMARY"),
    ],
)
def test_verdict_not_inferred_from_exit_only(tmp_path, runner, stdout, returncode, expected, outcome):
    result = run_mock(runner, tmp_path, stdout, returncode)
    assert result.verdict == expected
    assert runner.records["run"]["outcome"] == outcome


def test_exit_zero_with_pass_text_but_no_summary_is_never_a_pass(tmp_path, runner):
    assert run_mock(runner, tmp_path, "PASS\nAll tests passed\n", 0).verdict != Verdict.PASS


def test_compile_failure_is_not_a_testbench_kill(tmp_path, runner):
    with patch("archxbench_pilot.subprocess.run", return_value=proc("error", 1)):
        result = runner.run("foo", "module foo; invalid", tmp_path / "run", timeout_s=3.0)
    assert result == TbResult(Verdict.NOT_RUNNABLE, "compile")
    assert result.verdict != Verdict.FAIL
    assert runner.records["run"]["outcome"] == "COMPILE_FAILURE"


def test_timeout_never_claimed_as_kill(tmp_path, runner):
    with patch("archxbench_pilot.subprocess.run", side_effect=subprocess.TimeoutExpired("iverilog", 3)):
        result = runner.run("foo", "module foo; endmodule", tmp_path / "run", timeout_s=3.0)
    assert result.verdict == Verdict.TIMEOUT
    assert runner.records["run"]["timeout_phase"] == "compile"


def test_simulation_phase_timeout_is_labeled(tmp_path, runner):
    with patch("archxbench_pilot.subprocess.run",
               side_effect=[proc(), subprocess.TimeoutExpired("vvp", 3)]):
        result = runner.run("foo", "module foo; endmodule", tmp_path / "run", timeout_s=3.0)
    assert result.verdict == Verdict.TIMEOUT
    assert runner.records["run"]["timeout_phase"] == "simulate"


def test_missing_simulator_is_not_runnable(tmp_path, runner):
    with patch("archxbench_pilot.subprocess.run", side_effect=FileNotFoundError("iverilog")):
        result = runner.run("foo", "module foo; endmodule", tmp_path / "run", timeout_s=3.0)
    assert result.verdict == Verdict.NOT_RUNNABLE
    assert runner.records["run"]["outcome"] == "SETUP_ERROR_SIMULATOR_UNAVAILABLE"


def test_missing_module_declaration_is_setup_error_without_running(tmp_path, runner):
    with patch("archxbench_pilot.subprocess.run") as sub:
        result = runner.run("foo", "module other; endmodule", tmp_path / "run", timeout_s=3.0)
    sub.assert_not_called()
    assert result.verdict == Verdict.NOT_RUNNABLE
    assert runner.records["run"]["outcome"] == "SETUP_ERROR_MODULE_MISSING"


@pytest.mark.parametrize(
    "source,present",
    [
        ("module foo(input a); endmodule", True),
        ("// module foo\nmodule bar; endmodule", False),
        ("/* module foo */ module foobar; endmodule", False),
        ("module  foo (", True),
    ],
)
def test_module_name_matching(source, present):
    assert declares_module(source, "foo") is present


def test_check_count_mismatch_after_baseline_is_not_a_kill_or_pass(tmp_path, runner):
    assert run_mock(runner, tmp_path, GOOD, name="baseline").verdict == Verdict.PASS
    result = run_mock(runner, tmp_path, '{"module": "foo", "passed": 2, "failed": 0}\n', name="m1")
    assert result.verdict == Verdict.NOT_RUNNABLE
    assert runner.records["m1"]["outcome"] == "CHECK_COUNT_MISMATCH"
    shortened_fail = '{"module": "foo", "passed": 1, "failed": 1}\n'
    assert run_mock(runner, tmp_path, shortened_fail, name="m2").verdict == Verdict.NOT_RUNNABLE


def test_original_testbench_bytes_are_preserved_including_crlf(tmp_path, runner):
    original = runner.testbench.read_bytes()
    run_mock(runner, tmp_path, GOOD)
    assert (tmp_path / "run" / "tb.v").read_bytes() == original
    assert runner.testbench.read_bytes() == original


def test_each_run_uses_isolated_work_dir_and_refuses_reuse(tmp_path, runner):
    run_mock(runner, tmp_path, GOOD, name="a")
    with pytest.raises(FileExistsError):
        run_mock(runner, tmp_path, GOOD, name="a")


def test_sim_env_is_minimal_and_locale_pinned(monkeypatch):
    monkeypatch.setenv("SECRET_TOKEN", "x")
    env = sim_env()
    assert "SECRET_TOKEN" not in env
    assert env["LC_ALL"] == "C" and env["TZ"] == "UTC"


def test_path_traversal_rejected(tmp_path):
    (tmp_path / "root").mkdir()
    (tmp_path / "outside.txt").write_text("x")
    with pytest.raises(ValueError):
        under(tmp_path / "root", "../outside.txt")
    with pytest.raises(ValueError):
        under(tmp_path / "root", str(tmp_path / "outside.txt"))


def test_symlink_escape_rejected(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (tmp_path / "secret.v").write_text("x")
    try:
        (root / "tb.v").symlink_to(tmp_path / "secret.v")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    with pytest.raises(ValueError):
        under(root, "tb.v")


def test_bad_module_identifier_rejected(tmp_path):
    with pytest.raises(ValueError):
        ArchXBenchRunner(tmp_path / "tb.v", "foo; rm -rf", "tb")
    with pytest.raises(ValueError):
        ArchXBenchRunner(tmp_path / "tb.v", "foo", "tb top")


def _git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t", "-c", "core.autocrlf=false", *args],
        check=True, capture_output=True, text=True,
    ).stdout.strip()


@pytest.fixture
def vendor(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("git unavailable")
    root = tmp_path / "vendor"
    (root / "t").mkdir(parents=True)
    (root / "t" / "tb.v").write_bytes(b"module tb; endmodule\n")
    _git(root, "init", "-q")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "x")
    return root, _git(root, "rev-parse", "HEAD")


def test_verify_vendor_accepts_pristine_pinned_checkout(vendor):
    root, sha = vendor
    commit, tb = verify_vendor(root, sha, "t")
    assert commit == sha and tb.name == "tb.v"


def test_verify_vendor_rejects_sha_mismatch(vendor):
    root, _ = vendor
    with pytest.raises(SystemExit):
        verify_vendor(root, "0" * 40, "t")


def test_verify_vendor_rejects_modified_or_crlf_converted_testbench(vendor):
    root, sha = vendor
    (root / "t" / "tb.v").write_bytes(b"module tb; endmodule\r\n")
    with pytest.raises(SystemExit):
        verify_vendor(root, sha, "t")


# ---------------------------------------------------------------- real-simulator tests

MINI_TB = """`timescale 1ns/1ps
module tb_mux_2to1;
  reg sel, in0, in1; wire out; integer p = 0, f = 0, i;
  mux_2to1 dut (.sel(sel), .in0(in0), .in1(in1), .out(out));
  initial begin
    for (i = 0; i < 8; i = i + 1) begin
      {sel, in0, in1} = i[2:0]; #10;
      if (out === (sel ? in1 : in0)) p = p + 1; else f = f + 1;
    end
    $display("{\\"module\\": \\"mux_2to1\\", \\"passed\\": %0d, \\"failed\\": %0d}", p, f);
    $finish(1);
  end
endmodule
"""
MUX = (PILOT / "references" / "mux_2to1.v").read_text()


@pytest.fixture
def real_runner(tmp_path):
    tb = tmp_path / "tb.v"
    tb.write_text(MINI_TB)
    return ArchXBenchRunner(tb, "mux_2to1", "tb_mux_2to1")


@needs_iverilog
def test_real_simulator_pass_kill_compile_and_timeout(tmp_path, real_runner):
    assert real_runner.run("m", MUX, tmp_path / "base", timeout_s=20).verdict == Verdict.PASS
    killed = real_runner.run("m", MUX.replace("in0 & ~sel", "in1 & ~sel"), tmp_path / "k", timeout_s=20)
    assert killed == TbResult(Verdict.FAIL, "tb")
    bad = real_runner.run("m", MUX.replace("endmodule", "endmodul"), tmp_path / "c", timeout_s=20)
    assert bad == TbResult(Verdict.NOT_RUNNABLE, "compile")
    hang = MUX.replace("endmodule", "initial forever begin end\nendmodule")
    assert real_runner.run("m", hang, tmp_path / "t", timeout_s=2).verdict == Verdict.TIMEOUT


@needs_iverilog
def test_real_simulator_runs_are_deterministic(tmp_path, real_runner):
    a = real_runner.run("m", MUX, tmp_path / "a", timeout_s=20)
    b = real_runner.run("m", MUX, tmp_path / "b", timeout_s=20)
    assert a == b
    assert real_runner.records["a"]["sim_stdout_sha256"] == real_runner.records["b"]["sim_stdout_sha256"]


# ---------------------------------------------------------------- oracles and analysis


@pytest.mark.parametrize("module,rows", [("mux_2to1", 8), ("comparator_4bit", 256), ("decoder_2to4", 8)])
def test_oracle_row_counts(module, rows):
    assert len(oracles.oracle_rows(module)) == rows


def test_comparator_oracle_is_mutually_exclusive():
    spec = oracles.SPECS["comparator_4bit"]
    for _, values in oracles.input_combinations(spec):
        out = spec["oracle"](values)
        assert out["gt"] + out["eq"] + out["lt"] == 1


@needs_iverilog
@pytest.mark.parametrize(
    "module,ref",
    [
        ("mux_2to1", "mux_2to1.v"),
        ("comparator_4bit", "comparator_4bit.v"),
        ("decoder_2to4", "decoder_2to4.v"),
        ("decoder_2to4", "decoder_2to4_behavioral_SENSITIVITY.v"),
    ],
)
def test_references_match_independent_oracle_exhaustively(tmp_path, module, ref):
    source = (PILOT / "references" / ref).read_text()
    rows = analysis.exhaustive_rows("iverilog", "vvp", source, module, tmp_path)
    assert rows == oracles.oracle_rows(module)


@needs_iverilog
def test_exhaustive_comparison_detects_difference_and_equivalence(tmp_path):
    ref = analysis.exhaustive_rows("iverilog", "vvp", MUX, "mux_2to1", tmp_path / "r")
    xor_form = MUX.replace("(in0 & ~sel) | (in1 & sel)", "(in0 & ~sel) ^ (in1 & sel)")
    assert analysis.exhaustive_rows("iverilog", "vvp", xor_form, "mux_2to1", tmp_path / "x") == ref
    inverted = MUX.replace("assign out = ", "assign out = ~")
    assert analysis.exhaustive_rows("iverilog", "vvp", inverted, "mux_2to1", tmp_path / "i") != ref


def rec(outcome, **extra):
    return {"outcome": outcome, **extra}


@pytest.mark.parametrize(
    "record,same,yosys,category",
    [
        (rec("COMPILE_FAILURE"), None, "not-run", "COMPILE_FAILURE"),
        (rec("TIMEOUT", timeout_phase="simulate"), None, "not-run", "TIMEOUT"),
        (rec("SETUP_ERROR_MODULE_MISSING"), None, "not-run", "SETUP_ERROR"),
        (rec("MALFORMED_SUMMARY"), None, "not-run", "INDETERMINATE"),
        (rec("CHECK_COUNT_MISMATCH"), None, "not-run", "INDETERMINATE"),
        (rec("TB_FAIL"), False, "different", "BEHAVIORAL_KILL"),
        (rec("TB_FAIL"), True, "equivalent", "INDETERMINATE"),
        (rec("PASS"), False, "different", "SURVIVED"),
        (rec("PASS"), True, "equivalent", "EQUIVALENT"),
        (rec("PASS"), True, "different", "INDETERMINATE"),
        (rec("PASS"), None, "not-run", "INDETERMINATE"),
        (None, None, "not-run", "INDETERMINATE"),
    ],
)
def test_category_decision_table(record, same, yosys, category):
    assert analysis._categorize(record, same, yosys)[0] == category


def entry(category, operator="op"):
    return {"category": category, "operator": operator}


def test_summary_denominator_excludes_invalid_and_equivalent():
    entries = [entry("BEHAVIORAL_KILL"), entry("BEHAVIORAL_KILL"), entry("SURVIVED"),
               entry("EQUIVALENT"), entry("COMPILE_FAILURE"), entry("TIMEOUT")]
    s = analysis.summarize(entries, 1.0)
    assert s["behavioral_kill_score_fraction"] == "2/3"
    assert s["mutants_generated"] == 6 and s["mutants_compiling"] == 5
    assert s["inconclusive"] is False


def test_no_mutants_is_inconclusive_not_a_perfect_score():
    s = analysis.summarize([], 1.0)
    assert s["behavioral_kill_score"] is None and s["inconclusive"] is True


def test_only_invalid_or_equivalent_mutants_is_inconclusive():
    s = analysis.summarize([entry("COMPILE_FAILURE"), entry("EQUIVALENT")], 1.0)
    assert s["behavioral_kill_score"] is None and s["inconclusive"] is True


def test_all_killed_is_reported_without_overclaiming():
    s = analysis.summarize([entry("BEHAVIORAL_KILL")] * 3, 1.0)
    assert s["behavioral_kill_score"] == 1.0 and s["valid_nonequivalent_mutants"] == 3


def test_deterministic_view_drops_only_wall_clock():
    view = analysis.deterministic_view({"a": {"wall_s": 1.0, "x": 2}, "l": [{"analysis_wall_s": 3, "y": 1}]})
    assert view == {"a": {"x": 2}, "l": [{"y": 1}]}


def test_aggregate_separates_supplementary_designs(tmp_path):
    def design(design_id, kills, surv):
        path = tmp_path / f"{design_id}.json"
        counts = {c: 0 for c in analysis.CATEGORIES}
        counts.update(BEHAVIORAL_KILL=kills, SURVIVED=surv)
        path.write_text(json.dumps({"design_id": design_id, "summary": {
            "category_counts": counts, "mutants_generated": kills + surv,
            "inconclusive": kills + surv == 0}}))
        return path

    agg = analysis.aggregate([design("a", 1, 1), design("b", 0, 0), design("s", 9, 0)], {"s"})
    total = agg["aggregate_over_primary_designs"]
    assert total["behavioral_kill_score_fraction"] == "1/2"
    assert total["inconclusive_designs"] == ["b"]
    assert agg["supplementary_designs"] == ["s"]
