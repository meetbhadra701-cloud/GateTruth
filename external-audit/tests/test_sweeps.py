from __future__ import annotations

import sys
from pathlib import Path

import pytest

AUDIT_ROOT = Path(__file__).resolve().parents[1]
if str(AUDIT_ROOT) not in sys.path:
    sys.path.insert(0, str(AUDIT_ROOT))

from fetch_vendor import GIT_TEXT_CHECKOUT, tree_hash  # noqa: E402
from sweep_cvdp import _row_report  # noqa: E402
from sweep_rtllm import (  # noqa: E402
    IVERILOG,
    VVP,
    _module_names,
    _reference_top_module,
    _rewrite_module_declaration,
    _support_files,
    sweep_design,
)


def test_tree_hash_is_content_sensitive_and_ignores_git(tmp_path):
    (tmp_path / "B.txt").write_text("second\n", encoding="utf-8")
    (tmp_path / "a.txt").write_text("first\n", encoding="utf-8")
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("ignored\n", encoding="utf-8")

    baseline = tree_hash(tmp_path)
    (git_dir / "HEAD").write_text("still ignored\n", encoding="utf-8")
    assert tree_hash(tmp_path) == baseline

    (tmp_path / "a.txt").write_text("changed\n", encoding="utf-8")
    assert tree_hash(tmp_path) != baseline


def test_vendor_fetch_pins_certified_text_checkout_convention():
    assert GIT_TEXT_CHECKOUT == ["-c", "core.autocrlf=true"]


def test_cvdp_row_requires_actual_output_not_only_an_oss_origin():
    row = {
        "id": "cvdp_copilot_example_0001",
        "categories": ["cid003", "medium"],
        "output": {"response": "", "context": {"rtl/design.sv": ""}},
    }
    report = _row_report(
        row,
        oss_ids={"cvdp_copilot_example"},
        example_solutions={},
    )

    assert report["oss_origin_declared"] is True
    assert report["has_golden"] is False
    assert report["golden_source"] is None


def test_cvdp_row_accepts_nonempty_rtl_output():
    row = {
        "id": "row",
        "categories": ["cid002"],
        "output": {
            "response": "",
            "context": {"rtl/design.sv": "module design; endmodule\n"},
        },
    }
    report = _row_report(row, oss_ids=set(), example_solutions={})

    assert report["has_golden"] is True
    assert report["golden_source"] == "output-field"


def test_rtllm_module_and_support_file_discovery(tmp_path):
    source = tmp_path / "verified_example.v"
    source.write_text(
        "module helper; endmodule\nmodule verified_example; endmodule\n",
        encoding="utf-8",
    )
    testbench = tmp_path / "testbench.v"
    testbench.write_text(
        'module testbench; initial $readmemh("vectors.dat", mem); endmodule\n',
        encoding="utf-8",
    )
    (tmp_path / "vectors.dat").write_text("00\n", encoding="utf-8")

    modules = _module_names(source)
    assert modules == ["helper", "verified_example"]
    assert _reference_top_module(modules, "example") == "verified_example"
    assert _support_files(testbench) == ["vectors.dat"]


def test_rtllm_sweep_aliases_verified_module_in_temporary_copy(tmp_path):
    source = tmp_path / "verified_foo.v"
    original_source = (
        "module verified_foo\n"
        "#(parameter ONE = 1'b1)\n"
        "(output wire value);\n"
        "  assign value = ONE;\n"
        "endmodule\n"
    )
    source.write_text(original_source, encoding="utf-8")
    testbench = tmp_path / "testbench.v"
    testbench.write_text(
        "module testbench;\n"
        "  wire value;\n"
        "  foo #(.ONE(1'b1)) uut(.value(value));\n"
        "  initial begin\n"
        "    #1;\n"
        '    if (value) $display("Your Design Passed");\n'
        "    $finish;\n"
        "  end\n"
        "endmodule\n",
        encoding="utf-8",
    )

    result = sweep_design(
        {
            "design_id": "foo",
            "directory": tmp_path,
            "sources": [source],
            "testbench": testbench,
        },
        vendor=tmp_path,
        iverilog=IVERILOG,
        vvp=VVP,
        timeout_s=5.0,
    )

    assert result["runnable"] is True
    assert result["compatibility"] == "icarus-pass-with-module-alias"
    assert result["module_alias"] == {"from": "verified_foo", "to": "foo"}
    assert source.read_text(encoding="utf-8") == original_source


def test_rtllm_sweep_notes_record_the_actual_generation_flag_used(tmp_path):
    """The recorded note previously always said "Icarus Verilog-2001" regardless
    of which generation_flag was actually passed to the compiler -- wrong for
    the paper's reported g2012 condition. The note must reflect reality."""

    source = tmp_path / "example.v"
    source.write_text(
        "module example(output wire value);\n  assign value = 1'b1;\nendmodule\n",
        encoding="utf-8",
    )
    testbench = tmp_path / "testbench.v"
    testbench.write_text(
        "module testbench;\n"
        "  wire value;\n"
        "  example uut(.value(value));\n"
        "  initial begin\n"
        "    #1;\n"
        '    if (value) $display("Your Design Passed");\n'
        "    $finish;\n"
        "  end\n"
        "endmodule\n",
        encoding="utf-8",
    )

    result = sweep_design(
        {
            "design_id": "example",
            "directory": tmp_path,
            "sources": [source],
            "testbench": testbench,
        },
        vendor=tmp_path,
        iverilog=IVERILOG,
        vvp=VVP,
        timeout_s=5.0,
        generation_flag="-g2012",
    )

    assert result["runnable"] is True
    assert "-g2012" in result["notes"]
    assert "2001" not in result["notes"]


def test_rewrite_module_declaration_renames_the_single_declaration(tmp_path):
    source = tmp_path / "single.v"
    source.write_text("module verified_foo(input a, output b);\nendmodule\n", encoding="utf-8")

    rewritten = _rewrite_module_declaration(source, actual_module="verified_foo", expected_module="foo")

    assert "module foo(" in rewritten
    assert "verified_foo" not in rewritten


def test_rewrite_module_declaration_rejects_a_missing_declaration(tmp_path):
    source = tmp_path / "missing.v"
    source.write_text("module something_else(input a);\nendmodule\n", encoding="utf-8")

    with pytest.raises(ValueError, match="found 0"):
        _rewrite_module_declaration(source, actual_module="verified_foo", expected_module="foo")


def test_rewrite_module_declaration_rejects_a_duplicate_declaration(tmp_path):
    """Regression test: subn(..., count=1) can only ever report 0 or 1 replacements
    no matter how many declarations actually exist, so a naive `replacements != 1`
    check against that capped count can never catch this case -- it would silently
    rewrite only the first declaration and report success."""
    source = tmp_path / "duplicate.v"
    source.write_text(
        "module verified_foo(input a);\nendmodule\n"
        "module verified_foo(input b);\nendmodule\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="found 2"):
        _rewrite_module_declaration(source, actual_module="verified_foo", expected_module="foo")
