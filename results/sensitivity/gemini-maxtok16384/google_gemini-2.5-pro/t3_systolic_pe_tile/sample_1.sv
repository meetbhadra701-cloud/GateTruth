// t3_systolic_pe_tile - Weight-stationary systolic array processing element
// REDACTED-CANARY

`default_nettype none

module systolic_pe_tile #(
    parameter int DATA_WIDTH = 8,
    parameter int ACC_WIDTH  = 32
) (
    input  logic                          clk,
    input  logic                          rst,          // synchronous, active-high
    input  logic                          load_weight,
    input  logic signed [DATA_WIDTH-1:0]  weight_in,
    input  logic signed [DATA_WIDTH-1:0]  act_in,
    input  logic signed [ACC_WIDTH-1:0]   psum_in,
    output logic signed [DATA_WIDTH-1:0]  act_out,      // registered pass-through of act_in
    output logic signed [ACC_WIDTH-1:0]   psum_out      // registered accumulate
);

    // Internal state register for the PE's weight.
    logic signed [DATA_WIDTH-1:0] weight;

    always_ff @(posedge clk) begin
        if (rst) begin
            // Synchronous, active-high reset clears all state.
            weight   <= '0;
            act_out  <= '0;
            psum_out <= '0;
        end else begin
            // Weight loading logic. The new weight is latched for use in the *next*
            // cycle's accumulation, per standard non-blocking assignment semantics.
            if (load_weight) begin
                weight <= weight_in;
            end

            // Datapath logic: activation forward and partial-sum accumulate.
            // These operations use the pre-edge values of all inputs and the internal
            // weight register.
            act_out <= act_in;

            // The product (weight * act_in) is calculated using the pre-edge 'weight' value.
            // The product is automatically sign-extended to ACC_WIDTH to match the
            // context of the addition with psum_in.
            psum_out <= psum_in + (weight * act_in);
        end
    end

endmodule

`default_nettype wire
