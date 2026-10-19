"""AxSYS vs. Naive Bit-Truncation Comparative Evaluation.

Rigorous empirical benchmark comparing heuristic Approximate Logic Synthesis (AxSYS)
against traditional Manual LSB Bit-Truncation across Area, Power, MED, WCE, and SQNR.
"""

from __future__ import annotations

import json
import logging
import math
import os
import random
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List

import matplotlib.pyplot as plt
import numpy as np

from axsys.flow import AxcFlow
from axsys.power_estimator import PowerEstimator

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("trunc_comp")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TECH_LIB = REPO_ROOT / "third_party" / "AxLS" / "templates" / "NanGate15nm.lib"
TECH_V = REPO_ROOT / "third_party" / "AxLS" / "templates" / "NanGate15nm.v"
BUILD_DIR = REPO_ROOT / "build" / "truncation_comparison"

PE_EXACT_RTL = REPO_ROOT / "examples" / "systolic_pe" / "rtl" / "pe.sv"


def synthesize_to_gate_level(input_vlog: Path, top_module: str, output_vlog: Path) -> bool:
    """Synthesize Verilog RTL to NanGate 15nm gate netlist using Yosys."""
    output_vlog.parent.mkdir(parents=True, exist_ok=True)
    ys_script = (
        f"read_verilog -sv {input_vlog}; "
        f"hierarchy -check -top {top_module}; "
        f"proc; opt_expr; opt_clean; "
        f"synth -top {top_module}; "
        f"dfflibmap -liberty {TECH_LIB}; "
        f"abc -liberty {TECH_LIB}; "
        f"opt_clean; "
        f"write_verilog {output_vlog}"
    )
    cmd = ["yosys", "-p", ys_script]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        logger.error("Yosys synthesis failed:\n%s", res.stderr)
        return False
    return True


