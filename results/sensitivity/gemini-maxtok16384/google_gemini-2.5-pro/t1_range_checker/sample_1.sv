// t1_range_checker - Registered inclusive range checker
// REDACTED-CANARY

module range_checker #(
    parameter int WIDTH = 8,
    parameter logic [WIDTH-1:0] LOW  = 8'd50,
    parameter logic [WIDTH-1:0] HIGH = 8'd200
) (
    input  logic             clk,
    input  logic             rst,      // synchronous, active-high
    input  logic [WIDTH-1:0] din,
    output logic             in_range  // registered: LOW <= din <= HIGH
);

    always_ff @(posedge clk) begin
        if (rst) begin
            in_range <= 1'b0;
        end else begin
            in_range <= (din >= LOW) && (din <= HIGH);
        end
    end

endmodule
