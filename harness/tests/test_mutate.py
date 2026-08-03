from types import SimpleNamespace

import harness.mutate as mutate_module
from harness.mutate import _is_timeout, _run_baseline, run_mutation
from harness.mutators import Mutant, generate_mutants
from harness.runner import HIDDEN_FAILURE_PREFIX


def test_mutants_are_deterministic_for_seed():
    first = run_mutation(task_id="t1_gray_counter", min_kill=0, seed=1337)
    second = run_mutation(task_id="t1_gray_counter", min_kill=0, seed=1337)
    assert first == second


def test_sequential_and_parallel_mutation_verdicts_match():
    sequential = run_mutation(
        task_id="t1_gray_counter",
        min_kill=0,
        seed=1337,
        jobs=1,
    )
    parallel = run_mutation(
        task_id="t1_gray_counter",
        min_kill=0,
        seed=1337,
        jobs=6,
    )

    assert sequential.pop("jobs") == 1
    assert parallel.pop("jobs") == 6
    assert sequential == parallel


def test_official_mutation_mode_is_threaded_to_mutant_runs(tmp_path, monkeypatch):
    ref_dir = tmp_path / "ref"
    ref_dir.mkdir()
    (ref_dir / "ref.sv").write_text("module m; endmodule\n", encoding="utf-8")
    task = SimpleNamespace(root=tmp_path)
    mutant = Mutant(
        id="m-000",
        operator="test",
        description="test mutant",
        source="module m; wire changed; endmodule\n",
    )
    official_values = []

    monkeypatch.setattr(mutate_module, "resolve_task", lambda _task_id: task)
    monkeypatch.setattr(
        mutate_module,
        "generate_mutants",
        lambda _task_id, _source: [mutant],
    )
    monkeypatch.setattr(
        mutate_module,
        "_run_baseline",
        lambda _task_id, _source, *, official: {"status": "pass", "stage": None, "log": ""},
    )

    def fake_run_one(_task_id, _mutant, *, official):
        official_values.append(official)
        return {
            "id": mutant.id,
            "operator": mutant.operator,
            "description": mutant.description,
            "stillborn": False,
            "setup_error": False,
            "killed_by": "sim",
            "indeterminate": False,
        }

    monkeypatch.setattr(mutate_module, "_run_one", fake_run_one)

    report = run_mutation(
        task_id="fixture",
        min_kill=95,
        seed=1337,
        official=True,
    )

    assert official_values == [True]
    assert report["official"] is True
    assert report["status"] == "ok"
    assert report["killed"] == 1
    assert report["kill_rate"] == 100.0


def _fixture_task(tmp_path):
    ref_dir = tmp_path / "ref"
    ref_dir.mkdir()
    (ref_dir / "ref.sv").write_text("module m; endmodule\n", encoding="utf-8")
    return SimpleNamespace(root=tmp_path)


def _fixture_mutant(index=0):
    return Mutant(
        id=f"m-{index:03d}",
        operator="test",
        description="test mutant",
        source="module m; wire changed; endmodule\n",
    )


def test_baseline_hidden_root_failure_blocks_certification_before_any_mutant_runs(
    tmp_path, monkeypatch
):
    """A missing hidden root must fail the whole task closed, not report every
    mutant as a coincidental "kill" of the same setup error (the exact
    fail-open bug this baseline check exists to close)."""

    task = _fixture_task(tmp_path)
    monkeypatch.setattr(mutate_module, "resolve_task", lambda _task_id: task)

    def refuse_to_generate(*_args, **_kwargs):
        raise AssertionError("mutants must never be generated when the baseline fails")

    monkeypatch.setattr(mutate_module, "generate_mutants", refuse_to_generate)
    monkeypatch.setattr(
        mutate_module,
        "run_lint",
        lambda _submission: ({"stage": 0, "name": "lint", "status": "pass"}, ""),
    )
    monkeypatch.setattr(
        mutate_module,
        "run_sim",
        lambda *args, **kwargs: (
            {"stage": 1, "name": "sim", "status": "fail"},
            f"{HIDDEN_FAILURE_PREFIX}GATETRUTH_HIDDEN_ROOT is required for registered task fixture\n",
        ),
    )

    report = run_mutation(task_id="fixture", min_kill=95, seed=1337, official=True)

    assert report["status"] == "setup_error"
    assert report["baseline"]["stage"] == "sim"
    assert HIDDEN_FAILURE_PREFIX in report["status_reason"]
    assert report["total_generated"] == 0
    assert report["results"] == []
    assert report["kill_rate"] == 0.0


