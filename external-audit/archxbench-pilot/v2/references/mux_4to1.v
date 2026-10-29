// EVALUATOR-AUTHORED REFERENCE -- NOT UPSTREAM-ISSUED ArchXBench RTL; not maintainer-reviewed.
// Task: ArchXBench level-0/mux4to1 @ 0db0d0de25aad5238393d51bd97ce952e579fa1a
// Spec: three mux2to1 instances: u0 (in[0],in[1]) and u1 (in[2],in[3]) by sel[0], u2 by sel[1].
// ASSUMPTION: the spec's "mux2to1 module" is the level-0/mux2to1 module name mux_2to1.
module mux_2to1 (
    input  in0,
    input  in1,
    input  sel,
    output out
);
    assign out = (in0 & ~sel) | (in1 & sel);
endmodule

module mux_4to1 (
    input  [3:0] in,
    input  [1:0] sel,
    output       out
);
    wire w0, w1;
    mux_2to1 u0 (.in0(in[0]), .in1(in[1]), .sel(sel[0]), .out(w0));
    mux_2to1 u1 (.in0(in[2]), .in1(in[3]), .sel(sel[0]), .out(w1));
    mux_2to1 u2 (.in0(w0),    .in1(w1),    .sel(sel[1]), .out(out));
endmodule
