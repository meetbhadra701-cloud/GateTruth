// t2_i2c_slave: Fixed-address, write-only I2C slave (digital domain)
// REDACTED-CANARY

module i2c_slave #(
    parameter logic [6:0] SLAVE_ADDR = 7'h50
) (
    input  logic clk,
    input  logic rst,         // synchronous, active-high reset
    input  logic scl_in,
    input  logic sda_in,
    output logic sda_oe,      // 1 = driving SDA low (ACK); 0 = not driving
    output logic byte_valid,
    output logic [7:0] byte_data
);

    // Internal state representation
    localparam [2:0] S_IDLE     = 3'd0,
                     S_ADDR     = 3'd1,
                     S_ADDR_ACK = 3'd2,
                     S_DATA     = 3'd3,
                     S_DATA_ACK = 3'd4,
                     S_IGNORE   = 3'd5;

    // Registers for state, counters, and data
    logic [2:0] state_reg, state_next;
    logic [2:0] bit_count_reg, bit_count_next;
    logic [7:0] shift_reg_reg, shift_reg_next;

    // Next-state logic for registered outputs
    logic sda_oe_next;
    logic byte_valid_next;
    logic [7:0] byte_data_next;

    // Input synchronizers for edge detection
    logic scl_in_d, sda_in_d;

    // Edge and condition detectors
    logic scl_rising_edge;
    logic start_cond;
    logic stop_cond;

    // Sample previous input values
    always_ff @(posedge clk) begin
        scl_in_d <= scl_in;
        sda_in_d <= sda_in;
    end

    // Combinational generation of edge/condition signals
    assign scl_rising_edge = scl_in && !scl_in_d;
    // START: SDA falls while SCL is high
    assign start_cond = scl_in && scl_in_d && sda_in_d && !sda_in;
    // STOP: SDA rises while SCL is high
    assign stop_cond = scl_in && scl_in_d && !sda_in_d && sda_in;

    // State and data registers
    always_ff @(posedge clk or posedge rst) begin
        if (rst) begin
            state_reg     <= S_IDLE;
            bit_count_reg <= '0;
            shift_reg_reg <= '0;
            sda_oe        <= 1'b0;
            byte_valid    <= 1'b0;
            byte_data     <= '0;
        end else begin
            state_reg     <= state_next;
            bit_count_reg <= bit_count_next;
            shift_reg_reg <= shift_reg_next;
            sda_oe        <= sda_oe_next;
            byte_valid    <= byte_valid_next;
            byte_data     <= byte_data_next;
        end
    end

    // Next-state logic for FSM and outputs
    always_comb begin
        // Default assignments to maintain current state unless changed
        state_next     = state_reg;
        bit_count_next = bit_count_reg;
        shift_reg_next = shift_reg_reg;
        sda_oe_next    = sda_oe;
        byte_valid_next = 1'b0; // byte_valid is a pulse
        byte_data_next = byte_data;

        // High-priority START/STOP conditions override FSM state
        if (start_cond) begin
            state_next     = S_ADDR;
            bit_count_next = '0;
            sda_oe_next    = 1'b0;
        end else if (stop_cond) begin
            state_next     = S_IDLE;
            sda_oe_next    = 1'b0;
        end else begin
            // Main state machine logic
            case (state_reg)
                S_IDLE: begin
                    // Wait for START condition (handled above)
                    sda_oe_next = 1'b0;
                end

                S_ADDR: begin
                    if (scl_rising_edge) begin
                        shift_reg_next = {shift_reg_reg[6:0], sda_in};
                        if (bit_count_reg == 7) begin // 8th bit just received
                            state_next = S_ADDR_ACK;
                            // Check address and R/W bit, prepare to drive ACK/NACK
                            logic addr_match = ({shift_reg_reg[6:0], sda_in}[7:1] == SLAVE_ADDR);
                            logic write_op   = ({shift_reg_reg[6:0], sda_in}[0] == 1'b0);
                            if (addr_match && write_op) begin
                                sda_oe_next = 1'b1; // ACK
                            end else begin
                                sda_oe_next = 1'b0; // NACK
                            end
                        end else begin
                            bit_count_next = bit_count_reg + 1;
                        end
                    end
                end

                S_ADDR_ACK: begin
                    // Hold ACK/NACK for one SCL cycle. Transition on next SCL rising edge.
                    if (scl_rising_edge) begin
                        sda_oe_next = 1'b0; // Release SDA line
                        logic addr_match = (shift_reg_reg[7:1] == SLAVE_ADDR);
                        logic write_op   = (shift_reg_reg[0] == 1'b0);
                        if (addr_match && write_op) begin
                            state_next     = S_DATA;
                            bit_count_next = '0;
                        end else begin
                            state_next = S_IGNORE;
                        end
                    end
                end

                S_DATA: begin
                    if (scl_rising_edge) begin
                        shift_reg_next = {shift_reg_reg[6:0], sda_in};
                        if (bit_count_reg == 7) begin // 8th bit just received
                            state_next      = S_DATA_ACK;
                            sda_oe_next     = 1'b1; // ACK data byte
                            byte_valid_next = 1'b1; // Signal data is valid
                            byte_data_next  = {shift_reg_reg[6:0], sda_in};
                        end else begin
                            bit_count_next = bit_count_reg + 1;
                        end
                    end
                end

                S_DATA_ACK: begin
                    // Hold ACK for one SCL cycle. Transition on next SCL rising edge.
                    if (scl_rising_edge) begin
                        sda_oe_next    = 1'b0; // Release SDA line
                        state_next     = S_DATA; // Prepare for next data byte
                        bit_count_next = '0;
                    end
                end

                S_IGNORE: begin
                    // After a NACKed address, ignore all bus activity until START/STOP
                    sda_oe_next = 1'b0;
                end

                default: begin
                    state_next = S_IDLE;
                end
            endcase
        end
    end

endmodule
