// EVALUATOR-AUTHORED REFERENCE -- NOT UPSTREAM-ISSUED ArchXBench RTL; not maintainer-reviewed.
// Task: ArchXBench level-0/comparator-8bit @ 0db0d0de25aad5238393d51bd97ce952e579fa1a
// Spec: two comparator_4bit instances, MSB nibble decides unless equal, unsigned.
// comparator_4bit is not supplied by the task, so it is included here (same behavior as the
// level-0/comparator-4bit reference).
module comparator_4bit(input [3:0] a, input [3:0] b, output gt, eq, lt);
    assign gt = (a > b);
    assign eq = (a == b);
    assign lt = (a < b);
endmodule

module comparator_8bit(input [7:0] a, input [7:0] b, output gt, eq, lt);
    wire gt_hi, eq_hi, lt_hi, gt_lo, eq_lo, lt_lo;
    comparator_4bit u_hi (.a(a[7:4]), .b(b[7:4]), .gt(gt_hi), .eq(eq_hi), .lt(lt_hi));
    comparator_4bit u_lo (.a(a[3:0]), .b(b[3:0]), .gt(gt_lo), .eq(eq_lo), .lt(lt_lo));
    assign gt = gt_hi | (eq_hi & gt_lo);
    assign eq = eq_hi & eq_lo;
    assign lt = lt_hi | (eq_hi & lt_lo);
endmodule
