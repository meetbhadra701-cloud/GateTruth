module mm_timer #(
    parameter int WIDTH = 16
) (
    input  logic             clk,
    input  logic             rst,
    input  logic             en,
    input  logic             load,
    input  logic [WIDTH-1:0] load_val,
    input  logic             auto_reload,
    output logic [WIDTH-1:0] count,
    output logic             tick
);

    // Internal register to store the reload value, set on 'load'.
    logic [WIDTH-1:0] period;

    always_ff @(posedge clk) begin
        if (rst) begin
            // Synchronous, active-high reset clears all state.
            count <= {WIDTH{1'b0}};
            period <= {WIDTH{1'b0}};
            tick <= 1'b0;
        end else begin
            // Default assignment for tick ensures it's a one-cycle pulse.
            tick <= 1'b0;

            if (load) begin
                // Load has highest priority (after reset).
                // It updates both the counter and the stored period.
                count <= load_val;
                period <= load_val;
            end else if (en && (count != '0)) begin
                // Counting is enabled and the counter is not at zero.
                if (count == 1'b1) begin
                    // Counter is expiring (decrementing from 1).
                    tick <= 1'b1;
                    if (auto_reload) begin
                        // Auto-reload mode: reload from the stored period.
                        count <= period;
                    end else begin
                        // One-shot mode: stop at zero.
                        count <= {WIDTH{1'b0}};
                    end
                end else begin
                    // Normal decrement.
                    count <= count - 1;
                end
            end
            // If not loading, and not enabled or count is already zero,
            // the counter holds its value. The 'tick' output remains low
            // due to the default assignment at the top of the 'else' block.
        end
    end

endmodule
