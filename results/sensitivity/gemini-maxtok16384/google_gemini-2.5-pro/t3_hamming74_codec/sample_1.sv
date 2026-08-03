// SPDX-License-Identifier: Apache-2.0
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
// http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

`default_nettype none

module hamming74_codec (
    input  logic       clk,
    input  logic       rst,
    input  logic [3:0] encode_data,
    output logic [6:0] codeword_out,
    input  logic [6:0] decode_codeword,
    output logic [3:0] decode_data,
    output logic       error_detected
);

    // --- Combinational Logic ---

    // --- ENCODE PATH ---
    // Intermediate signals for the encode path
    logic [6:0] codeword_out_next;
    logic p1, p2, p3;

    // Parity bit calculations based on input data (d1, d2, d3, d4)
    // d1=encode_data[0], d2=encode_data[1], d3=encode_data[2], d4=encode_data[3]
    // p1 = d1 ^ d2 ^ d4
    assign p1 = encode_data[0] ^ encode_data[1] ^ encode_data[3];
    // p2 = d1 ^ d3 ^ d4
    assign p2 = encode_data[0] ^ encode_data[2] ^ encode_data[3];
    // p3 = d2 ^ d3 ^ d4
    assign p3 = encode_data[1] ^ encode_data[2] ^ encode_data[3];

    // Assemble the next codeword according to the spec's bit positions
    // Codeword bit position (1-indexed): 7  6  5  4  3  2  1
    // Content:                          d4 d3 d2 p3 d1 p2 p1
    // codeword_out index (0-indexed):  [6][5][4][3][2][1][0]
    assign codeword_out_next = {
        encode_data[3], // d4
        encode_data[2], // d3
        encode_data[1], // d2
        p3,
        encode_data[0], // d1
        p2,
        p1
    };


    // --- DECODE PATH ---
    // Intermediate signals for the decode path
    logic [3:0] decode_data_next;
    logic       error_detected_next;

    logic s1, s2, s3;
    logic [2:0] syndrome;
    logic [6:0] corrected_codeword;
    logic [6:0] error_mask;

    // Syndrome bit calculations from the received codeword
    // s1 checks parity over positions 1, 3, 5, 7 (indices 0, 2, 4, 6)
    assign s1 = decode_codeword[0] ^ decode_codeword[2] ^ decode_codeword[4] ^ decode_codeword[6];
    // s2 checks parity over positions 2, 3, 6, 7 (indices 1, 2, 5, 6)
    assign s2 = decode_codeword[1] ^ decode_codeword[2] ^ decode_codeword[5] ^ decode_codeword[6];
    // s3 checks parity over positions 4, 5, 6, 7 (indices 3, 4, 5, 6)
    assign s3 = decode_codeword[3] ^ decode_codeword[4] ^ decode_codeword[5] ^ decode_codeword[6];

    // The syndrome {s3, s2, s1} is the 1-indexed position of the error
    assign syndrome = {s3, s2, s1};

    // Generate a one-hot mask from the syndrome to flip the error bit.
    // A syndrome of 0 means no error, so the mask is 0.
    // A non-zero syndrome indicates the 1-indexed position to flip.
    // e.g., syndrome=1 -> mask=...001; syndrome=7 -> mask=100...
    assign error_mask = (1 << syndrome) >> 1;

    // Correct the codeword by XORing with the error mask
    assign corrected_codeword = decode_codeword ^ error_mask;

    // Extract the data bits from the corrected codeword.
    // The output data bit order must match the input data bit order.
    // encode_data[0]=d1, [1]=d2, [2]=d3, [3]=d4
    // Corrected codeword positions: d1=[2], d2=[4], d3=[5], d4=[6]
    assign decode_data_next = {
        corrected_codeword[6], // d4 -> decode_data[3]
        corrected_codeword[5], // d3 -> decode_data[2]
        corrected_codeword[4], // d2 -> decode_data[1]
        corrected_codeword[2]  // d1 -> decode_data[0]
    };

    // Set error_detected if the syndrome is non-zero (i.e., an error was found)
    assign error_detected_next = |syndrome;


    // --- Sequential Logic (Registers) ---
    // All outputs are registered and reset synchronously.
    always_ff @(posedge clk) begin
        if (rst) begin
            codeword_out   <= '0;
            decode_data    <= '0;
            error_detected <= 1'b0;
        end else begin
            codeword_out   <= codeword_out_next;
            decode_data    <= decode_data_next;
            error_detected <= error_detected_next;
        end
    end

endmodule

`default_nettype wire
