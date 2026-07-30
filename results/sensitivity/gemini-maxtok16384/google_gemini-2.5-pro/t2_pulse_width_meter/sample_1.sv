module pulse_width_meter #(
    parameter int WIDTH = 8
) (
    input  logic             clk,
    input  logic             rst,       // synchronous, active-high reset
    input  logic             level_in,
    output logic [WIDTH-1:0] width_out,
    output logic             width_valid,
    output logic             overflow
);

    // Internal state for the current measurement.
    logic [WIDTH-1:0] count;
    logic             is_overflow;

    // Registered version of level_in to detect edges.
    logic             level_in_prev;

    always_ff @(posedge clk) begin
        if (rst) begin
            // Reset all state and outputs to their idle values.
            count <= '0;
            is_overflow <= 1'b0;
            level_in_prev <= 1'b0;
            width_out <= '0;
            width_valid <= 1'b0;
            overflow <= 1'b0;
        end else begin
            // Register level_in for edge detection on the next cycle.
            level_in_prev <= level_in;

            // By default, the measurement is not valid. It will be asserted for one
            // cycle on a falling edge.
            width_valid <= 1'b0;
            // width_out and overflow hold their previous values unless a pulse completes.

            // Check for a falling edge on level_in, which marks the end of a pulse.
            if (level_in_prev && !level_in) begin
                // A pulse just ended. Output the measured values.
                width_out <= count;
                width_valid <= 1'b1;
                overflow <= is_overflow;

                // Reset internal state for the next measurement.
                count <= '0;
                is_overflow <= 1'b0;
            end
            // If not a falling edge, check if we are in the middle of a pulse.
            else if (level_in) begin
                // Pulse is high, so increment the counter.
                if (count == {WIDTH{1'b1}}) begin
                    // Counter is saturated. Set the overflow flag and hold the count.
                    is_overflow <= 1'b1;
                end else begin
                    // Increment the counter.
                    count <= count + 1;
                end
            end
            // If level_in is low and was also low previously (steady low),
            // the internal state (count, is_overflow) is already zero from the
            // last falling edge, so no action is needed.
        end
    end

endmodule
