// toy_task — reference implementation (NON-SCORED harness fixture)
module toy #(
    parameter int WIDTH = 4
) (
    input  logic             clk,
    input  logic             rst,
    input  logic [WIDTH-1:0] a,
    output logic [WIDTH-1:0] y
);
    always_ff @(posedge clk) begin
        if (rst)
            y <= '0;
        else
            y <= a + 1'b1;
    end
endmodule
