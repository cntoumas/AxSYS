"""Systolic PE Error-Area Tradeoff Sweep & Validation.

Sweeps error bounds and LSB widths across the open-source INT8 systolic MAC Processing Element
(source: ratshgupta-guptar76/int8-systolic-mac-array) to measure empirical area savings,
gate pruning, and verify zero control corruption.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from axsys.flow import AxcFlow

logger = logging.getLogger("pe_sweep")

PE_TEMPLATE = """`timescale 1ns/1ps

module pe #(
    parameter int DW = 8,
    parameter int K = 8
) (
    input logic clk,
    input logic rst_n,
    (* axc_precise = "1" *) input logic clear,

    input logic signed [DW-1:0] a_in,
    input logic signed [DW-1:0] b_in,
    (* axc_precise = "1" *) input logic valid_in,

    (* axc_precise = "1" *) output logic signed [DW-1:0] a_out,
    (* axc_precise = "1" *) output logic signed [DW-1:0] b_out,
    (* axc_precise = "1" *) output logic signed valid_out,
    (* axc_relax = "1", axc_metric = "MED", axc_bound = "__BOUND__", axc_lsb_width = __LSB__ *)
    output logic signed [2*DW + 3 - 1:0] acc
);

    localparam int ACC_DW = 2*DW + 3;

    logic signed [ACC_DW-1:0] prod;
    
    assign prod = (a_in * b_in);
    
    always_ff @(posedge clk or negedge rst_n) begin
        if (~rst_n) begin
            a_out <= '0;
            b_out <= '0;
            acc   <= '0;
        end else begin
            if (valid_in) begin
                a_out <= a_in;
                b_out <= b_in;
                acc <= prod + acc;
            end else begin
                a_out <= a_out;
                b_out <= b_out;
                acc <= acc;
            end
            if (clear) begin
                acc <= '0;
            end
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (~rst_n) begin
            valid_out <= '0;
        end else begin
            valid_out <= valid_in;
        end
    end

endmodule
"""

SWEEP_CONFIGS = [
    {
        "id": "cfg0_light",
        "description": "Light Approximation (Bound=8.0, LSB=2)",
        "bound": "8.0",
        "lsb": 2,
    },
    {
        "id": "cfg1_conservative",
        "description": "Conservative Approximation (Bound=16.0, LSB=4)",
        "bound": "16.0",
        "lsb": 4,
    },
    {
        "id": "cfg2_moderate",
        "description": "Moderate Approximation (Bound=32.0, LSB=6)",
        "bound": "32.0",
        "lsb": 6,
    },
    {
        "id": "cfg3_aggressive",
        "description": "Aggressive Approximation (Bound=64.0, LSB=8)",
        "bound": "64.0",
        "lsb": 8,
    },
    {
        "id": "cfg4_over_pushed",
        "description": "Over-Pushed Bound Test (Bound=4.0, LSB=8)",
        "bound": "4.0",
        "lsb": 8,
    },
]


def run_sweep(build_root: Path) -> List[Dict[str, Any]]:
    import subprocess
    from axsys.power_estimator import PowerEstimator

    build_root.mkdir(parents=True, exist_ok=True)
    rtl_dir = build_root / "generated_rtl"
    rtl_dir.mkdir(parents=True, exist_ok=True)

    # Evaluate exact baseline power
    estimator = PowerEstimator(tech="NanGate15nm", clk_mhz=100.0)
    baseline_vlog = build_root / "exact_baseline_mapped.v"
    if not baseline_vlog.exists():
        synth_cmd = f"yosys -p 'read_verilog -sv examples/systolic_pe/rtl/pe.sv; synth -top pe; dfflibmap -liberty third_party/AxLS/templates/NanGate15nm.lib; abc -liberty third_party/AxLS/templates/NanGate15nm.lib; write_verilog {baseline_vlog}'"
        subprocess.run(synth_cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base_pwr = estimator.evaluate_netlist(baseline_vlog) if baseline_vlog.exists() else None
    if base_pwr:
        print(f"Exact Baseline: {base_pwr['cell_count']} cells | Power: {base_pwr['total_power_uw']:.3f} uW (Dyn: {base_pwr['dynamic_power_uw']:.3f} uW, Leak: {base_pwr['leakage_power_uw']:.3f} uW)")

    results = []

    for cfg in SWEEP_CONFIGS:
        cfg_id = cfg["id"]
        cfg_out_dir = build_root / cfg_id
        cfg_out_dir.mkdir(parents=True, exist_ok=True)

        vlog_content = (
            PE_TEMPLATE
            .replace("__BOUND__", str(cfg["bound"]))
            .replace("__LSB__", str(cfg["lsb"]))
        )
        vlog_path = rtl_dir / f"pe_{cfg_id}.sv"
        vlog_path.write_text(vlog_content, encoding="utf-8")

        print(f"\n=======================================================")
        print(f"Running Configuration: {cfg_id} ({cfg['description']})")
        print(f"=======================================================")

        flow = AxcFlow(
            input_verilog=vlog_path,
            output_dir=cfg_out_dir,
            tech="NanGate15nm",
            clk_port="clk",
            clk_period_ns=10.0,
            sim_samples=100,
            verify_cycles=200,
        )

        flow_res = flow.run()

        approx_info = flow_res.get("approximation", {})
        verif_info = flow_res.get("verification", {})
        power_info = flow_res.get("power", {})

        total_pwr = power_info.get("total_power_uw", 0.0)
        pwr_savings = 0.0
        if base_pwr and total_pwr and base_pwr["total_power_uw"] > 0:
            pwr_savings = (base_pwr["total_power_uw"] - total_pwr) / base_pwr["total_power_uw"] * 100.0

        record = {
            "config_id": cfg_id,
            "description": cfg["description"],
            "bound": float(cfg["bound"]),
            "lsb_width": cfg["lsb"],
            "flow_status": flow_res.get("flow_status"),
            "initial_area": approx_info.get("initial_area"),
            "final_area": approx_info.get("approx_area"),
            "area_savings_percent": approx_info.get("area_savings_percent", 0.0),
            "pruned_nodes_count": approx_info.get("pruned_nodes", 0),
            "total_power_uw": total_pwr,
            "leakage_power_uw": power_info.get("leakage_power_uw"),
            "dynamic_power_uw": power_info.get("dynamic_power_uw"),
            "power_savings_percent": round(pwr_savings, 2),
            "baseline_power_uw": base_pwr["total_power_uw"] if base_pwr else None,
            "verification_status": verif_info.get("status", "NOT_RUN"),
            "control_errors": verif_info.get("control_errors", 0),
            "control_integrity": verif_info.get("control_integrity", "UNKNOWN"),
            "measured_med": verif_info.get("measured_med"),
            "measured_wce": verif_info.get("measured_wce"),
            "measured_mred": verif_info.get("measured_mred"),
            "bound_satisfied": verif_info.get("error_bound_satisfied", False),
        }
        results.append(record)

    results_file = build_root / "pe_sweep_results.json"
    results_file.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nSaved sweep summary to {results_file}")
    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
    repo_root = Path(__file__).resolve().parent.parent.parent
    build_dir = repo_root / "build" / "systolic_pe_sweep"
    run_sweep(build_dir)
