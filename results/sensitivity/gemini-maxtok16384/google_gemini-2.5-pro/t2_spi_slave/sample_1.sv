module spi_slave (
    input  logic       clk,
    input  logic       rst,        // synchronous, active-high reset
    input  logic       sclk_in,
    input  logic       cs_n_in,
    input  logic       mosi_in,
    input  logic [7:0] tx_data,
    output logic       miso_out,
    output logic [7:0] rx_data,
    output logic       rx_valid
);

    // Internal state registers
    logic [7:0] tx_sr;      // Transmit shift register
    logic [7:0] rx_sr;      // Receive shift register
    logic [2:0] bit_count;  // Counts received/transmitted bits
    logic       rx_valid_next;

    // Edge detection logic requires previous state of inputs
    logic cs_n_prev, sclk_prev;

    always_ff @(posedge clk) begin
        if (rst) begin
            cs_n_prev <= 1'b1;
            sclk_prev <= 1'b0;
        end else begin
            cs_n_prev <= cs_n_in;
            sclk_prev <= sclk_in;
        end
    end

    // Combinational edge detectors
    logic cs_n_falling = cs_n_prev && !cs_n_in;
    logic sclk_rising  = sclk_in && !sclk_prev;
    logic sclk_falling = !sclk_in && sclk_prev;

    // Main state machine and data path logic
    always_ff @(posedge clk) begin
        if (rst) begin
            tx_sr     <= 8'h00;
            rx_sr     <= 8'h00;
            bit_count <= 3'd0;
            rx_data   <= 8'h00;
            rx_valid  <= 1'b0;
        end else begin
            // rx_valid is a registered one-cycle pulse. It gets the value
            // calculated in the previous cycle's combinational logic.
            rx_valid <= rx_valid_next;
            
            // By default, the next value of rx_valid is 0 unless a byte completes.
            rx_valid_next = 1'b0;

            if (cs_n_falling) begin
                // A new transfer starts. Load the transmit data and reset bit counter.
                tx_sr     <= tx_data;
                rx_sr     <= 8'h00; // Clear receive buffer for new data.
                bit_count <= 3'd0;
            end else if (!cs_n_in) begin // Transfer is in progress (chip is selected).
                
                // On SCLK rising edge, sample MOSI (CPHA=0).
                if (sclk_rising) begin
                    // Shift in the new bit from MOSI.
                    rx_sr <= {rx_sr[6:0], mosi_in};
                    
                    if (bit_count == 3'd7) begin
                        // 8th bit is being sampled, the byte is now complete.
                        // Latch the complete byte into rx_data.
                        rx_data       <= {rx_sr[6:0], mosi_in};
                        // Signal that received data is valid for one cycle.
                        rx_valid_next <= 1'b1;
                        // Reset bit counter for the next byte in a multi-byte transfer.
                        bit_count     <= 3'd0;
                    end else begin
                        bit_count <= bit_count + 1;
                    end
                end
                
                // On SCLK falling edge, change MISO (CPHA=0).
                if (sclk_falling) begin
                    // Shift the transmit register. Per spec, shift in '0' so that
                    // for transfers > 8 bits, MISO will output '0'.
                    tx_sr <= {tx_sr[6:0], 1'b0};
                end
            end
            // On cs_n_rising (transfer ends), no explicit action is needed.
            // A partial byte is discarded because rx_valid is not asserted.
            // The state (bit_count, etc.) is reset by the next cs_n_falling.
        end
    end

    // MISO output logic.
    // For SPI Mode 0, MISO must be valid before the first SCLK rising edge.
    // This means it must change combinationally when CS_n asserts (falls).
    // If CS_n is asserted:
    //  - On the first cycle (cs_n_prev is high), output tx_data[7] directly.
    //  - On subsequent cycles, output the MSB of the shifting tx_sr.
    // If CS_n is deasserted, output 0.
    assign miso_out = !cs_n_in ? (cs_n_prev ? tx_data[7] : tx_sr[7]) : 1'b0;

endmodule
