// EVALUATOR-AUTHORED REFERENCE -- NOT UPSTREAM-ISSUED ArchXBench RTL; not maintainer-reviewed.
// Task: ArchXBench level-0/demux-1to4 @ 0db0d0de25aad5238393d51bd97ce952e579fa1a
// Spec: three structural demux_1to2 instances u0/u1/u2 exactly as listed in design-specs.txt.
module demux_1to2 (
    input  in,
    input  sel,
    output out0,
    output out1
);
    assign out0 = in & ~sel;
    assign out1 = in & sel;
endmodule

module demux_1to4 (
    input        in,
    input  [1:0] sel,
    output       out0,
    output       out1,
    output       out2,
    output       out3
);
    wire i_low, i_high;
    demux_1to2 u0 (.in(in),     .sel(sel[1]), .out0(i_low),  .out1(i_high));
    demux_1to2 u1 (.in(i_low),  .sel(sel[0]), .out0(out0),   .out1(out1));
    demux_1to2 u2 (.in(i_high), .sel(sel[0]), .out0(out2),   .out1(out3));
endmodule
