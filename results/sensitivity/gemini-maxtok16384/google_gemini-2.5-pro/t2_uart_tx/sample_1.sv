// REDACTED-CANARY
module uart_tx #(
    parameter int CLKS_PER_BIT = 16,
    parameter int DATA_BITS    = 8
) (
    input  logic                 clk,
    input  logic                 rst,    // synchronous, active-high reset
    input  logic                 start,  // accepted only when !busy
    input  logic [DATA_BITS-1:0] data,
    output logic                 tx,     // serial out, idle high
    output logic                 busy,
    output logic                 done    // one-cycle completion pulse
);

    // State machine encoding
    typedef enum logic {
        IDLE,
        TRANSMIT
    } state_t;

    state_t state_reg, state_next;

    // Counters and data holding registers
    logic [$clog2(CLKS_PER_BIT)-1:0] clk_counter_reg, clk_counter_next;
    logic [$clog2(DATA_BITS+2)-1:0] bit_counter_reg, bit_counter_next;
    logic [DATA_BITS+1:0]           shift_reg, shift_reg_next;

    // Internal signal for bit period timing
    logic bit_tick;

    // Sequential logic: registers update on clock edge
    always_ff @(posedge clk) begin
        if (rst) begin
            state_reg       <= IDLE;
            clk_counter_reg <= '0;
            bit_counter_reg <= '0;
            shift_reg       <= '1; // Drive tx high in idle
        end else begin
            state_reg       <= state_next;
            clk_counter_reg <= clk_counter_next;
            bit_counter_reg <= bit_counter_next;
            shift_reg       <= shift_reg_next;
        end
    end

    // Combinational logic: next state and output logic
    always_comb begin
        // Default assignments to avoid latches
        state_next       = state_reg;
        clk_counter_next = clk_counter_reg;
        bit_counter_next = bit_counter_reg;
        shift_reg_next   = shift_reg;
        done             = 1'b0;

        // A 'tick' every CLKS_PER_BIT cycles
        bit_tick = (clk_counter_reg == CLKS_PER_BIT - 1);

        case (state_reg)
            IDLE: begin
                // In IDLE, keep tx line high by keeping shift register full of 1s.
                shift_reg_next = '1;
                // A start request is only accepted when not busy (i.e., in IDLE state)
                if (start) begin
                    state_next = TRANSMIT;
                    // Load the frame: {stop_bit, data_lsb_first, start_bit}
                    shift_reg_next = {1'b1, data, 1'b0};
                    clk_counter_next = '0;
                    bit_counter_next = '0;
                end
            end

            TRANSMIT: begin
                if (bit_tick) begin
                    // End of a bit period, prepare for the next bit
                    clk_counter_next = '0;

                    // Total bits to send: 1 start + DATA_BITS + 1 stop
                    // Bit counter counts from 0 to (DATA_BITS+1)
                    if (bit_counter_reg == DATA_BITS + 1) begin
                        // Last bit (stop bit) has finished transmitting
                        state_next = IDLE;
                        done = 1'b1; // Pulse done for one cycle
                    end else begin
                        // Not the last bit, continue transmitting
                        bit_counter_next = bit_counter_reg + 1;
                        // Shift out the current LSB and shift in '1' (idle level) from MSB
                        shift_reg_next = {1'b1, shift_reg[DATA_BITS+1:1]};
                    end
                end else begin
                    // In the middle of a bit period, just increment the clock cycle counter
                    clk_counter_next = clk_counter_reg + 1;
                end
            end
        endcase
    end

    // Output assignments
    assign busy = (state_reg != IDLE);
    assign tx = shift_reg[0];

endmodule
