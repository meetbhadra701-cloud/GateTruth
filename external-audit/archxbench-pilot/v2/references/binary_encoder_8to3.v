// EVALUATOR-AUTHORED REFERENCE -- NOT UPSTREAM-ISSUED ArchXBench RTL; not maintainer-reviewed.
// Task: ArchXBench level-0/binary-encoder @ 0db0d0de25aad5238393d51bd97ce952e579fa1a
// Spec: "Assumes exactly one input is high. Outputs the corresponding binary index."
// ASSUMPTION: behavior for non-one-hot input is UNSPECIFIED; only the 8 one-hot inputs are legal.
module binary_encoder_8to3 (
    input  [7:0] in,
    output [2:0] out
);
    assign out[0] = in[1] | in[3] | in[5] | in[7];
    assign out[1] = in[2] | in[3] | in[6] | in[7];
    assign out[2] = in[4] | in[5] | in[6] | in[7];
endmodule
