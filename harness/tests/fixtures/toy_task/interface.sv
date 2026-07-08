// toy_task — locked port contract (NON-SCORED harness fixture)
module toy #(
    parameter int WIDTH = 4
) (
    input  logic             clk,
    input  logic             rst,   // synchronous, active-high
    input  logic [WIDTH-1:0] a,
    output logic [WIDTH-1:0] y
);
    // Implementation provided by ref/ref.sv.
endmodule
