"""Regression test for GTFS-039: sample_and_expect() in
tasksB/b3_reduce_area_fir/tb/test_b3_reduce_area_fir.py must accept a result
that arrives at exactly MAX_LATENCY (6) cycles after its sample -- the
contract's own stated maximum, not one cycle short of it.

The original bug: the check loop ran `range(MAX_LATENCY)` (6 iterations,
covering only 0..5 cycles after the sample) and then advanced past cycle 6
without ever checking it, so a design that legitimately completed at the
maximum allowed latency would fail with "no result within 6 cycles of sample
N" even though it satisfied the spec exactly. Verified directly against the
real toolchain before writing this test: the pre-fix testbench (git blob
55975c3^:tasksB/b3_reduce_area_fir/tb/test_b3_reduce_area_fir.py) rejected the
fixture design below with exactly that assertion; the fixed testbench accepts
it. None of the 7 real committed b3_reduce_area_fir official manifests were
affected by this bug -- the 3 that reached the sim stage at all (Haiku,
Sonnet, Gemini 2.5 Pro) all recorded sim: pass and failed only at the
separate objective (area) stage; the other 4 failed at lint/sim compilation
before this code path could run at all.
"""

from __future__ import annotations

from pathlib import Path

from harness.runner import run_sim
from harness.trackb import resolve_track_b_task

# Same FIR core as tasksB/b3_reduce_area_fir/baseline/fir.sv, but result_out
# and result_valid pass through an extra 6-stage pipeline before reaching the
# ports, so the externally observed latency is exactly MAX_LATENCY (6)
# instead of the baseline's 1 cycle -- the boundary this bug hid.
_MAX_LATENCY_DESIGN = """\
module fir_filter_loadable #(
    parameter int NTAPS      = 4,
    parameter int DATA_WIDTH = 8,
    parameter int COEF_WIDTH = 8,
    parameter int ACC_WIDTH  = 24
) (
    input  logic                          clk,
    input  logic                          rst,
    input  logic                          coef_load_valid,
    input  logic [$clog2(NTAPS)-1:0]      coef_load_index,
    input  logic signed [COEF_WIDTH-1:0]  coef_load_value,
    input  logic                          sample_valid,
    input  logic signed [DATA_WIDTH-1:0]  sample_in,
    output logic signed [ACC_WIDTH-1:0]   result_out,
    output logic                          result_valid
);
    localparam int PRODW = DATA_WIDTH + COEF_WIDTH;
    localparam int EXTRA_DELAY = 6;

    logic signed [COEF_WIDTH-1:0] coef_mem [0:NTAPS-1];
    logic signed [DATA_WIDTH-1:0] x_hist   [0:NTAPS-2];

    logic signed [DATA_WIDTH-1:0] tap_sample [0:NTAPS-1];
    assign tap_sample[0] = sample_in;

    genvar gi;
    generate
        for (gi = 1; gi < NTAPS; gi++) begin : g_tap
            assign tap_sample[gi] = x_hist[gi-1];
        end
    endgenerate

    logic signed [PRODW-1:0] prod [0:NTAPS-1];
    generate
        for (gi = 0; gi < NTAPS; gi++) begin : g_prod
            assign prod[gi] = coef_mem[gi] * tap_sample[gi];
        end
    endgenerate

    logic signed [ACC_WIDTH-1:0] sum_comb;
    always_comb begin
        sum_comb = '0;
        for (int i = 0; i < NTAPS; i++) sum_comb = sum_comb + ACC_WIDTH'(prod[i]);
    end

    logic signed [ACC_WIDTH-1:0] result_pipe [0:EXTRA_DELAY];
    logic                        valid_pipe  [0:EXTRA_DELAY];

    always_ff @(posedge clk) begin
        if (rst) begin
            for (int i = 0; i < NTAPS; i++)   coef_mem[i] <= '0;
            for (int i = 0; i < NTAPS - 1; i++) x_hist[i] <= '0;
            for (int i = 0; i <= EXTRA_DELAY; i++) begin
                result_pipe[i] <= '0;
                valid_pipe[i]  <= 1'b0;
            end
        end else begin
            if (coef_load_valid) coef_mem[coef_load_index] <= coef_load_value;
            valid_pipe[0] <= 1'b0;
            if (sample_valid) begin
                result_pipe[0] <= sum_comb;
                valid_pipe[0]  <= 1'b1;
                for (int i = 1; i <= NTAPS - 2; i++) x_hist[i] <= x_hist[i-1];
                x_hist[0] <= sample_in;
            end
            for (int i = 1; i <= EXTRA_DELAY; i++) begin
                result_pipe[i] <= result_pipe[i-1];
                valid_pipe[i]  <= valid_pipe[i-1];
            end
        end
    end

    assign result_out   = result_pipe[EXTRA_DELAY];
    assign result_valid = valid_pipe[EXTRA_DELAY];
endmodule
"""


def test_max_latency_design_clears_the_public_smoke_test(tmp_path: Path) -> None:
    task = resolve_track_b_task("b3_reduce_area_fir")
    design = tmp_path / "fir_maxlatency.sv"
    design.write_text(_MAX_LATENCY_DESIGN, encoding="utf-8")

    work_root = tmp_path / "work"
    work_root.mkdir()
    stage, log, _hidden_sha256, _hidden_test_count = run_sim(task, design, work_root)

    assert stage["status"] == "pass", log


def test_real_baseline_still_clears_the_public_smoke_test(tmp_path: Path) -> None:
    """Regression guard alongside the boundary test above: confirms the fix
    didn't tighten anything for the design that already worked."""
    task = resolve_track_b_task("b3_reduce_area_fir")
    work_root = tmp_path / "work"
    work_root.mkdir()

    stage, log, _hidden_sha256, _hidden_test_count = run_sim(
        task, task.root / "baseline" / "fir.sv", work_root
    )

    assert stage["status"] == "pass", log
