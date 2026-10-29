// EVALUATOR-AUTHORED REFERENCE -- NOT UPSTREAM-ISSUED ArchXBench RTL.
// Task:   ArchXBench level-0/mux2to1 @ 0db0d0de25aad5238393d51bd97ce952e579fa1a
// Source of behavior: that task's design-specs.txt ("selects in0 when sel=0, in1
// when sel=1: y = (in0 & ~sel) | (in1 & sel)"). Not reviewed by ArchXBench maintainers.
module mux_2to1 (
    input  in0,
    input  in1,
    input  sel,
    output out
);
    assign out = (in0 & ~sel) | (in1 & sel);
endmodule
