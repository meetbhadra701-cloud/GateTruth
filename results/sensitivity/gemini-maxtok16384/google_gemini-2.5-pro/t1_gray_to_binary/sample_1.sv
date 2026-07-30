module gray_to_binary #(
    parameter int WIDTH = 8
) (
    input  logic             clk,
    input  logic             rst,   // synchronous, active-high
    input  logic [WIDTH-1:0] gray,
    output logic [WIDTH-1:0] bin    // registered binary decode of gray
);

    logic [WIDTH-1:0] bin_next;

    always_comb begin
        bin_next[WIDTH-1] = gray[WIDTH-1];
        for (int i = WIDTH - 2; i >= 0; i--) begin
            bin_next[i] = bin_next[i+1] ^ gray[i];
        end
    end

    always_ff @(posedge clk) begin
        if (rst) begin
            bin <= {WIDTH{1'b0}};
        end else begin
            bin <= bin_next;
        end
    end

endmodule
