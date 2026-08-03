```systemverilog
// t2_pulse_stretcher - Non-retriggerable pulse stretcher
// REDACTED-CANARY

module pulse_stretcher #(
    parameter int DURATION = 8
) (
    input  logic clk,
    input  logic rst,        // synchronous, active-high
    input  logic pulse_in,
    output logic out         // registered, high for exactly DURATION cycles per accepted trigger
);

    localparam CNT_WIDTH = (DURATION > 1) ? $clog2(DURATION) : 1;
