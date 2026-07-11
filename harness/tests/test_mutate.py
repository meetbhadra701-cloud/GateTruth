from harness.mutate import run_mutation
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
