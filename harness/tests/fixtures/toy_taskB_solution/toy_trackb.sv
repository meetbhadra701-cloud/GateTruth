module toy_trackb (
    input  logic clk,
    input  logic rst,
    input  logic a,
    input  logic b,
    output logic y
);
    always_ff @(posedge clk) begin
        if (rst) y <= 1'b0;
        else y <= a ^ b;
    end
endmodule
