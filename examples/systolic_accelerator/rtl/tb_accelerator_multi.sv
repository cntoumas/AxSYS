`timescale 1ns/1ps

module tb_accelerator_multi #(
  parameter AW = 8,
  parameter BW = 8,
  parameter ACCW = 32,
  parameter ROWS = 4,
  parameter COLS = 4,
  parameter K = 4,
  parameter APPROX_LSB = 0,
  parameter NUM_TESTS = 100
) ();

  reg clk;
  reg rst_n;
  reg start;
  wire done;

  reg signed [AW-1:0] A_tile [0:ROWS-1][0:K-1];
  reg signed [BW-1:0] B_tile [0:K-1][0:COLS-1];

  wire [ROWS*COLS*ACCW-1:0] C_out_flat;
  reg signed [ACCW-1:0] C_out [0:ROWS-1][0:COLS-1];

  reg [ROWS*K*AW-1:0] A_flat;
  reg [K*COLS*BW-1:0] B_flat;

  always @* begin
    for(int i=0; i<ROWS; i++) begin
      for(int j=0; j<K; j++) begin
        A_flat[(i*K+j)*AW +: AW] = A_tile[i][j];
      end
    end
    for(int i=0; i<K; i++) begin
      for(int j=0; j<COLS; j++) begin
        B_flat[(i*COLS+j)*BW +: BW] = B_tile[i][j];
      end
    end
  end

  always @* begin
    for(int r=0; r<ROWS; r++) begin
      for(int c=0; c<COLS; c++) begin
        C_out[r][c] = C_out_flat[(r*COLS + c)*ACCW +: ACCW];
      end
    end
  end

  Systolic4x4 #(
    .AW(AW), .BW(BW), .ACCW(ACCW),
    .ROWS(ROWS), .COLS(COLS), .K(K),
    .APPROX_LSB(APPROX_LSB)
  ) dut (
    .clk(clk),
    .rst_n(rst_n),
    .start(start),
    .A_in_flat(A_flat),
    .B_in_flat(B_flat),
    .done(done),
    .C_out(C_out_flat)
  );

  initial clk = 0;
  always #5 clk = ~clk;

  function signed [ACCW-1:0] golden_mul_elem;
    input integer r_in;
    input integer c_in;
    integer k_idx;
    reg signed [ACCW-1:0] s_sum;
    begin
      s_sum = 0;
      for (k_idx=0; k_idx<K; k_idx=k_idx+1)
        s_sum = s_sum + ($signed(A_tile[r_in][k_idx]) * $signed(B_tile[k_idx][c_in]));
      golden_mul_elem = s_sum;
    end
  endfunction

  integer t, r, c, cyc;
  integer control_errors;
  real total_abs_err;
  real total_sq_err;
  real total_golden_sq;
  real max_err;
  real total_elements;
  real g_val, hw_val, diff;
  real med, nmed, frobenius_pct;

  initial begin
    rst_n = 0;
    start = 0;
    control_errors = 0;
    total_abs_err = 0.0;
    total_sq_err = 0.0;
    total_golden_sq = 0.0;
    max_err = 0.0;
    total_elements = NUM_TESTS * ROWS * COLS;

    #20;
    rst_n = 1;
    #20;

    for (t = 0; t < NUM_TESTS; t = t + 1) begin
      // Generate randomized matrix inputs (INT8 range [-64, 63])
      for (int i=0; i<ROWS; i++) begin
        for (int j=0; j<K; j++) begin
          A_tile[i][j] = ($random % 128) - 64;
        end
      end
      for (int i=0; i<K; i++) begin
        for (int j=0; j<COLS; j++) begin
          B_tile[i][j] = ($random % 128) - 64;
        end
      end

      @(posedge clk);
      start = 1;
      @(posedge clk);
      start = 0;

      cyc = 0;
      while (!done && cyc <= 500) begin
        @(posedge clk);
        cyc = cyc + 1;
      end
      if (cyc > 500) begin
        $display("ERROR: Hang detected on test %0d", t);
        control_errors = control_errors + 1;
      end

      // Check expected cycle count for 2D systolic pipeline
      // Expected = K + ROWS + COLS - 1 + 2 (overhead for load/finish)
      if (cyc < (K + ROWS + COLS - 3)) begin
        control_errors = control_errors + 1;
      end

      // Sample results
      for (r = 0; r < ROWS; r = r + 1) begin
        for (c = 0; c < COLS; c = c + 1) begin
          g_val = real'(golden_mul_elem(r, c));
          hw_val = real'($signed(C_out[r][c]));
          diff = hw_val - g_val;
          if (diff < 0) diff = -diff;

          total_abs_err = total_abs_err + diff;
          total_sq_err = total_sq_err + (diff * diff);
          total_golden_sq = total_golden_sq + (g_val * g_val);
          if (diff > max_err) max_err = diff;
        end
      end

      @(posedge clk);
    end

    med = total_abs_err / total_elements;
    // NMED normalized by max potential range (K * 128 * 128)
    nmed = med / (real'(K) * 16384.0);
    if (total_golden_sq > 0.0) begin
      frobenius_pct = ($sqrt(total_sq_err) / $sqrt(total_golden_sq)) * 100.0;
    end else begin
      frobenius_pct = 0.0;
    end

    $display("ACCEL_METRICS: {\"num_tests\": %0d, \"total_elements\": %0d, \"med\": %0f, \"nmed\": %0e, \"frobenius_err_pct\": %0f, \"max_err\": %0f, \"control_errors\": %0d}",
      NUM_TESTS, int'(total_elements), med, nmed, frobenius_pct, max_err, control_errors);

    $finish;
  end

endmodule
