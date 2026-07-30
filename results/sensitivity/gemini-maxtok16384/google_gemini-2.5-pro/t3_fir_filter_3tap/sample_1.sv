// Copyright 2024 Google LLC
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

module fir_filter_3tap #(
    parameter int DATA_WIDTH = 8,
    parameter int ACC_WIDTH  = 24,
    parameter logic signed [DATA_WIDTH-1:0] C0 = 8'sd2,
    parameter logic signed [DATA_WIDTH-1:0] C1 = 8'sd3,
    parameter logic signed [DATA_WIDTH-1:0] C2 = 8'sd1
) (
    input  logic                         clk,
    input  logic                         rst,   // synchronous, active-high
    input  logic                         en,
    input  logic signed [DATA_WIDTH-1:0] x_in,
    output logic signed [ACC_WIDTH-1:0]  y_out  // registered 3-tap convolution
);

    // Internal state for sample history (x[n-1] and x[n-2])
    logic signed [DATA_WIDTH-1:0] x1_reg, x2_reg;

    // Combinational logic for the next output value
    logic signed [ACC_WIDTH-1:0] y_next;

    // The convolution calculation: y[n] = C0*x[n] + C1*x[n-1] + C2*x[n-2]
    // The products are 2*DATA_WIDTH bits. The sum is performed at ACC_WIDTH
    // precision, which is guaranteed by the spec to be sufficient.
    // This uses the current input (x[n]) and the registered history (x[n-1], x[n-2]).
    assign y_next = (C0 * x_in) + (C1 * x1_reg) + (C2 * x2_reg);

    // Register file for history and output
    always_ff @(posedge clk) begin
        if (rst) begin
            // Reset all internal state and output
            x1_reg <= '0;
            x2_reg <= '0;
            y_out  <= '0;
        end else if (en) begin
            // Shift the history registers
            x1_reg <= x_in;
            x2_reg <= x1_reg;
            // Register the new convolution result
            y_out  <= y_next;
        end
        // If not reset and not enabled, all registers hold their previous values.
    end

endmodule
