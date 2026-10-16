"""Sobel Multi-Cone Optimization & Error-Area Tradeoff Sweep.

Sweeps error bounds and LSB pruning widths across the multi-cone Sobel operator
to push gate area savings and measure empirical Pareto tradeoffs.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from axsys.flow import AxcFlow

logger = logging.getLogger("sobel_sweep")

SOBEL_TEMPLATE = """`timescale 1ns / 1ps

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

    // Multi-Cone Datapath Outputs
    (* axc_relax = "1", axc_metric = "MED", axc_bound = "__GRAD_BOUND__", axc_lsb_width = __GRAD_LSB__ *)
    output reg  [10:0] gx_abs,

    (* axc_relax = "1", axc_metric = "MED", axc_bound = "__GRAD_BOUND__", axc_lsb_width = __GRAD_LSB__ *)
    output reg  [10:0] gy_abs,

    (* axc_relax = "1", axc_metric = "MED", axc_bound = "__MAG_BOUND__", axc_lsb_width = __MAG_LSB__ *)
    output reg  [7:0]  sobel_out
);

    wire signed [11:0] gx_pos = {3'b000, p02} + {2'b00, p12, 1'b0} + {3'b000, p22};
    wire signed [11:0] gx_neg = {3'b000, p00} + {2'b00, p10, 1'b0} + {3'b000, p20};
    wire signed [11:0] gx_diff = gx_pos - gx_neg;

    wire signed [11:0] gy_pos = {3'b000, p20} + {2'b00, p21, 1'b0} + {3'b000, p22};
    wire signed [11:0] gy_neg = {3'b000, p00} + {2'b00, p01, 1'b0} + {3'b000, p02};
    wire signed [11:0] gy_diff = gy_pos - gy_neg;

    wire [10:0] gx_val = (gx_diff[11]) ? (-gx_diff[10:0]) : gx_diff[10:0];
    wire [10:0] gy_val = (gy_diff[11]) ? (-gy_diff[10:0]) : gy_diff[10:0];

    wire [11:0] mag_sum = {1'b0, gx_val} + {1'b0, gy_val};
    wire [7:0]  sat_out = (mag_sum > 12'd255) ? 8'hff : mag_sum[7:0];

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
"""


def run_sweep() -> List[Dict[str, Any]]:
    work_dir = Path("build/sobel_sweep").resolve()
    work_dir.mkdir(parents=True, exist_ok=True)

    configs = [
        {"name": "baseline_exact", "grad_bound": 0.0, "grad_lsb": 0, "mag_bound": 0.0, "mag_lsb": 0},
        {"name": "conservative",   "grad_bound": 4.0, "grad_lsb": 3, "mag_bound": 8.0, "mag_lsb": 3},
        {"name": "moderate",       "grad_bound": 8.0, "grad_lsb": 4, "mag_bound": 16.0, "mag_lsb": 4},
        {"name": "aggressive",     "grad_bound": 16.0, "grad_lsb": 5, "mag_bound": 32.0, "mag_lsb": 5},
        {"name": "high_push",      "grad_bound": 32.0, "grad_lsb": 6, "mag_bound": 64.0, "mag_lsb": 6},
        {"name": "max_push",       "grad_bound": 64.0, "grad_lsb": 7, "mag_bound": 100.0, "mag_lsb": 7},
    ]

    results = []

    for cfg in configs:
        tag = cfg["name"]
        run_dir = work_dir / tag
        rtl_file = run_dir / "sobel_kernel.v"
        run_dir.mkdir(parents=True, exist_ok=True)

        # Generate annotated RTL
        code = (
            SOBEL_TEMPLATE
            .replace("__GRAD_BOUND__", str(cfg["grad_bound"]))
            .replace("__GRAD_LSB__", str(cfg["grad_lsb"]))
            .replace("__MAG_BOUND__", str(cfg["mag_bound"]))
            .replace("__MAG_LSB__", str(cfg["mag_lsb"]))
        )
        rtl_file.write_text(code, encoding="utf-8")

        print(f"\n=======================================================")
        print(f"Running Configuration: {tag} (grad_lsb={cfg['grad_lsb']}, bound={cfg['grad_bound']})")
        print(f"=======================================================")

        if cfg["grad_lsb"] == 0:
            # Baseline exact: no relaxation, just evaluate baseline area
            # We can run AxLS with 0 bound / 0 lsb or record baseline from other runs
            continue

        flow = AxcFlow(
            input_verilog=rtl_file,
            output_dir=run_dir,
            tech="NanGate15nm",
            clk_port="clk",
            clk_period_ns=5.0,
            sim_samples=300,
            verify_cycles=300,
        )

        res = flow.run()
        summary = {
            "config": tag,
            "grad_bound": cfg["grad_bound"],
            "grad_lsb": cfg["grad_lsb"],
            "mag_bound": cfg["mag_bound"],
            "mag_lsb": cfg["mag_lsb"],
            "flow_status": res.get("flow_status"),
            "initial_area": res.get("approximation", {}).get("initial_area"),
            "approx_area": res.get("approximation", {}).get("approx_area"),
            "area_savings_percent": res.get("approximation", {}).get("area_savings_percent"),
            "pruned_nodes": res.get("approximation", {}).get("pruned_nodes"),
            "verification": res.get("verification", {}).get("status"),
            "control_errors": res.get("verification", {}).get("control_errors"),
            "metric_evaluations": res.get("verification", {}).get("metric_evaluations"),
        }
        results.append(summary)

    out_file = work_dir / "sweep_summary.json"
    out_file.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nSweep completed. Summary written to {out_file}")
    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_sweep()
