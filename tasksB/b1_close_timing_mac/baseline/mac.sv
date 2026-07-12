// b1 candidate BASELINE: functionally-exact MAC with a deliberately slow
// shift-add multiply structure (long mux/add chain) in one comb cycle.
module fixed_point_mac #(
    parameter int DATA_WIDTH = 16,
    parameter int ACC_WIDTH  = 48
) (
    input  logic                        clk,
    input  logic                        rst,
    input  logic                        en,
    input  logic                        clear,
    input  logic signed [DATA_WIDTH-1:0] a,
    input  logic signed [DATA_WIDTH-1:0] b,
    output logic signed [ACC_WIDTH-1:0]  acc
);
    // Shift-add product: sequential chain of conditional adds, forced into a
    // single combinational cone. Functionally identical to a*b (signed).
    logic signed [2*DATA_WIDTH-1:0] partial [DATA_WIDTH:0];
    logic signed [2*DATA_WIDTH-1:0] a_ext;
    assign a_ext = {{DATA_WIDTH{a[DATA_WIDTH-1]}}, a};

    always_comb begin
        partial[0] = '0;
        for (int i = 0; i < DATA_WIDTH; i++) begin
            if (i == DATA_WIDTH-1)
                // MSB of a signed multiplier carries negative weight.
                partial[i+1] = partial[i] - ((b[i] ? a_ext : '0) <<< i);
            else
                partial[i+1] = partial[i] + ((b[i] ? a_ext : '0) <<< i);
        end
    end

    wire signed [2*DATA_WIDTH-1:0] product = partial[DATA_WIDTH];

    always_ff @(posedge clk) begin
        if (rst)        acc <= '0;
        else if (clear) acc <= '0;
        else if (en)    acc <= acc + ACC_WIDTH'(product);
    end
endmodule
