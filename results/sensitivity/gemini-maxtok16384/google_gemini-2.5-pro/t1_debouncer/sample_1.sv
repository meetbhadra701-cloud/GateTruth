module debouncer #(
    parameter int STABLE = 8
) (
    input  logic clk,
    input  logic rst,
    input  logic noisy,
    output logic clean
);

    localparam COUNT_WIDTH = (STABLE <= 1) ? 1 : $clog2(STABLE);

    logic clean_q;
    logic [COUNT_WIDTH-1:0] count_q;

    always_ff @(posedge clk) begin
        if (rst) begin
            clean_q <= 1'b0;
            count_q <= '0;
        end else begin
            if (noisy != clean_q) begin
                if (count_q == STABLE - 1) begin
                    clean_q <= noisy;
                    count_q <= '0;
                end else begin
                    count_q <= count_q + 1;
                end
            end else begin
                count_q <= '0;
            end
        end
    end

    assign clean = clean_q;

endmodule
