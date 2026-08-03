// t3_cache_tag_comparator — Direct-mapped tag/valid compare slice
// REDACTED-CANARY

`default_nettype none

module cache_tag_comparator #(
    parameter int NSETS     = 4,
    parameter int TAG_WIDTH = 8
) (
    input  logic                       clk,
    input  logic                       rst,
    input  logic                       lookup_valid,
    input  logic                       fill_valid,
    input  logic [$clog2(NSETS)-1:0]   set_index,
    input  logic [TAG_WIDTH-1:0]       tag_in,
    output logic                       hit
);

    // Internal storage for the cache tags and their valid bits.
    // Implemented as an array of registers.
    logic [TAG_WIDTH-1:0] tag_mem [NSETS];
    logic                 valid_mem [NSETS];

    always_ff @(posedge clk) begin
        if (rst) begin
            // On synchronous reset, invalidate all cache entries.
            // The hit output is also reset to 0.
            for (int i = 0; i < NSETS; i++) begin
                valid_mem[i] <= 1'b0;
                tag_mem[i]   <= '0; // Reset tags for determinism
            end
            hit <= 1'b0;
        end else begin
            // By default, hit is 0 (for idle, fill, or miss cycles).
            // It will be overridden on a successful lookup.
            hit <= 1'b0;

            // Fill has priority over lookup.
            if (fill_valid) begin
                // A fill operation updates the tag and valid bit for the given set.
                tag_mem[set_index]   <= tag_in;
                valid_mem[set_index] <= 1'b1;
            end else if (lookup_valid) begin
                // A lookup operation compares the input tag with the stored tag.
                // A hit occurs if the set is valid and the tags match.
                // The comparison uses the state from before this clock edge.
                if (valid_mem[set_index] && (tag_mem[set_index] == tag_in)) begin
                    hit <= 1'b1;
                end
            end
            // If neither fill_valid nor lookup_valid is asserted, it's an idle cycle.
            // State remains unchanged, and hit remains 0.
        end
    end

endmodule

`default_nettype wire
