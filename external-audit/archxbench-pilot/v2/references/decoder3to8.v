// EVALUATOR-AUTHORED REFERENCE -- NOT UPSTREAM-ISSUED ArchXBench RTL; not maintainer-reviewed.
// Task: ArchXBench level-0/decoder-3to8 @ 0db0d0de25aad5238393d51bd97ce952e579fa1a
// Spec: two decoder_2to4 instances, in[2] selects which is enabled; structural, no behavioral code.
// NOTE: the upstream testbench prints summary module "decoder_3to8" while the DUT is "decoder3to8".
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

module decoder3to8(input [2:0] in, input enable, output [7:0] out);
    wire n2, en_lo, en_hi;
    not u_not2 (n2, in[2]);
    and u_enlo (en_lo, enable, n2);
    and u_enhi (en_hi, enable, in[2]);
    decoder_2to4 u_lo (.in(in[1:0]), .enable(en_lo), .out(out[3:0]));
    decoder_2to4 u_hi (.in(in[1:0]), .enable(en_hi), .out(out[7:4]));
endmodule
