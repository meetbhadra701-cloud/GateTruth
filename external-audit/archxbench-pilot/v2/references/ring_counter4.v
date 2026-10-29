// EVALUATOR-AUTHORED REFERENCE -- NOT UPSTREAM-ISSUED ArchXBench RTL; not maintainer-reviewed.
// Task: ArchXBench level-0/ring-counter @ 0db0d0de25aad5238393d51bd97ce952e579fa1a
// Spec: q resets to 0001 (synchronous, active high); shift left, MSB wraps to LSB.
module ring_counter4 (
    input clk,
    input rst,
    output [3:0] q
);
    reg [3:0] state;
    always @(posedge clk) begin
        if (rst) state <= 4'b0001;
        else     state <= {state[2:0], state[3]};
    end
    assign q = state;
endmodule
