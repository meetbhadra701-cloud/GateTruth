// EVALUATOR-AUTHORED REFERENCE -- NOT UPSTREAM-ISSUED ArchXBench RTL.
// Task:   ArchXBench level-0/comparator-4bit @ 0db0d0de25aad5238393d51bd97ce952e579fa1a
// Source of behavior: that task's design-specs.txt (unsigned 4-bit compare, gt/eq/lt
// mutually exclusive, direct logic expressions). Not reviewed by ArchXBench maintainers.
module comparator_4bit(input [3:0] a, input [3:0] b, output gt, eq, lt);
    assign gt = (a > b);
    assign eq = (a == b);
    assign lt = (a < b);
endmodule
