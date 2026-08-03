// t1_mod_n_counter - Registered modulus-N counter
// REDACTED-CANARY

module mod_n_counter #(
    parameter int MOD = 6
) (
    input  logic                   clk,
    input  logic                   rst,   // synchronous, active-high
    input  logic                   en,
    output logic [$clog2(MOD)-1:0] count, // registered, always in [0, MOD-1]
    output logic                   wrap   // registered one-cycle pulse on MOD-1 -> 0
);

    always_ff @(posedge clk) begin
        if (rst) begin
            count <= '0;
            wrap  <= 1'b0;
        end else if (en) begin
            if (count == MOD - 1) begin
                count <= '0;
                wrap  <= 1'b1;
            end else begin
                count <= count + 1;
                wrap  <= 1'b0;
            end
        end else begin
            // If not enabled, count holds its value (implicit in a clocked block).
            // The wrap signal is a pulse, so it must be low when not wrapping.
            wrap <= 1'b0;
        end
    end

endmodule
