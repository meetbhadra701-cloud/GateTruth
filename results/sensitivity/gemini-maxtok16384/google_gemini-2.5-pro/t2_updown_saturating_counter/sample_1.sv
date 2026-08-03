// t2_updown_saturating_counter
// REDACTED-CANARY

module updown_saturating_counter #(
    parameter int WIDTH = 8
) (
    input  logic             clk,
    input  logic             rst,      // synchronous, active-high
    input  logic             en,
    input  logic             up_down,  // 1 = count up, 0 = count down
    output logic [WIDTH-1:0] count     // registered, saturates at 0 and 2**WIDTH-1
);

    localparam logic [WIDTH-1:0] MAX_VAL = '1;
    localparam logic [WIDTH-1:0] MIN_VAL = '0;

    always_ff @(posedge clk) begin
        if (rst) begin
            count <= MIN_VAL;
        end else if (en) begin
            if (up_down) begin // Count up
                if (count < MAX_VAL) begin
                    count <= count + 1;
                end
            end else begin // Count down
                if (count > MIN_VAL) begin
                    count <= count - 1;
                end
            end
        end
        // If not rst and not en, count holds its value implicitly.
    end

endmodule