def test_baseline_malformed_hidden_module_also_fails_closed(tmp_path, monkeypatch):
    """Same fail-closed behavior for a hidden module that fails to load for a
    reason other than a missing mount (e.g. a syntax error, a name collision) --
    any baseline sim failure blocks certification, not just a missing root."""

    task = _fixture_task(tmp_path)
    monkeypatch.setattr(mutate_module, "resolve_task", lambda _task_id: task)
    monkeypatch.setattr(
        mutate_module,
        "generate_mutants",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("mutants must never be generated when the baseline fails")
        ),
    )
    monkeypatch.setattr(
        mutate_module,
        "run_lint",
        lambda _submission: ({"stage": 0, "name": "lint", "status": "pass"}, ""),
    )
    monkeypatch.setattr(
        mutate_module,
        "run_sim",
        lambda *args, **kwargs: (
            {"stage": 1, "name": "sim", "status": "fail"},
            f"{HIDDEN_FAILURE_PREFIX}hidden module defines no cocotb tests: fixture\n",
        ),
    )

    report = run_mutation(task_id="fixture", min_kill=95, seed=1337, official=True)

    assert report["status"] == "setup_error"
    assert "hidden module defines no cocotb tests" in report["status_reason"]


def test_zero_generated_mutants_is_unsupported_not_vacuous_100_percent(
    tmp_path, monkeypatch
):
    task = _fixture_task(tmp_path)
    monkeypatch.setattr(mutate_module, "resolve_task", lambda _task_id: task)
    monkeypatch.setattr(mutate_module, "_run_baseline", lambda *a, **k: {
        "status": "pass", "stage": None, "log": ""
    })
    monkeypatch.setattr(mutate_module, "generate_mutants", lambda *_a, **_k: [])

    report = run_mutation(task_id="fixture", min_kill=95, seed=1337)

    assert report["status"] == "unsupported"
    assert report["total"] == 0
    assert report["kill_rate"] == 0.0


def test_all_mutants_invalid_is_unsupported_not_vacuous_100_percent(tmp_path, monkeypatch):
    task = _fixture_task(tmp_path)
    mutants = [_fixture_mutant(0), _fixture_mutant(1)]
    monkeypatch.setattr(mutate_module, "resolve_task", lambda _task_id: task)
    monkeypatch.setattr(mutate_module, "_run_baseline", lambda *a, **k: {
        "status": "pass", "stage": None, "log": ""
    })
    monkeypatch.setattr(mutate_module, "generate_mutants", lambda *_a, **_k: mutants)
    monkeypatch.setattr(
        mutate_module,
        "_run_one",
        lambda _task_id, mutant, *, official: {
            "id": mutant.id,
            "operator": mutant.operator,
            "description": mutant.description,
            "stillborn": True,
            "setup_error": False,
            "killed_by": None,
            "indeterminate": False,
        },
    )

    report = run_mutation(task_id="fixture", min_kill=95, seed=1337)

    assert report["status"] == "unsupported"
    assert report["total_generated"] == 2
    assert report["stillborn"] == 2
    assert report["total"] == 0
    assert report["kill_rate"] == 0.0


def test_formal_only_kill_counts_as_survived_for_the_sim_metric(tmp_path, monkeypatch):
    """A mutant that compiles, passes simulation, and is only caught by formal
    must not inflate the metric labeled as a simulation-testbench kill rate --
    it is reported separately via formal_only_kills instead."""

    task = _fixture_task(tmp_path)
    mutants = [_fixture_mutant(0)]
    monkeypatch.setattr(mutate_module, "resolve_task", lambda _task_id: task)
    monkeypatch.setattr(mutate_module, "_run_baseline", lambda *a, **k: {
        "status": "pass", "stage": None, "log": ""
    })
    monkeypatch.setattr(mutate_module, "generate_mutants", lambda *_a, **_k: mutants)
    monkeypatch.setattr(
        mutate_module,
        "_run_one",
        lambda _task_id, mutant, *, official: {
            "id": mutant.id,
            "operator": mutant.operator,
            "description": mutant.description,
            "stillborn": False,
            "setup_error": False,
            "killed_by": "formal",
            "indeterminate": False,
        },
    )

    report = run_mutation(task_id="fixture", min_kill=0, seed=1337)

    assert report["status"] == "ok"
    assert report["killed"] == 0
    assert report["kill_rate"] == 0.0
    assert report["survived"] == 1
    assert report["formal_only_kills"] == 1


