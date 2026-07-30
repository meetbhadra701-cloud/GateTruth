module fir_filter_loadable #(
    parameter int NTAPS      = 4,
    parameter int DATA_WIDTH = 8,
    parameter int COEF_WIDTH = 8,
    parameter int ACC_WIDTH  = 24
) (
    input  logic                          clk,
    input  logic                          rst,
    input  logic                          coef_load_valid,
    input  logic [$clog2(NTAPS)-1:0]      coef_load_index,
    input  logic signed [COEF_WIDTH-1:0]  coef_load_value,
    input  logic                          sample_valid,
    input  logic signed [DATA_WIDTH-1:0]  sample_in,
    output logic signed [ACC_WIDTH-1:0]   result_out,
    output logic                          result_valid
);

    logic signed [COEF_WIDTH-1:0] coef_mem [NTAPS];
    logic signed [DATA_WIDTH-1:0] sample_history [NTAPS-1];

    logic signed [ACC_WIDTH-1:0] convolution_result;

    always_comb begin
        convolution_result = '0;
        convolution_result += sample_in * coef_mem[0];
        for (int i = 1; i < NTAPS; i++) begin
            convolution_result += sample_history[i-1] * coef_mem[i];
        end
    end

    always_ff @(posedge clk) begin
        if (rst) begin
            for (int i = 0; i < NTAPS; i++) begin
                coef_mem[i] <= '0;
            end
            for (int i = 0; i < NTAPS - 1; i++) begin
                sample_history[i] <= '0;
            end
            result_out   <= '0;
            result_valid <= 1'b0;
        end else begin
            if (coef_load_valid) begin
                coef_mem[coef_load_index] <= coef_load_value;
            end

            if (sample_valid) begin
                sample_history[0] <= sample_in;
                for (int i = 1; i < NTAPS - 1; i++) begin
                    sample_history[i] <= sample_history[i-1];
                end
                result_out <= convolution_result;
            }

            result_valid <= sample_valid;
        end
    end

endmodule
