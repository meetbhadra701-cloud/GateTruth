// EVALUATOR-AUTHORED REFERENCE -- NOT UPSTREAM-ISSUED ArchXBench RTL; not maintainer-reviewed.
// Task: ArchXBench level-0/gray-counter @ 0db0d0de25aad5238393d51bd97ce952e579fa1a
// Spec: internal binary counter, gray = binary ^ (binary >> 1), synchronous active-high reset.
// ASSUMPTION: reset value is binary 0 (gray 0), the only value the formula gives for a cleared counter.
module gray_counter8(
    input wire clk,
    input wire rst,
    output wire [7:0] count
);
    reg [7:0] bin;
    always @(posedge clk) begin
        if (rst) bin <= 8'd0;
        else     bin <= bin + 8'd1;
    end
    assign count = bin ^ (bin >> 1);
endmodule