def test_double_timeout_is_indeterminate_and_counts_against_the_rate_not_survived(
    tmp_path, monkeypatch
):
    task = _fixture_task(tmp_path)
    mutants = [_fixture_mutant(0), _fixture_mutant(1)]
    monkeypatch.setattr(mutate_module, "resolve_task", lambda _task_id: task)
    monkeypatch.setattr(mutate_module, "_run_baseline", lambda *a, **k: {
        "status": "pass", "stage": None, "log": ""
    })
    monkeypatch.setattr(mutate_module, "generate_mutants", lambda *_a, **_k: mutants)

    def fake_run_one(_task_id, mutant, *, official):
        indeterminate = mutant.id == "m-000"
        return {
            "id": mutant.id,
            "operator": mutant.operator,
            "description": mutant.description,
            "stillborn": False,
            "setup_error": False,
            "killed_by": None if indeterminate else "sim",
            "indeterminate": indeterminate,
        }

    monkeypatch.setattr(mutate_module, "_run_one", fake_run_one)

    report = run_mutation(task_id="fixture", min_kill=0, seed=1337)

    assert report["status"] == "ok"
    assert report["indeterminate"] == 1
    assert report["killed"] == 1
    assert report["survived"] == 0
    assert report["total"] == 2
    # indeterminate counts against the rate: 1/2, not treated as a kill.
    assert report["kill_rate"] == 50.0
    # and the partition invariant holds exactly.
    assert report["killed"] + report["survived"] + report["indeterminate"] == report["total"]


def test_count_invariants_hold_with_a_mixed_batch(tmp_path, monkeypatch):
    """total = killed + survived + indeterminate, and total_generated =
    total + stillborn + setup_errors, for a batch exercising every category."""

    task = _fixture_task(tmp_path)
    mutants = [_fixture_mutant(i) for i in range(5)]
    monkeypatch.setattr(mutate_module, "resolve_task", lambda _task_id: task)
    monkeypatch.setattr(mutate_module, "_run_baseline", lambda *a, **k: {
        "status": "pass", "stage": None, "log": ""
    })
    monkeypatch.setattr(mutate_module, "generate_mutants", lambda *_a, **_k: mutants)

    plan = {
        "m-000": {"stillborn": True, "setup_error": False, "killed_by": None, "indeterminate": False},
        "m-001": {"stillborn": False, "setup_error": False, "killed_by": "sim", "indeterminate": False},
        "m-002": {"stillborn": False, "setup_error": False, "killed_by": None, "indeterminate": False},
        "m-003": {"stillborn": False, "setup_error": False, "killed_by": None, "indeterminate": True},
        "m-004": {"stillborn": False, "setup_error": False, "killed_by": "formal", "indeterminate": False},
    }

    def fake_run_one(_task_id, mutant, *, official):
        return {
            "id": mutant.id,
            "operator": mutant.operator,
            "description": mutant.description,
            **plan[mutant.id],
        }

    monkeypatch.setattr(mutate_module, "_run_one", fake_run_one)

    report = run_mutation(task_id="fixture", min_kill=0, seed=1337)

    assert report["total_generated"] == 5
    assert report["stillborn"] == 1
    assert report["setup_errors"] == 0
    assert report["total"] == 4
    assert report["killed"] == 1
    assert report["formal_only_kills"] == 1
    assert report["survived"] == 2  # m-002 (clean) and m-004 (formal-only)
    assert report["indeterminate"] == 1
    assert report["killed"] + report["survived"] + report["indeterminate"] == report["total"]
    assert report["total"] + report["stillborn"] + report["setup_errors"] == report["total_generated"]
    assert report["kill_rate"] == 25.0


def test_run_baseline_attributes_the_failing_stage(tmp_path, monkeypatch):
    task = _fixture_task(tmp_path)
    monkeypatch.setattr(mutate_module, "resolve_task", lambda _task_id: task)
    monkeypatch.setattr(
        mutate_module,
        "run_lint",
        lambda _submission: ({"stage": 0, "name": "lint", "status": "fail"}, "syntax error"),
    )

    result = _run_baseline("fixture", "module m; endmodule\n", official=False)

    assert result == {"status": "fail", "stage": "lint", "log": "syntax error"}


def test_mutator_generates_expected_gray_operators():
    source = "if (rst)\n    bin <= '0;\nelse if (en)\n    bin <= bin + 1'b1;\nassign gray = bin ^ (bin >> 1);\n"
    operators = {mutant.operator for mutant in generate_mutants("t1_gray_counter", source)}
    assert "reset_polarity_flip" in operators
    assert "dropped_enable" in operators
    assert "operator_inversion" in operators


def test_generic_only_mutation_excludes_task_specific_operators():
    source = """module m;
localparam LAST_TICK = CLKS_PER_BIT - 1;
endmodule
"""

    generic = generate_mutants(
        "t2_uart_tx",
        source,
        include_task_specs=False,
    )
    default = generate_mutants("t2_uart_tx", source)

    assert all(mutant.operator != "off_by_one_counter_limit" for mutant in generic)
    assert any(mutant.operator == "off_by_one_counter_limit" for mutant in default)
    assert default == generate_mutants(
        "t2_uart_tx",
        source,
        include_task_specs=True,
    )
    assert generate_mutants("no_such_task", source, include_task_specs=False) == (
        generate_mutants("no_such_task", source)
    )


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
