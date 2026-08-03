// t1_leading_zero_counter - Registered leading-zero counter
// REDACTED-CANARY

module leading_zero_counter #(
    parameter int WIDTH = 8
) (
    input  logic                       clk,
    input  logic                       rst,   // synchronous, active-high
    input  logic [WIDTH-1:0]           in,
    output logic [$clog2(WIDTH+1)-1:0] out    // registered leading-zero count, 0..WIDTH
);

    logic [$clog2(WIDTH+1)-1:0] next_out;

    // Combinational logic to calculate the number of leading zeros.
    // This structure describes a priority encoder.
    always_comb begin
        // By default, assume 'in' is all zeros. The count is the input width.
        next_out = WIDTH;
        // Iterate from the most significant bit downwards. The loop variable 'i'
        // directly corresponds to the number of leading zeros.
        for (int i = 0; i < WIDTH; i++) begin
            // Check bit position corresponding to 'i' leading zeros.
            if (in[WIDTH - 1 - i]) begin
                next_out = i;
                break; // Found the highest-priority '1', so we can stop.
            end
        end
    end

    // Register the result.
    always_ff @(posedge clk) begin
        if (rst) begin
            out <= '0;
        end else begin
            out <= next_out;
        end
    end

endmodule
