"""Tests for the v2 operator set, sequential oracles and the unbounded equivalence engine."""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

AUDIT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AUDIT_ROOT.parent
for import_root in (REPO_ROOT, AUDIT_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

import archxbench_analysis as analysis  # noqa: E402
import archxbench_formal as formal  # noqa: E402
import archxbench_oracles as oracles  # noqa: E402
from archxbench_ops_v2 import V2_OPERATORS, generate_mutants_v2  # noqa: E402
from harness.mutators import generate_mutants  # noqa: E402

PILOT = AUDIT_ROOT / "archxbench-pilot"
needs_sim = pytest.mark.skipif(shutil.which("iverilog") is None, reason="Icarus Verilog not installed")
needs_sby = pytest.mark.skipif(shutil.which("sby") is None or shutil.which("yosys") is None,
                               reason="SymbiYosys not installed")


def by_op(source, operator):
    return [m for m in generate_mutants_v2("t", source) if m.operator == operator]


def sources(mutants):
    return {m.source for m in mutants}


def test_v2_is_v1_unchanged_plus_extras():
    src = "module m(input a, b, output y);\n    assign y = (a & b) | b;\nendmodule\n"
    v1, v2 = generate_mutants("t", src, include_task_specs=False), generate_mutants_v2("t", src)
    assert [m.source for m in v2[:len(v1)]] == [m.source for m in v1]
    assert len(v2) > len(v1)
    assert [m.id for m in v2] == [f"t-m{i:03d}" for i in range(len(v2))]


def test_generation_is_deterministic_and_deduplicated():
    src = (PILOT / "v2" / "references" / "comparator_8bit.v").read_text()
    a, b = generate_mutants_v2("t", src), generate_mutants_v2("t", src)
    assert [m.source for m in a] == [m.source for m in b]
    assert len({m.source for m in a}) == len(a) and src not in {m.source for m in a}


def test_relational_replacement_covers_boundaries_and_skips_nonblocking():
    src = "module m(input [3:0] a, b, output y, output reg r);\n  assign y = (a < b);\n  always @(*) r <= a;\nendmodule\n"
    ror = by_op(src, "relational_op_replacement")
    assert any("(a <= b)" in m.source for m in ror) and any("(a >= b)" in m.source for m in ror)
    assert not any("r < a" in m.source or "r == a" in m.source for m in ror)
    assert len(ror) == 5


def test_bitwise_replacement_distinguishes_binary_from_reduction_and_logical():
    src = "module m(input [1:0] a, b, output y, z, w);\n  assign y = a & b;\n  assign z = &a;\n  assign w = a && b;\nendmodule\n"
    out = sources(by_op(src, "bitwise_op_replacement"))
    assert "module m(input [1:0] a, b, output y, z, w);\n  assign y = a | b;\n  assign z = &a;\n  assign w = a && b;\nendmodule\n" in out
    assert all("assign z = &a;" in s and "assign w = a && b;" in s for s in out)
    assert len(out) == 2


def test_negation_deletion_only_unary():
    src = "module m(input a, b, output y);\n  assign y = a & ~b;\nendmodule\n"
    out = sources(by_op(src, "negation_deletion"))
    assert out == {"module m(input a, b, output y);\n  assign y = a & b;\nendmodule\n"}


def test_if_condition_negation():
    src = "module m(input c, output reg y);\n  always @(*) begin\n    if (c) y = 1'b1; else y = 1'b0;\n  end\nendmodule\n"
    assert any("if (!(c))" in m.source for m in by_op(src, "if_condition_negation"))


def test_arith_replacement_ignores_increment_tokens_and_unary_minus():
    src = "module m(input [3:0] a, output [3:0] y);\n  assign y = a + 4'd1;\nendmodule\n"
    assert sources(by_op(src, "arith_op_replacement")) == {src.replace("a + 4'd1", "a - 4'd1")}


def test_constant_bit_flip_preserves_width_and_base():
    src = "module m(output [3:0] y, output [7:0] z);\n  assign y = 4'b0101;\n  assign z = 8'hA0;\nendmodule\n"
    out = sources(by_op(src, "constant_bit_flip"))
    assert any("4'b0100" in s for s in out) and any("8'hA1".lower() in s.lower() for s in out)


def test_bit_select_off_by_one_and_no_negative_index():
    src = "module m(input [3:0] a, output y, z);\n  assign y = a[0];\n  assign z = a[2];\nendmodule\n"
    out = by_op(src, "bit_select_off_by_one")
    assert len(out) == 3  # a[0]->a[1]; a[2]->a[3], a[1]
    assert not any("a[-1]" in m.source for m in out)


def test_gate_replacement_and_stuck_at():
    src = "module m(input a, b, output y, z);\n  and u0 (y, a, b);\n  assign z = a | b;\nendmodule\n"
    gates = by_op(src, "gate_type_replacement")
    assert {m.description for m in gates} == {"gate and becomes or", "gate and becomes nand"}
    stuck = sources(by_op(src, "stuck_at_assign"))
    assert any("assign z = '0;" in s for s in stuck) and any("assign z = '1;" in s for s in stuck)


def test_mutations_inside_comments_and_strings_are_not_made():
    src = 'module m(input a, b, output y);\n  // y = a & b\n  assign y = a;\n  initial $display("a & b");\nendmodule\n'
    assert not by_op(src, "bitwise_op_replacement")


def test_every_declared_operator_has_a_generator():
    seen = {m.operator for ref in (PILOT / "v2" / "references").glob("*.v")
            for m in generate_mutants_v2("t", ref.read_text())}
    assert set(V2_OPERATORS) <= seen | {"if_condition_negation", "arith_op_replacement"}


# ------------------------------------------------------------------ oracles


@pytest.mark.parametrize("module", sorted(oracles.SEQ_SPECS))
def test_sequential_models_start_at_documented_reset_value(module):
    row = oracles.sequential_oracle_rows(module)[0].split()
    assert row[1] == {"johnson_counter4": "0000", "ring_counter4": "0001", "gray_counter8": "00000000",
                      "up_counter8": "00000000", "clock_div2": "0"}[module]


def test_gray_model_changes_one_bit_per_cycle_without_reset():
    rows = [int(r.split()[1], 2) for r in oracles.sequential_oracle_rows("gray_counter8")[:300]]
    assert all(bin(a ^ b).count("1") == 1 for a, b in zip(rows[1:], rows[2:]))


def test_encoder_legality_predicate_keeps_only_one_hot():
    assert len(oracles.oracle_rows("binary_encoder_8to3")) == 8
    all_rows = [f"{i} 000" for i in range(256)]
    assert len(oracles.legal_filter("binary_encoder_8to3", all_rows)) == 8


def test_summary_module_may_differ_from_dut_module(tmp_path):
    from archxbench_pilot import ArchXBenchRunner
    tb = tmp_path / "tb.v"
    tb.write_text("module tb; endmodule\n")
    runner = ArchXBenchRunner(tb, "decoder3to8", "tb", summary_module="decoder_3to8")
    assert runner.summary_module == "decoder_3to8" and runner.module == "decoder3to8"


# ------------------------------------------------------------------ real tools


def ref(name):
    return (PILOT / "v2" / "references" / name).read_text()


@needs_sim
@pytest.mark.parametrize("module,file", [
    ("johnson_counter4", "johnson_counter4.v"), ("ring_counter4", "ring_counter4.v"),
    ("gray_counter8", "gray_counter8.v"), ("up_counter8", "up_counter8.v"), ("clock_div2", "clock_div2.v"),
    ("binary_encoder_8to3", "binary_encoder_8to3.v"), ("comparator_8bit", "comparator_8bit.v"),
    ("decoder3to8", "decoder3to8.v"), ("demux_1to2", "demux_1to2.v"), ("demux_1to4", "demux_1to4.v"),
    ("mux_4to1", "mux_4to1.v")])
def test_v2_references_match_independent_oracles(tmp_path, module, file):
    rows = formal.behavior_rows("iverilog", "vvp", ref(file), module, tmp_path)
    assert rows == formal.expected_rows(module)


@needs_sim
def test_trace_comparison_detects_a_sequential_difference(tmp_path):
    good = ref("ring_counter4.v")
    bad = good.replace("{state[2:0], state[3]}", "{state[2:0], ~state[3]}")
    a = formal.behavior_rows("iverilog", "vvp", good, "ring_counter4", tmp_path / "a")
    b = formal.behavior_rows("iverilog", "vvp", bad, "ring_counter4", tmp_path / "b")
    assert a != b


@needs_sby
def test_sby_proves_equivalent_and_refutes_different(tmp_path):
    good = ref("ring_counter4.v")
    same_logic = good.replace("{state[2:0], state[3]}", "{state[2:0], state[3] | 1'b0}")
    different = good.replace("4'b0001;", "4'b0010;")
    assert formal.sby_equivalence("sby", good, same_logic, "ring_counter4", tmp_path / "eq") == "equivalent"
    assert formal.sby_equivalence("sby", good, different, "ring_counter4", tmp_path / "ne") == "different"


@needs_sby
def test_sby_finds_difference_only_reachable_after_many_cycles(tmp_path):
    good = ref("up_counter8.v")
    late_bug = good.replace("value <= value + 8'd1;", "value <= (value == 8'd200) ? 8'd7 : value + 8'd1;")
    assert formal.sby_equivalence("sby", good, late_bug, "up_counter8", tmp_path) == "different"


@needs_sim
def test_multi_module_yosys_miter_handles_shared_submodule_names(tmp_path):
    if shutil.which("yosys") is None:
        pytest.skip("yosys missing")
    good = ref("comparator_8bit.v")
    bad = good.replace("assign eq = eq_hi & eq_lo;", "assign eq = eq_hi | eq_lo;")
    assert analysis.yosys_equivalence("yosys", good, good, "comparator_8bit", tmp_path / "e") == "equivalent"
    assert analysis.yosys_equivalence("yosys", good, bad, "comparator_8bit", tmp_path / "d") == "different"


def test_sequential_category_requires_unbounded_proof_for_equivalence():
    rec = {"outcome": "PASS"}
    assert analysis._categorize(rec, True, "equivalent", True)[0] == "EQUIVALENT"
    assert analysis._categorize(rec, True, "error", True)[0] == "INDETERMINATE"
    assert analysis._categorize(rec, False, "different", True)[0] == "SURVIVED"
    assert analysis._categorize({"outcome": "TB_FAIL"}, False, "different", True)[0] == "BEHAVIORAL_KILL"
    assert analysis._categorize(rec, False, "equivalent", True)[0] == "INDETERMINATE"


def test_legal_assumption_equivalence_is_labeled_not_proven_by_solver():
    cat, why = analysis._categorize({"outcome": "PASS"}, True, "n/a-legal-assumption")
    assert cat == "EQUIVALENT" and "legal input" in why
