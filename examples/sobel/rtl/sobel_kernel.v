`timescale 1ns / 1ps

module sobel_kernel (
    input  wire        clk,
    input  wire        rst_n,

    // Precise control paths — protected from pruning
    (* axc_precise = "1" *) input  wire valid_in,
    (* axc_precise = "1" *) output reg  valid_out,

    // 3x3 Pixel Window Inputs (8-bit grayscale pixels)
    input  wire [7:0]  p00, p01, p02,
    input  wire [7:0]  p10, p11, p12,
    input  wire [7:0]  p20, p21, p22,

    // Relaxed Datapath Outputs: Multi-cone approximation targets
    // Cone 1: Absolute Horizontal Gradient
    (* axc_relax = "1", axc_metric = "MED", axc_bound = "8.0", axc_lsb_width = 4 *)
    output reg  [10:0] gx_abs,

    // Cone 2: Absolute Vertical Gradient
    (* axc_relax = "1", axc_metric = "MED", axc_bound = "8.0", axc_lsb_width = 4 *)
    output reg  [10:0] gy_abs,

    // Cone 3: Combined Saturated Edge Magnitude
    (* axc_relax = "1", axc_metric = "MED", axc_bound = "16.0", axc_lsb_width = 4 *)
    output reg  [7:0]  sobel_out
);

    // Intermediate horizontal & vertical gradient computations
    // Gx = (p02 + 2*p12 + p22) - (p00 + 2*p10 + p20)
    wire signed [11:0] gx_pos = {3'b000, p02} + {2'b00, p12, 1'b0} + {3'b000, p22};
    wire signed [11:0] gx_neg = {3'b000, p00} + {2'b00, p10, 1'b0} + {3'b000, p20};
    wire signed [11:0] gx_diff = gx_pos - gx_neg;

    // Gy = (p20 + 2*p21 + p22) - (p00 + 2*p01 + p02)
    wire signed [11:0] gy_pos = {3'b000, p20} + {2'b00, p21, 1'b0} + {3'b000, p22};
    wire signed [11:0] gy_neg = {3'b000, p00} + {2'b00, p01, 1'b0} + {3'b000, p02};
    wire signed [11:0] gy_diff = gy_pos - gy_neg;

    // Absolute values
    wire [10:0] gx_val = (gx_diff[11]) ? (-gx_diff[10:0]) : gx_diff[10:0];
    wire [10:0] gy_val = (gy_diff[11]) ? (-gy_diff[10:0]) : gy_diff[10:0];

    // Combined magnitude and saturation
    wire [11:0] mag_sum = {1'b0, gx_val} + {1'b0, gy_val};
    wire [7:0]  sat_out = (mag_sum > 12'd255) ? 8'hff : mag_sum[7:0];

    // Pipeline / Output registers
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            valid_out <= 1'b0;
            gx_abs    <= 11'd0;
            gy_abs    <= 11'd0;
            sobel_out <= 8'd0;
        end else begin
            valid_out <= valid_in;
            gx_abs    <= gx_val;
            gy_abs    <= gy_val;
            sobel_out <= sat_out;
        end
    end

endmodule
