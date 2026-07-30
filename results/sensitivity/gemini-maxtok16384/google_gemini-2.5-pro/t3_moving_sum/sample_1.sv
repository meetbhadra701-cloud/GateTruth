module moving_sum #(
    parameter int WIDTH  = 8,
    parameter int WINDOW = 4
) (
    input  logic                            clk,
    input  logic                            rst,
    input  logic                            sample_valid,
    input  logic [WIDTH-1:0]                sample,
    output logic [WIDTH+$clog2(WINDOW)-1:0] sum_out,
    output logic                            valid_out
);

    localparam int SUM_WIDTH = WIDTH + $clog2(WINDOW);
    localparam int PTR_WIDTH = $clog2(WINDOW);
    localparam int FILL_COUNT_WIDTH = $clog2(WINDOW + 1);

    // Internal state registers
    logic [SUM_WIDTH:0] sum_reg; // 1 bit wider to prevent intermediate overflow
    logic valid_reg;
    logic [WIDTH-1:0] window_mem [0:WINDOW-1];
    logic [PTR_WIDTH-1:0] wr_ptr;
    logic [FILL_COUNT_WIDTH-1:0] fill_count;

    assign sum_out = sum_reg[SUM_WIDTH-1:0];
    assign valid_out = valid_reg;

    always_ff @(posedge clk) begin
        if (rst) begin
            sum_reg    <= '0;
            valid_reg  <= 1'b0;
            wr_ptr     <= '0;
            fill_count <= '0;
            for (int i = 0; i < WINDOW; i++) begin
                window_mem[i] <= '0;
            end
        end else begin
            if (sample_valid) begin
                // The sample being replaced is at the current write pointer.
                // During ramp-up, the memory contains zeros, so this correctly subtracts zero.
                logic [WIDTH-1:0] oldest_sample = window_mem[wr_ptr];

                // Update sum: add new sample, subtract the oldest.
                // The calculation uses a sum register 1 bit wider than the output
                // to prevent overflow in the intermediate (sum_reg + sample) operation.
                sum_reg <= sum_reg + sample - oldest_sample;

                // Store the new sample, overwriting the oldest one.
                window_mem[wr_ptr] <= sample;

                // Advance the write pointer, wrapping around.
                if (wr_ptr == WINDOW - 1) begin
                    wr_ptr <= '0;
                end else begin
                    wr_ptr <= wr_ptr + 1;
                end

                // During ramp-up, count samples until the window is full.
                if (!valid_reg) begin
                    fill_count <= fill_count + 1;
                    // valid_out becomes high on the cycle the WINDOW-th sample is processed.
                    // This happens when the fill_count (number of samples processed *before*
                    // the current one) is WINDOW-1.
                    if (fill_count == WINDOW - 1) begin
                        valid_reg <= 1'b1;
                    end
                end
            end
        end
    end

endmodule
