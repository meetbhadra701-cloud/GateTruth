// EVALUATOR-AUTHORED REFERENCE -- NOT UPSTREAM-ISSUED ArchXBench RTL.
// Task:   ArchXBench level-0/decoder-2to4 @ 0db0d0de25aad5238393d51bd97ce952e579fa1a
// Source of behavior: that task's design-specs.txt. The spec requires structural NOT/AND
// gate instances and forbids assign/case/always, so this reference follows that
// style even though GateTruth's text-level operators may have little to mutate in it.
// Not reviewed by ArchXBench maintainers.
module decoder_2to4 (
    input  [1:0] in,
    input        enable,
    output [3:0] out
);
    wire n1, n0;
    not u_not1 (n1, in[1]);
    not u_not0 (n0, in[0]);
    and u_and0 (out[0], n1,    n0,    enable);
    and u_and1 (out[1], n1,    in[0], enable);
    and u_and2 (out[2], in[1], n0,    enable);
    and u_and3 (out[3], in[1], in[0], enable);
endmodule
