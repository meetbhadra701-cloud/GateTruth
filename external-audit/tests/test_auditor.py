from __future__ import annotations

import importlib
import sys
from collections import defaultdict
from pathlib import Path

import pytest

AUDIT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AUDIT_ROOT.parent
for import_root in (REPO_ROOT, AUDIT_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

audit_module = importlib.import_module("auditor.audit")

from auditor.audit import audit_design  # noqa: E402
from auditor.protocol import TbResult, Verdict  # noqa: E402
from auditor.rtllm import RTLLMIcarusRunner  # noqa: E402
from fetch_vendor import tree_hash  # noqa: E402
from harness.mutators import Mutant  # noqa: E402


def _catalog_entry(golden: str) -> dict:
    return {
        "_golden_source": golden,
        "_tool_versions": {
            "harness_git": "abcdef0",
            "iverilog": "fixture",
            "python": "3.11.2",
        },
        "_vendor_commit": "1234567",
        "notes": "",
        "reference_sha256": None,
        "testbench_sha256": "tb-hash",
    }


class ScriptedRunner:
    suite = "rtllm"

    def __init__(self, scripts: dict[str, list[TbResult]]) -> None:
        self.scripts = {key: list(values) for key, values in scripts.items()}
        self.calls = defaultdict(int)

    def run(
        self,
        design_id: str,
        rtl_source: str,
        work_dir: Path,
        *,
        timeout_s: float,
    ) -> TbResult:
        del design_id, work_dir, timeout_s
        index = self.calls[rtl_source]
        self.calls[rtl_source] += 1
        return self.scripts[rtl_source][index]


def test_audit_baseline_failure_is_unsupported_without_mutants(monkeypatch):
    runner = ScriptedRunner({"golden": [TbResult(Verdict.FAIL, "tb")]})

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("mutants must not be generated after baseline failure")

    monkeypatch.setattr(audit_module, "generate_mutants", fail_if_called)
    report = audit_design(
        "broken",
        runner,
        1337,
        _catalog_entry("golden"),
    )

    assert report["status"] == "unsupported"
    assert report["baseline"] == {"verdict": "fail", "killed_by": "tb"}
    assert report["mutants_total"] == 0
    assert report["kill_rate"] == 0.0
    assert runner.calls["golden"] == 1


def test_audit_counts_kills_survivors_and_double_timeouts(monkeypatch):
    mutants = [
        Mutant("rtllm_foo-m000", "logic_inversion", "killed", "mutant-kill"),
        Mutant("rtllm_foo-m001", "output_inversion", "survives", "mutant-live"),
        Mutant("rtllm_foo-m002", "assignment_hold", "times out", "mutant-timeout"),
    ]
    monkeypatch.setattr(
        audit_module,
        "generate_mutants",
        lambda *_args, **_kwargs: mutants,
    )
    runner = ScriptedRunner(
        {
            "golden": [TbResult(Verdict.PASS, None)],
            "mutant-kill": [TbResult(Verdict.FAIL, "compile")],
            "mutant-live": [TbResult(Verdict.PASS, None)],
            "mutant-timeout": [
                TbResult(Verdict.TIMEOUT, None),
                TbResult(Verdict.TIMEOUT, None),
            ],
        }
    )

    report = audit_design("foo", runner, 1337, _catalog_entry("golden"))

    assert report["status"] == "audited"
    assert report["mutants_total"] == 3
    assert report["killed"] == 1
    assert report["survived"] == 1
    assert report["indeterminate"] == 1
    assert report["kill_rate"] == 33.3333
    assert runner.calls["mutant-timeout"] == 2
    verdicts = {item["id"]: item for item in report["per_mutant"]}
    assert verdicts["rtllm_foo-m000"]["killed_by"] == "compile"
    assert verdicts["rtllm_foo-m002"]["killed_by"] == "tb-timeout"


def test_audit_records_the_actual_generation_flag_not_a_default(monkeypatch):
    """GTFS-040: generation_flag must be the value this run actually passed to
    audit_design(), independent of anything in the catalog entry's notes."""

    mutants = [Mutant("rtllm_foo-m000", "logic_inversion", "killed", "mutant-kill")]
    monkeypatch.setattr(audit_module, "generate_mutants", lambda *_a, **_k: mutants)
    runner = ScriptedRunner(
        {
            "golden": [TbResult(Verdict.PASS, None)],
            "mutant-kill": [TbResult(Verdict.FAIL, "compile")],
        }
    )
    entry = _catalog_entry("golden")
    entry["notes"] = "baseline passed under Icarus Verilog-2001"

    report = audit_design("foo", runner, 1337, entry, generation_flag="-g2012")

    assert report["generation_flag"] == "-g2012"


def test_unsupported_report_still_records_generation_flag(monkeypatch):
    """The GTFS-040 field must be present on the unsupported-status path too, not
    only the fully-audited path -- both share _base_report() via **base."""

    runner = ScriptedRunner({"golden": [TbResult(Verdict.FAIL, "tb")]})

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("mutants must not be generated after baseline failure")

    monkeypatch.setattr(audit_module, "generate_mutants", fail_if_called)
    report = audit_design(
        "broken", runner, 1337, _catalog_entry("golden"), generation_flag="-g2012"
    )

    assert report["status"] == "unsupported"
    assert report["generation_flag"] == "-g2012"


def test_audit_defaults_generation_flag_to_none_when_not_supplied():
    runner = ScriptedRunner({"golden": [TbResult(Verdict.FAIL, "tb")]})

    report = audit_design("foo", runner, 1337, _catalog_entry("golden"))

    assert report["generation_flag"] is None


def _rtllm_fixture(tmp_path: Path) -> tuple[Path, dict]:
    design_root = tmp_path / "Arithmetic" / "foo"
    design_root.mkdir(parents=True)
    source = design_root / "verified_foo.v"
    source.write_text(
        "module verified_foo(output wire value);\n"
        "  assign value = 1'b1;\n"
        "endmodule\n",
        encoding="utf-8",
    )
    testbench = design_root / "testbench.v"
    testbench.write_text(
        "module testbench;\n"
        "  wire value;\n"
        "  foo uut(.value(value));\n"
        "  initial begin\n"
        "    #1;\n"
        '    if (value) $display("Your Design Passed");\n'
        "    $finish;\n"
        "  end\n"
        "endmodule\n",
        encoding="utf-8",
    )
    entry = {
        "design_id": "foo",
        "runnable": True,
        "reference_sources": ["Arithmetic/foo/verified_foo.v"],
        "testbench": "Arithmetic/foo/testbench.v",
        "extra_sources_needed": [],
        "pass_string": "Your Design Passed",
        "module_alias": {"from": "verified_foo", "to": "foo"},
    }
    return tmp_path, entry


def test_rtllm_runner_uses_temp_alias_and_preserves_vendor(tmp_path):
    vendor, entry = _rtllm_fixture(tmp_path / "vendor")
    runner = RTLLMIcarusRunner(vendor, {"foo": entry})
    golden = (vendor / entry["reference_sources"][0]).read_text(encoding="utf-8")
    before_hash = tree_hash(vendor)

    passed = runner.run(
        "foo",
        golden,
        tmp_path / "pass",
        timeout_s=5.0,
    )
    failed = runner.run(
        "foo",
        golden.replace("1'b1", "1'b0"),
        tmp_path / "fail",
        timeout_s=5.0,
    )
    compile_failed = runner.run(
        "foo",
        "this is not Verilog\n",
        tmp_path / "compile-fail",
        timeout_s=5.0,
    )

    assert passed == TbResult(Verdict.PASS, None)
    assert failed == TbResult(Verdict.FAIL, "tb")
    assert compile_failed == TbResult(Verdict.FAIL, "compile")
    assert tree_hash(vendor) == before_hash
    assert "module verified_foo" in golden


def test_rtllm_runner_rejects_catalog_path_escape(tmp_path):
    vendor, entry = _rtllm_fixture(tmp_path / "vendor")
    entry["testbench"] = "../outside.v"
    runner = RTLLMIcarusRunner(vendor, {"foo": entry})

    with pytest.raises(ValueError, match="escapes root"):
        runner.run(
            "foo",
            "module verified_foo; endmodule\n",
            tmp_path / "work",
            timeout_s=5.0,
        )
