// t3_lru_tracker: N-way age-based LRU replacement tracker
//
// Implements the standard counter/age-based LRU algorithm. Each of the NWAYS
// ways has an associated age, where the ages are always a permutation of
// 0..NWAYS-1. Age 0 is the most-recently-used (MRU) and age NWAYS-1 is the
// least-recently-used (LRU).

module lru_tracker #(
    parameter int NWAYS = 4
) (
    input  logic                       clk,
    input  logic                       rst,           // synchronous, active-high reset
    input  logic                       access_valid,
    input  logic [$clog2(NWAYS)-1:0]   access_way,
    output logic [$clog2(NWAYS)-1:0]   lru_way
);

    // Width of way indices and age values.
    // Ages are a permutation of 0..NWAYS-1, so they need the same width as way indices.
    localparam int WAY_W = $clog2(NWAYS);

    // Array of registers to hold the age of each way.
    logic [WAY_W-1:0] age [NWAYS-1:0];

    // Combinational logic for the next state of the age registers.
    logic [WAY_W-1:0] next_age [NWAYS-1:0];

    // Sequential logic: update age registers on clock edge.
    always_ff @(posedge clk) begin
        if (rst) begin
            // On synchronous reset, initialize ages to a known permutation:
            // age[i] = i. Way 0 is MRU, Way NWAYS-1 is LRU.
            for (int i = 0; i < NWAYS; i++) begin
                age[i] <= i;
            end
        end else if (access_valid) begin
            // On a valid access, update all ages based on the combinational
            // next_age logic.
            age <= next_age;
        end
    end

    // Combinational logic: calculate the next age for each way based on the
    // current ages and the accessed way.
    always_comb begin
        // The age of the currently accessed way before the update.
        logic [WAY_W-1:0] old_age_of_accessed_way;
        old_age_of_accessed_way = age[access_way];

        for (int i = 0; i < NWAYS; i++) begin
            if (i == access_way) begin
                // The accessed way becomes the new MRU (age 0).
                next_age[i] = '0;
            end else begin
                // For all other ways, if they were more recent than the
                // accessed way, they become one step less recent (age increases).
                // Ways that were already less recent are not affected.
                if (age[i] < old_age_of_accessed_way) begin
                    next_age[i] = age[i] + 1;
                end else {
                    next_age[i] = age[i];
                }
            end
        end
    end

    // Combinational logic: determine the current LRU way.
    // The LRU way is the one with the maximum age (NWAYS-1).
    // Since the ages are always a permutation, exactly one way will have this age.
    always_comb begin
        lru_way = '0; // Default assignment (will be overwritten by the loop)
        for (int i = 0; i < NWAYS; i++) begin
            if (age[i] == NWAYS - 1) begin
                lru_way = i;
            end
        end
    end

endmodule
