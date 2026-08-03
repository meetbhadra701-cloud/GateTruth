// t1_priority_encoder - Registered priority encoder
// REDACTED-CANARY

module priority_encoder #(
    parameter int WIDTH = 8
) (
    input  logic                     clk,
    input  logic                     rst,   // synchronous, active-high
    input  logic [WIDTH-1:0]         in,
    output logic [$clog2(WIDTH)-1:0] out,   // index of the highest set bit (registered)
    output logic                     valid  // registered: high iff any input bit was set
);

    logic [$clog2(WIDTH)-1:0] next_out;
    logic                     next_valid;

    always_comb begin
        // Combinational logic to determine the next state of the outputs.
        // Priority is given to the most significant bit.
        // If 'in' is all zeros, 'valid' will be low and 'out' will be 0.

        next_valid = |in;
        next_out = '0; // Default output if no bits are set.

        // A for-loop iterating from MSB to LSB is a standard way to model a priority encoder.
        // The first set bit found (highest index) determines the output.
        for (int i = WIDTH - 1; i >= 0; i--) begin
            if (in[i]) begin
                next_out = i;
                break; // Exit loop once the highest priority bit is found.
            end
        end
    end

    // Registered output stage.
    always_ff @(posedge clk) begin
        if (rst) begin
            out   <= '0;
            valid <= 1'b0;
        end else begin
            out   <= next_out;
            valid <= next_valid;
        end
    end

endmodule