def simulate_and_measure_errors(
    exact_netlist: Path,
    test_netlist: Path,
    num_cycles: int = 1000,
    top_name: str = "pe",
) -> Dict[str, float]:
    """Run dual-miter simulation between exact netlist and test netlist, measuring error metrics."""
    with tempfile.TemporaryDirectory(prefix="miter_sim_") as tmp_dir:
        td = Path(tmp_dir)

        # Rename test netlist top module and export only design modules (prevent standard-cell duplicate collisions)
        test_renamed = td / f"{top_name}_test.v"
        rename_cmd = (
            f"read_verilog {test_netlist}; "
            f"rename {top_name} {top_name}_test; "
            f"select {top_name}_test; "
            f"select -add {top_name}_axc_cone_0; "
            f"write_verilog -selected {test_renamed}"
        )
        subprocess.run(["yosys", "-p", rename_cmd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        tb_path = td / "tb_compare.v"
        tb_code = f"""
`timescale 1ns / 1ps

module tb_compare;
    reg clk;
    reg rst_n;
    reg clear;
    reg signed [7:0] a_in;
    reg signed [7:0] b_in;
    reg valid_in;

    wire signed [7:0] a_out_exact, a_out_test;
    wire signed [7:0] b_out_exact, b_out_test;
    wire valid_out_exact, valid_out_test;
    wire signed [18:0] acc_exact;
    wire signed [18:0] acc_test;

    // Golden exact instance (Behavioral SystemVerilog RTL)
    {top_name} uut_exact (
        .clk(clk), .rst_n(rst_n), .clear(clear),
        .a_in(a_in), .b_in(b_in), .valid_in(valid_in),
        .a_out(a_out_exact), .b_out(b_out_exact), .valid_out(valid_out_exact),
        .acc(acc_exact)
    );

    // Approximate / Truncated instance (Gate-level mapped)
    {top_name}_test uut_test (
        .clk(clk), .rst_n(rst_n), .clear(clear),
        .a_in(a_in), .b_in(b_in), .valid_in(valid_in),
        .a_out(a_out_test), .b_out(b_out_test), .valid_out(valid_out_test),
        .acc(acc_test)
    );

    always #5 clk = ~clk;

    integer cycle = 0;
    integer control_errors = 0;
    real total_error = 0.0;
    real max_error = 0.0;
    real total_sq_error = 0.0;
    real total_exact_power = 0.0;
    integer error_count = 0;

    real cur_diff;

    initial begin
        clk = 0;
        rst_n = 0;
        clear = 0;
        a_in = 0;
        b_in = 0;
        valid_in = 0;

        #20 rst_n = 1;
        #10 valid_in = 1;
    end

    always @(posedge clk) begin
        if (rst_n) begin
            cycle = cycle + 1;

            // Check control integrity
            if (valid_out_exact !== valid_out_test ||
                a_out_exact !== a_out_test ||
                b_out_exact !== b_out_test) begin
                control_errors = control_errors + 1;
            end

            // Measure arithmetic error on accumulator
            cur_diff = acc_exact - acc_test;
            if (cur_diff < 0) cur_diff = -cur_diff;

            total_error = total_error + cur_diff;
            if (cur_diff > max_error) max_error = cur_diff;
            total_sq_error = total_sq_error + (cur_diff * cur_diff);
            total_exact_power = total_exact_power + (acc_exact * acc_exact);

            if (cur_diff > 0.0) error_count = error_count + 1;

            // Randomize inputs every cycle
            a_in <= $random % 128;
            b_in <= $random % 128;
            if (cycle % 50 == 0) clear <= 1;
            else                 clear <= 0;

            if (cycle >= {num_cycles}) begin
                $display("RESULT_CYCLES: %0d", cycle);
                $display("RESULT_CTRL_ERR: %0d", control_errors);
                $display("RESULT_MED: %f", total_error / cycle);
                $display("RESULT_WCE: %f", max_error);
                $display("RESULT_MSED: %f", total_sq_error / cycle);
                $display("RESULT_ER: %f", (error_count * 100.0) / cycle);
                $display("RESULT_SIG_PWR: %f", total_exact_power / cycle);
                $finish;
            end
        end
    end
endmodule
"""
        tb_path.write_text(tb_code)

        sim_out = td / "sim.vvp"
        cmd_compile = [
            "iverilog", "-g2012", "-DPRIMITIVES", "-o", str(sim_out),
            str(tb_path), str(PE_EXACT_RTL), str(test_renamed), str(TECH_V)
        ]
        res_comp = subprocess.run(cmd_compile, capture_output=True, text=True)
        if res_comp.returncode != 0:
            logger.error("Simulation compilation failed:\n%s", res_comp.stderr)
            return {"med": -1, "wce": -1, "msed": -1, "sqnr_db": -1, "control_errors": -1}

        res_sim = subprocess.run(["vvp", str(sim_out)], capture_output=True, text=True, timeout=60)
        stdout = res_sim.stdout

        def get_val(pattern: str, default: float = 0.0) -> float:
            m = re.search(pattern, stdout)
            return float(m.group(1)) if m else default

        med = get_val(r"RESULT_MED:\s+([\d\.]+)")
        wce = get_val(r"RESULT_WCE:\s+([\d\.]+)")
        msed = get_val(r"RESULT_MSED:\s+([\d\.]+)")
        er = get_val(r"RESULT_ER:\s+([\d\.]+)")
        ctrl_err = int(get_val(r"RESULT_CTRL_ERR:\s+(\d+)"))
        sig_pwr = get_val(r"RESULT_SIG_PWR:\s+([\d\.]+)")

        sqnr_db = 10.0 * math.log10(sig_pwr / msed) if msed > 0 and sig_pwr > 0 else 99.0

        return {
            "med": round(med, 3),
            "wce": round(wce, 1),
            "msed": round(msed, 3),
            "sqnr_db": round(sqnr_db, 2),
            "er_percent": round(er, 2),
            "control_errors": ctrl_err,
        }


def generate_truncated_rtl(k_bits: int, out_path: Path) -> Path:
    """Generate SystemVerilog RTL for systolic PE with k lower product bits truncated."""
    rtl = f"""`timescale 1ns/1ps

module pe #(
    parameter int DW = 8,
    parameter int K = 8
) (
    input logic clk,
    input logic rst_n,
    input logic clear,
    input logic signed [DW-1:0] a_in,
    input logic signed [DW-1:0] b_in,
    input logic valid_in,
    output logic signed [DW-1:0] a_out,
    output logic signed [DW-1:0] b_out,
    output logic signed valid_out,
    output logic signed [2*DW + 3 - 1:0] acc
);
    localparam int ACC_DW = 2*DW + 3;
    logic signed [ACC_DW-1:0] prod_full;
    logic signed [ACC_DW-1:0] prod;

    assign prod_full = (a_in * b_in);
    // Truncate lower {k_bits} bits (wire to zero for dead-logic pruning)
    assign prod = {{prod_full[ACC_DW-1:{k_bits}], {{{k_bits}{{1'b0}}}}}};

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
    out_path.write_text(rtl, encoding="utf-8")
    return out_path


def run_comparison() -> Dict[str, Any]:
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    pwr_estimator = PowerEstimator(tech="NanGate15nm", clk_mhz=100.0)

    # 1. Exact Baseline
    logger.info("=== STEP 1: Synthesizing Exact Baseline ===")
    exact_mapped = BUILD_DIR / "exact_baseline_mapped.v"
    if not exact_mapped.exists():
        synthesize_to_gate_level(PE_EXACT_RTL, "pe", exact_mapped)
    exact_pwr = pwr_estimator.evaluate_netlist(exact_mapped)
    base_area = exact_pwr["cell_area_um2"]
    base_power = exact_pwr["total_power_uw"]
    base_cells = exact_pwr["cell_count"]
    logger.info("Exact Baseline: Area=%.2f um^2, Power=%.2f uW, Cells=%d", base_area, base_power, base_cells)

    # 2. Naive Truncation Sweep
    logger.info("=== STEP 2: Evaluating Naive Truncation (k = 1..8) ===")
    trunc_results = []
    for k in [1, 2, 3, 4, 5, 6, 7, 8]:
        trunc_rtl = BUILD_DIR / f"pe_trunc_{k}.sv"
        generate_truncated_rtl(k, trunc_rtl)
        trunc_mapped = BUILD_DIR / f"pe_trunc_{k}_mapped.v"
        synthesize_to_gate_level(trunc_rtl, "pe", trunc_mapped)
        pwr = pwr_estimator.evaluate_netlist(trunc_mapped)

        area_saved_pct = round(((base_area - pwr["cell_area_um2"]) / base_area) * 100.0, 2)
        power_saved_pct = round(((base_power - pwr["total_power_uw"]) / base_power) * 100.0, 2)

        err_metrics = simulate_and_measure_errors(exact_mapped, trunc_mapped, num_cycles=1000)

        item = {
            "name": f"Trunc-{k}",
            "k_bits": k,
            "type": "Naive Truncation",
            "cells": pwr["cell_count"],
            "area_um2": pwr["cell_area_um2"],
            "area_saved_pct": area_saved_pct,
            "power_uw": pwr["total_power_uw"],
            "power_saved_pct": power_saved_pct,
            **err_metrics,
        }
        trunc_results.append(item)
        logger.info("Trunc-%d: AreaSaved=%.2f%%, PowerSaved=%.2f%%, MED=%.3f, WCE=%.1f, SQNR=%.2f dB",
                    k, area_saved_pct, power_saved_pct, item["med"], item["wce"], item["sqnr_db"])

    # 3. AxSYS Heuristic Pruning Sweep
    logger.info("=== STEP 3: Evaluating AxSYS Heuristic ALS ===")
    axsys_configs = [
        {"name": "AxSYS-Light", "bound": "8.0", "lsb": 2},
        {"name": "AxSYS-Conserv", "bound": "16.0", "lsb": 4},
        {"name": "AxSYS-Moderate", "bound": "32.0", "lsb": 6},
        {"name": "AxSYS-Aggressive", "bound": "64.0", "lsb": 8},
    ]

    axsys_results = []
    pe_sweep_dir = REPO_ROOT / "build" / "systolic_pe_sweep"
    for cfg in axsys_configs:
        cname = cfg["name"]
        # Use existing generated netlist from pe sweep or flow run
        cfg_tag = {
            "AxSYS-Light": "cfg0_light",
            "AxSYS-Conserv": "cfg1_conservative",
            "AxSYS-Moderate": "cfg2_moderate",
            "AxSYS-Aggressive": "cfg3_aggressive",
        }[cname]
        approx_netlist = pe_sweep_dir / cfg_tag / "final_approx_top.v"

        if not approx_netlist.exists():
            # Run flow if missing
            out_run = BUILD_DIR / cfg_tag
            flow = AxcFlow(
                input_verilog=PE_EXACT_RTL,
                output_dir=out_run,
                tech="NanGate15nm",
                clk_period_ns=10.0,
                sim_samples=100,
                verify_cycles=200,
            )
            flow.run()
            approx_netlist = out_run / "final_approx_top.v"

        pwr = pwr_estimator.evaluate_netlist(approx_netlist)
        area_saved_pct = round(((base_area - pwr["cell_area_um2"]) / base_area) * 100.0, 2)
        power_saved_pct = round(((base_power - pwr["total_power_uw"]) / base_power) * 100.0, 2)
        err_metrics = simulate_and_measure_errors(exact_mapped, approx_netlist, num_cycles=1000)

        item = {
            "name": cname,
            "type": "AxSYS (ALS)",
            "cells": pwr["cell_count"],
            "area_um2": pwr["cell_area_um2"],
            "area_saved_pct": area_saved_pct,
            "power_uw": pwr["total_power_uw"],
            "power_saved_pct": power_saved_pct,
            **err_metrics,
        }
        axsys_results.append(item)
        logger.info("%s: AreaSaved=%.2f%%, PowerSaved=%.2f%%, MED=%.3f, WCE=%.1f, SQNR=%.2f dB",
                    cname, area_saved_pct, power_saved_pct, item["med"], item["wce"], item["sqnr_db"])

    # 4. Generate Plot
    logger.info("=== STEP 4: Generating Pareto Tradeoff Plots ===")
    fig, axes = plt.subplots(2, 2, figsize=(13, 10))
    fig.suptitle("AxSYS Heuristic ALS vs. Naive Bit-Truncation Tradeoff Analysis\n(INT8 Systolic PE, NanGate 15nm Open Cell Library)", fontsize=14, fontweight="bold")

    # Panel 1: Area Savings vs MED
    ax1 = axes[0, 0]
    ax1.plot([t["area_saved_pct"] for t in trunc_results], [t["med"] for t in trunc_results], "r--o", label="Naive Truncation (k=1..8)", linewidth=2, markersize=7)
    ax1.plot([a["area_saved_pct"] for a in axsys_results], [a["med"] for a in axsys_results], "g-s", label="AxSYS (Heuristic ALS)", linewidth=2.5, markersize=8)
    for a in axsys_results:
        ax1.annotate(a["name"].replace("AxSYS-", ""), (a["area_saved_pct"], a["med"]), textcoords="offset points", xytext=(0, 8), ha="center", fontsize=9, fontweight="bold", color="darkgreen")
    ax1.set_xlabel("Silicon Area Savings (%)", fontweight="bold")
    ax1.set_ylabel("Mean Error Distance (MED)", fontweight="bold")
    ax1.set_title("Pareto Frontier: Area Savings vs. MED (Lower is Better)")
    ax1.grid(True, linestyle=":", alpha=0.6)
    ax1.legend(loc="upper left")

    # Panel 2: Area Savings vs WCE
    ax2 = axes[0, 1]
    ax2.plot([t["area_saved_pct"] for t in trunc_results], [t["wce"] for t in trunc_results], "r--o", label="Naive Truncation", linewidth=2, markersize=7)
    ax2.plot([a["area_saved_pct"] for a in axsys_results], [a["wce"] for a in axsys_results], "g-s", label="AxSYS (Heuristic ALS)", linewidth=2.5, markersize=8)
    for a in axsys_results:
        ax2.annotate(a["name"].replace("AxSYS-", ""), (a["area_saved_pct"], a["wce"]), textcoords="offset points", xytext=(0, 8), ha="center", fontsize=9, fontweight="bold", color="darkgreen")
    ax2.set_xlabel("Silicon Area Savings (%)", fontweight="bold")
    ax2.set_ylabel("Worst-Case Error (WCE)", fontweight="bold")
    ax2.set_title("Worst-Case Error Bounding (Lower is Better)")
    ax2.grid(True, linestyle=":", alpha=0.6)
    ax2.legend(loc="upper left")

    # Panel 3: Power Savings vs SQNR
    ax3 = axes[1, 0]
    ax3.plot([t["power_saved_pct"] for t in trunc_results], [t["sqnr_db"] for t in trunc_results], "r--o", label="Naive Truncation", linewidth=2, markersize=7)
    ax3.plot([a["power_saved_pct"] for a in axsys_results], [a["sqnr_db"] for a in axsys_results], "g-s", label="AxSYS (Heuristic ALS)", linewidth=2.5, markersize=8)
    for a in axsys_results:
        ax3.annotate(a["name"].replace("AxSYS-", ""), (a["power_saved_pct"], a["sqnr_db"]), textcoords="offset points", xytext=(0, -14), ha="center", fontsize=9, fontweight="bold", color="darkgreen")
    ax3.set_xlabel("Total Power Savings (%)", fontweight="bold")
    ax3.set_ylabel("SQNR (dB) (Higher is Better)", fontweight="bold")
    ax3.set_title("Signal Fidelity: Power Savings vs. SQNR")
    ax3.grid(True, linestyle=":", alpha=0.6)
    ax3.legend(loc="lower left")

    # Panel 4: MSED vs Area Savings
    ax4 = axes[1, 1]
    ax4.plot([t["area_saved_pct"] for t in trunc_results], [t["msed"] for t in trunc_results], "r--o", label="Naive Truncation", linewidth=2, markersize=7)
    ax4.plot([a["area_saved_pct"] for a in axsys_results], [a["msed"] for a in axsys_results], "g-s", label="AxSYS (Heuristic ALS)", linewidth=2.5, markersize=8)
    for a in axsys_results:
        ax4.annotate(a["name"].replace("AxSYS-", ""), (a["area_saved_pct"], a["msed"]), textcoords="offset points", xytext=(0, 8), ha="center", fontsize=9, fontweight="bold", color="darkgreen")
    ax4.set_xlabel("Silicon Area Savings (%)", fontweight="bold")
    ax4.set_ylabel("Mean Squared Error (MSED)", fontweight="bold")
    ax4.set_title("Error Energy: MSED vs. Area Savings")
    ax4.grid(True, linestyle=":", alpha=0.6)
    ax4.legend(loc="upper left")

    plt.tight_layout()
    plot_path = REPO_ROOT / "reports" / "truncation_vs_axsys_pareto.png"
    plt.savefig(plot_path, dpi=200)
    plt.close()
    logger.info("Saved comparative plot to %s", plot_path)

    # 5. Output Summary Report
    all_data = {
        "baseline": {
            "area_um2": base_area,
            "power_uw": base_power,
            "cell_count": base_cells,
        },
        "truncation": trunc_results,
        "axsys": axsys_results,
    }
    json_path = BUILD_DIR / "truncation_comparison_results.json"
    json_path.write_text(json.dumps(all_data, indent=2))

    return all_data


if __name__ == "__main__":
    run_comparison()
