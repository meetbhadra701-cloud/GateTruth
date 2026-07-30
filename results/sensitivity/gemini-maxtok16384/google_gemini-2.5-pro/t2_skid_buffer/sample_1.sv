// t2_skid_buffer — 2-entry pipeline skid buffer (ready/valid handshake)
//
// This module implements a fixed-depth-2 elastic buffer for decoupling
// a producer and a consumer using a standard ready/valid handshake protocol.

module skid_buffer #(
    parameter int WIDTH = 8
) (
    input  logic             clk,
    input  logic             rst,        // synchronous, active-high reset
    input  logic             in_valid,
    output logic             in_ready,
    input  logic [WIDTH-1:0] in_data,
    output logic             out_valid,
    input  logic             out_ready,
    output logic [WIDTH-1:0] out_data
);

    // Internal storage for the two buffer entries.
    // 'head' is the output stage, 'tail' is the stage before it.
    logic             head_valid;
    logic [WIDTH-1:0] head_data;
    logic             tail_valid;
    logic [WIDTH-1:0] tail_data;

    // Handshake signals and transfer conditions.
    wire in_transfer  = in_valid && in_ready;
    wire out_transfer = out_valid && out_ready;

    // The buffer can accept a new item if the second stage ('tail') is not full.
    assign in_ready = !tail_valid;

    // The output is valid if the first stage ('head') holds a valid item.
    assign out_valid = head_valid;
    assign out_data  = head_data;

    // State machine logic for updating the buffer contents and valid bits.
    always_ff @(posedge clk) begin
        if (rst) begin
            // On reset, the buffer becomes empty.
            head_valid <= 1'b0;
            tail_valid <= 1'b0;
            head_data  <= '0;
            tail_data  <= '0;
        end else begin
            // The logic is structured as a case statement on the buffer occupancy.
            // The state {head_valid, tail_valid} = {0, 1} is unreachable.

            // Occupancy 0: !head_valid
            if (!head_valid) begin
                if (in_transfer) begin
                    // Accept new data into the head stage.
                    head_valid <= 1'b1;
                    head_data  <= in_data;
                end
            // Occupancy 1: head_valid && !tail_valid
            end else if (!tail_valid) begin
                if (in_transfer && !out_transfer) begin
                    // Push: Input arrives, output is stalled. Store new data in tail.
                    tail_valid <= 1'b1;
                    tail_data  <= in_data;
                end else if (!in_transfer && out_transfer) begin
                    // Pop: Output is consumed, no new input. Buffer becomes empty.
                    head_valid <= 1'b0;
                end else if (in_transfer && out_transfer) begin
                    // Bypass: Output is consumed, new input arrives. New data goes to head.
                    head_data <= in_data;
                end
                // Case: !in_transfer && !out_transfer (stall) -> no change.
            // Occupancy 2: head_valid && tail_valid
            end else begin // `head_valid && tail_valid`
                // `in_ready` is low, so `in_transfer` is false.
                if (out_transfer) begin
                    // Shift: Output is consumed. Data from tail moves to head.
                    head_data  <= tail_data;
                    tail_valid <= 1'b0;
                end
                // Case: !out_transfer (stall) -> no change.
            end
        end
    end

endmodule
