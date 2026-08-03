// t2_majority_filter — N-of-M majority-vote glitch filter
// REDACTED-CANARY

module majority_filter #(
    parameter int SAMPLES = 5
) (
    input  logic clk,
    input  logic rst,
    input  logic sample_valid,
    input  logic noisy_in,
    output logic filtered_out,
    output logic valid_out
);

    localparam PtrWidth = $clog2(SAMPLES);
    localparam CountWidth = $clog2(SAMPLES + 1);
    localparam Threshold = SAMPLES / 2;

    logic [SAMPLES-1:0]    window_reg;
    logic [PtrWidth-1:0]   write_ptr_reg;
    logic [CountWidth-1:0] ones_count_reg;
    logic [CountWidth-1:0] samples_seen_reg; // Saturates at SAMPLES

    always_ff @(posedge clk) begin
        if (rst) begin
            window_reg       <= '0;
            write_ptr_reg    <= '0;
            ones_count_reg   <= '0;
            samples_seen_reg <= '0;
            filtered_out     <= 1'b0;
            valid_out        <= 1'b0;
        end else begin
            if (sample_valid) begin
                logic oldest_sample = window_reg[write_ptr_reg];

                logic [CountWidth-1:0] next_ones_count;
                next_ones_count = ones_count_reg - oldest_sample + noisy_in;

                logic [CountWidth-1:0] next_samples_seen;
                if (samples_seen_reg < SAMPLES) begin
                    next_samples_seen = samples_seen_reg + 1;
                end else begin
                    next_samples_seen = SAMPLES;
                end

                window_reg[write_ptr_reg] <= noisy_in;

                if (write_ptr_reg == SAMPLES - 1) begin
                    write_ptr_reg <= '0;
                end else begin
                    write_ptr_reg <= write_ptr_reg + 1;
                end

                ones_count_reg   <= next_ones_count;
                samples_seen_reg <= next_samples_seen;

                filtered_out <= (next_ones_count > Threshold);
                valid_out    <= valid_out | (next_samples_seen == SAMPLES);
            end
        end
    end

endmodule
