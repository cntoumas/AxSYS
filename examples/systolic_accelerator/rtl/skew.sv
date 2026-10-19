`timescale 1ns/1ps

/***************************************
 * Start : wait for one clk, copy 
 * register in this clk. Next clk: Start
 * skew
 ***************************************/

module skew #(
    parameter int ROWS = 8,
    parameter int COLS = 8,
    parameter int K    = 8,
    parameter int DW   = 16
) (
    input logic clk,
    input logic rst_n,
    input logic start,

    input var logic signed [DW-1:0] A_MAT [ROWS][K],
    input var logic signed [DW-1:0] B_MAT [K][COLS],
	
    output logic signed [DW-1:0] SKEWED_A[ROWS],
    output logic signed [DW-1:0] SKEWED_B[COLS],
    output logic 			  	 valid_a[ROWS],
    output logic 			  	 valid_b[COLS],
    output logic 			  	 done
);

localparam int CYC_A   = ROWS + K - 1;
localparam int CYC_B   = K + COLS - 1;
localparam int CYC_TOT = (CYC_A > CYC_B) ? CYC_A : CYC_B;

// Internal reg copy
logic signed [DW-1:0] A [ROWS][K];
logic signed [DW-1:0] B [K][COLS];

// Counters
logic [DW-1:0] cycles;
logic 		   skewing;


/* Timing note: `skewing` is set to 1 at the edge where `start` pulses.
 * SKEW_LOGIC reads `skewing` in a separate always_ff block, so during
 * the start cycle itself, SKEW_LOGIC sees the old value (0) and does
 * not emit. First emission happens one cycle after start, with cycles=0.
 * This is correct behavior and relies on non-blocking assignment semantics.
 */
always_ff @(posedge clk or negedge rst_n) begin : CTRL_LOGIC
	if (~rst_n) begin
		cycles <= 'd0;
		skewing <= 1'b0;
	end else begin
		if (start) begin
			skewing <= 1'b1;
			cycles <= 'd0;
		end else if (skewing) begin
			cycles <= cycles + 1;
			if (int'(cycles) == CYC_TOT - 1) skewing <= 1'b0;
		end
	end
end

// Copy matrices at start
always_ff @(posedge clk) begin : REG_COPY
	if (start) begin
		A <= A_MAT;
		B <= B_MAT;
	end
end

// Sequential Logic
always_ff @(posedge clk or negedge rst_n) begin : SKEW_LOGIC
	if (~rst_n) begin
		for (int i = 0; i < ROWS; i++) begin
			SKEWED_A[i] <= '0;
			valid_a[i]  <= 1'b0;
		end
		for (int j = 0; j < COLS; j++) begin
			SKEWED_B[j] <= '0;
			valid_b[j]  <= 1'b0;
		end
	end else begin
		if (start) begin
			// Init to default values
			for (int i = 0; i < ROWS; i++) begin
				SKEWED_A[i] <= '0;
				valid_a[i]  <= 1'b0;
			end

			// Init to default values
			for (int j = 0; j < COLS; j++) begin
				SKEWED_B[j] <= '0;
				valid_b[j]  <= 1'b0;
			end
		end

		if (skewing) begin
			for (int r = 0; r < ROWS; r++) begin
				if (int'(cycles) >= r && int'(cycles) < r+K) begin
					SKEWED_A[r] <= A[r][int'(cycles) - r];
					valid_a[r]  <= 1'b1;
				end else begin
					SKEWED_A[r] <= '0;
					valid_a[r]  <= 1'b0;
				end
			end
			for (int c = 0; c < COLS; c++) begin
				if (int'(cycles) >= c && int'(cycles) < c+K) begin
					SKEWED_B[c] <= B[int'(cycles) - c][c];
					valid_b[c]  <= 1'b1;
				end else begin
					SKEWED_B[c] <= '0;
					valid_b[c]  <= 1'b0;
				end
			end
		end

	end
end

/* Mainly used for debugging or to fix vulnerabilities
 * that may occur later.
 */
always_ff @(posedge clk or negedge rst_n) begin : DONE_FLAG
	if (~rst_n) begin
		done <= 1'b0;
	end else begin
		if (int'(cycles) == CYC_TOT - 1)
			done <= 1'b1;
		else
			done <= 1'b0;
	end
end

endmodule
