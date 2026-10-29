// EVALUATOR-AUTHORED REFERENCE -- NOT UPSTREAM-ISSUED ArchXBench RTL; not maintainer-reviewed.
// Task: ArchXBench level-0/up-counter @ 0db0d0de25aad5238393d51bd97ce952e579fa1a
// Spec: synchronous incrementer, synchronous active-high reset to zero, wraps modulo 256.
module up_counter8(
    input clk,
    input rst,
    output [7:0] count
);
    reg [7:0] value;
    always @(posedge clk) begin
        if (rst) value <= 8'd0;
        else     value <= value + 8'd1;
    end
    assign count = value;
endmodule
