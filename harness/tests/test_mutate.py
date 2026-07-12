from harness.mutate import _is_timeout, run_mutation
from harness.mutators import generate_mutants


def test_mutants_are_deterministic_for_seed():
    first = run_mutation(task_id="t1_gray_counter", min_kill=0, seed=1337)
    second = run_mutation(task_id="t1_gray_counter", min_kill=0, seed=1337)
    assert first == second


def test_mutator_generates_expected_gray_operators():
    source = "if (rst)\n    bin <= '0;\nelse if (en)\n    bin <= bin + 1'b1;\nassign gray = bin ^ (bin >> 1);\n"
    operators = {mutant.operator for mutant in generate_mutants("t1_gray_counter", source)}
    assert "reset_polarity_flip" in operators
    assert "dropped_enable" in operators
    assert "operator_inversion" in operators


def test_mutator_never_changes_comment_text():
    source = "module m; // x == y and x + 1'b1\nassign y = x == z;\nendmodule\n"
    mutants = generate_mutants("generic", source)

    assert mutants
    assert all("x != y" not in mutant.source for mutant in mutants)
    assert any("assign y = x != z;" in mutant.source for mutant in mutants)


def test_mutator_does_not_truncate_large_structural_set():
    assignments = "\n".join(f"q{i} <= '0;" for i in range(40))
    source = f"module m; always_ff @(posedge clk) begin\n{assignments}\nend endmodule\n"

    mutants = generate_mutants("generic", source)

    assert len(mutants) > 32


def test_internal_reset_state_is_not_mutated_but_output_reset_is():
    source = """module m(
input logic clk, input logic rst, output logic out
);
logic internal;
always_ff @(posedge clk) begin
  if (rst) begin
    internal <= '0;
    out <= '0;
  end else begin
    internal <= '1;
    out <= internal;
  end
end
endmodule
"""

    mutants = generate_mutants("generic", source)

    assert all("internal <= '1;\n    out <= '0;" not in mutant.source for mutant in mutants)
    assert any("out <= '1;" in mutant.source for mutant in mutants)


def test_spi_shift_register_preload_equivalents_are_excluded():
    source = """module spi_slave;
logic [6:0] rx_shreg;
always_ff @(posedge clk) begin
  if (cs_fall) rx_shreg <= '0;
end
endmodule
"""

    mutants = generate_mutants("t2_spi_slave", source)

    assert all("rx_shreg <= '1;" not in mutant.source for mutant in mutants)
    assert all("rx_shreg <= rx_shreg;" not in mutant.source for mutant in mutants)


def test_sim_timeout_is_detected_as_indeterminate_signal():
    assert _is_timeout("cocotb output\nTIMEOUT after 20 seconds\n")
    assert not _is_timeout("assertion failed")


def test_existing_holds_and_for_loop_initializers_are_not_mutated():
    source = """module m;
always_comb begin
  for (int i = 0; i < 8; i++) out[i] = in[7-i];
end
always_ff @(posedge clk) out <= out;
endmodule
"""

    mutants = generate_mutants("generic", source)

    assert all("int i = ~(0)" not in mutant.source for mutant in mutants)
    assert all(mutant.operator != "assignment_hold" for mutant in mutants)
