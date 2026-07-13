module toy_trackb (
    input  logic clk,
    input  logic rst,
    input  logic a,
    input  logic b,
    output logic y
);
    (* keep = "true" *) logic keep0;
    (* keep = "true" *) logic keep1;
    (* keep = "true" *) logic keep2;
    (* keep = "true" *) logic keep3;
    (* keep = "true" *) logic keep4;
    (* keep = "true" *) logic keep5;

    always_ff @(posedge clk) begin
        if (rst) begin
            y <= 1'b0;
            keep0 <= 1'b0;
            keep1 <= 1'b0;
            keep2 <= 1'b0;
            keep3 <= 1'b0;
            keep4 <= 1'b0;
            keep5 <= 1'b0;
        end else begin
            y <= a ^ b;
            keep0 <= a & b;
            keep1 <= keep0 ^ a;
            keep2 <= keep1 ^ b;
            keep3 <= keep2 ^ keep0;
            keep4 <= keep3 ^ keep1;
            keep5 <= keep4 ^ keep2;
        end
    end
endmodule
