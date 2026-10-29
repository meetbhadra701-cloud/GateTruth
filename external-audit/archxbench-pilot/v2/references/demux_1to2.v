// EVALUATOR-AUTHORED REFERENCE -- NOT UPSTREAM-ISSUED ArchXBench RTL; not maintainer-reviewed.
// Task: ArchXBench level-0/demux-1to2 @ 0db0d0de25aad5238393d51bd97ce952e579fa1a
// Spec: out0 = in AND NOT(sel); out1 = in AND sel.
module demux_1to2 (
    input  in,
    input  sel,
    output out0,
    output out1
);
    assign out0 = in & ~sel;
    assign out1 = in & sel;
endmodule
