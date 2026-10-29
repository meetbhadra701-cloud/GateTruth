// EVALUATOR-AUTHORED SUPPLEMENTARY VARIANT -- NOT UPSTREAM-ISSUED; DELIBERATELY NOT
// SPEC-COMPLIANT in style (spec forbids behavioral constructs). Pre-registered as a
// sensitivity probe only: functionally identical to decoder_2to4.v, reported separately,
// excluded from the primary result denominators.
module decoder_2to4 (
    input  [1:0] in,
    input        enable,
    output [3:0] out
);
    assign out = enable ? (4'b0001 << in) : 4'b0000;
endmodule
