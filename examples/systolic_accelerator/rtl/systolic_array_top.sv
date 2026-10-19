`timescale 1ns/1ps

module systolic_array_top #(
    parameter int ROWS = 8,
    parameter int COLS = 8,
    parameter int K    = 8,
    parameter int DW   = 8
) (
    input logic clk,
    input logic rst_n,
    input logic start,

    input logic          in_valid,
    input logic [DW-1:0] in_data,
    input logic          out_ready,

    output logic         in_ready,
    output logic         out_valid,
    output logic [ACC_DW-1:0] out_data,
    output logic         done
    
);

    localparam int ROW_W = $clog2(ROWS);
    localparam int COL_W = $clog2(COLS);
    localparam int K_W   = $clog2(K);

    localparam int ACC_DW = 2*DW + $clog2(K);

    // Counters
    logic [ROW_W:0] a_rows;
    logic [K_W:0]   a_cols;
    logic [K_W:0]   b_rows;
    logic [COL_W:0] b_cols;
    logic [ROW_W:0] c_rows;
    logic [COL_W:0] c_cols;

    // Memory
    logic signed [DW-1:0]     A [ROWS][K];
    logic signed [DW-1:0]     B [K][COLS];
    logic signed [ACC_DW-1:0] C [ROWS][COLS];

    // FSM state
    typedef enum logic [2:0] { 
        IDLE,
        LOAD_A,
        LOAD_B,
        DELAY,
        COMPUTE,
        OUTPUT
    } state_e ;

    state_e state, next_state;

    logic sa_done;

    systolic_array #(
        .ROWS (ROWS),
        .COLS (COLS),
        .K    (K)
    ) u_systolic_array (
        .clk   (clk),
        .rst_n (rst_n),
        .start (state == DELAY),
        .clear (state == DELAY),

        .A     (A),
        .B     (B),

        .C     (C),
        .done  (sa_done)
    );

    // Next State logic
    always_comb begin
        next_state = state;

        case(state)
            IDLE: begin
              if (start)
                next_state = LOAD_A;
            end
            LOAD_A: begin
                if (int'(a_rows) == ROWS-1 && int'(a_cols) == K-1 && in_valid && in_ready) begin
                    next_state = LOAD_B;
                end
            end
            LOAD_B: begin
                if (int'(b_rows) == K-1 && int'(b_cols) == COLS-1 && in_valid && in_ready) begin
                    next_state = DELAY;
                end
            end
            DELAY: begin
                next_state = COMPUTE;
            end
            COMPUTE: begin
              if (sa_done)
                next_state = OUTPUT;
            end
            OUTPUT: begin
                if (int'(c_cols) == COLS-1 && int'(c_rows) == ROWS-1 && out_valid && out_ready)
                    next_state = IDLE;
            end
            default: begin
                next_state = state;
            end
        endcase
    end

    // Handshake Signals - AXI-S
    assign in_ready  = (state == LOAD_A) || (state == LOAD_B);
    assign out_valid = (state == OUTPUT);
    assign out_data  = C[int'(c_rows)][int'(c_cols)];
    assign done      = (state == OUTPUT && next_state == IDLE);

    // Sequential Logic - Load A & B
    always_ff @(posedge clk) begin
        if (state == LOAD_A && in_valid && in_ready)
            A[int'(a_rows)][int'(a_cols)] <= signed'(in_data);
        if (state == LOAD_B && in_valid && in_ready)
            B[int'(b_rows)][int'(b_cols)] <= signed'(in_data);

    end
 
    // Sequential Logic - Update Counters
    always_ff @(posedge clk or negedge rst_n) begin
        if (~rst_n) begin
            a_cols <= '0;
            b_cols <= '0;
            c_cols <= '0;

            a_rows <= '0;
            b_rows <= '0;
            c_rows <= '0;
            
            state <= IDLE;
        end else begin
            state <= next_state;

            case (state)
                IDLE: begin
                    a_cols <= '0;
                    b_cols <= '0;
                    c_cols <= '0;

                    a_rows <= '0;
                    b_rows <= '0;
                    c_rows <= '0;
                end
                LOAD_A: begin
                    if (in_valid && in_ready) begin
                        if (int'(a_cols) == K - 1) begin
                            a_cols <= '0;
                            a_rows <= a_rows + 1;
                        end else begin
                            a_cols <=  a_cols + 1;
                        end
                    end
                end
                LOAD_B: begin
                    if (in_valid && in_ready) begin
                        if (int'(b_cols) == COLS - 1) begin
                            b_cols <= '0;
                            b_rows <= b_rows + 1;
                        end else begin
                            b_cols <=  b_cols + 1;
                        end
                    end
                end
                DELAY: begin
                end
                COMPUTE: begin
                end
                OUTPUT: begin
                    if (out_valid && out_ready) begin
                        if (int'(c_cols) == COLS - 1) begin
                            c_cols <= '0;
                            c_rows <= c_rows + 1;
                        end else begin
                            c_cols <= c_cols + 1;
                        end
                    end
                end
                default: begin
                end
            endcase
        end
    end

endmodule
