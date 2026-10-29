// EVALUATOR-AUTHORED REFERENCE -- NOT UPSTREAM-ISSUED ArchXBench RTL; not maintainer-reviewed.
// Task: ArchXBench level-0/clock-divide-by-2 @ 0db0d0de25aad5238393d51bd97ce952e579fa1a
// Spec: clk_out toggles on every rising clk edge; synchronous active-high reset clears it to 0.
module clock_div2 (
    input clk,
    input rst,
    output clk_out
);
    reg toggle;
    always @(posedge clk) begin
        if (rst) toggle <= 1'b0;
        else     toggle <= ~toggle;
    end
    assign clk_out = toggle;
endmodule
