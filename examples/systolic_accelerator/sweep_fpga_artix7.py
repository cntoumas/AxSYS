"""Comprehensive FPGA (Xilinx Artix-7) Evaluation for the Systolic Accelerator.

Synthesizes the complete 2D systolic tensor accelerator core to Xilinx 7-Series
(Artix-7 XC7A35T / XC7A100T) FPGA architecture using Yosys synth_xilinx.

Measures:
- 6-input and 5-input LUT utilization (LUT2..LUT6)
- CARRY4 fast-carry chain primitives
- Flip-Flop registers (FDCE / FDPE)
- Estimated Logic Cells (LCs) / Slice Utilization
- Device footprint percentage on Artix-7 XC7A35T
- Matrix accuracy (MED, NMED, Frobenius norm error) and control integrity
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List

import pyosys
from pyosys import libyosys as yosys

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("fpga_artix7_sweep")

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent.parent
RTL_DIR = WORKSPACE_ROOT / "examples" / "systolic_accelerator" / "rtl"
BUILD_DIR = WORKSPACE_ROOT / "build" / "accelerator_sweep"

# Xilinx Artix-7 XC7A35T Hardware Limits
ARTIX7_35T_LUTS = 20800
ARTIX7_35T_FFS = 41600
ARTIX7_35T_DSPS = 90

CONFIGS = [
    {"id": "fpga_exact_4x4", "name": "Exact Baseline", "scale": "4x4", "rows": 4, "cols": 4, "k": 4, "lsb": 0},
    {"id": "fpga_light_4x4", "name": "Light Approx (LSB=2)", "scale": "4x4", "rows": 4, "cols": 4, "k": 4, "lsb": 2},
    {"id": "fpga_conserv_4x4", "name": "Conservative Approx (LSB=4)", "scale": "4x4", "rows": 4, "cols": 4, "k": 4, "lsb": 4},
    {"id": "fpga_moderate_4x4", "name": "Moderate Approx (LSB=6)", "scale": "4x4", "rows": 4, "cols": 4, "k": 4, "lsb": 6},
    {"id": "fpga_aggress_4x4", "name": "Aggressive Approx (LSB=8)", "scale": "4x4", "rows": 4, "cols": 4, "k": 4, "lsb": 8},
    {"id": "fpga_exact_8x8", "name": "Exact 8x8 Core", "scale": "8x8", "rows": 8, "cols": 8, "k": 8, "lsb": 0},
    {"id": "fpga_approx_8x8", "name": "Approx 8x8 Core (LSB=4)", "scale": "8x8", "rows": 8, "cols": 8, "k": 8, "lsb": 4},
]


def synthesize_artix7(cfg: Dict[str, Any], nodsp: bool = True) -> Dict[str, Any]:
    """Run Yosys synth_xilinx for Artix-7 (xc7) and extract primitive counts."""
    logger.info("Synthesizing %s for Artix-7 (ROWS=%d, LSB=%d, nodsp=%s)...", cfg["id"], cfg["rows"], cfg["lsb"], nodsp)
    t0 = time.time()
    d = yosys.Design()
    yosys.run_pass(f"read_verilog {RTL_DIR / 'pe_mac.v'}", d)
    yosys.run_pass(f"read_verilog {RTL_DIR / 'systolic4x4.v'}", d)
    yosys.run_pass(
        f"chparam -set ROWS {cfg['rows']} -set COLS {cfg['cols']} -set K {cfg['k']} -set APPROX_LSB {cfg['lsb']} Systolic4x4",
        d
    )
    dsp_flag = "-nodsp" if nodsp else ""
    yosys.run_pass(f"synth_xilinx -family xc7 -flatten -noiopad {dsp_flag} -top Systolic4x4", d)
    
    top = d.top_module()
    cell_counts: Dict[str, int] = {}
    for cid, cell in top.cells_.items():
        ctype = cell.type.str().lstrip("\\")
        cell_counts[ctype] = cell_counts.get(ctype, 0) + 1

    # Aggregate FPGA primitives
    luts_by_type = {k: v for k, v in cell_counts.items() if k.startswith("LUT")}
    total_luts = sum(luts_by_type.values())
    carry4_count = cell_counts.get("CARRY4", 0)
    ff_count = sum(v for k, v in cell_counts.items() if k.startswith("FD"))
    dsp_count = cell_counts.get("DSP48E1", 0)
    
    # Estimate Logic Cells (standard Xilinx metric: 1.6 * total LUTs or LUTs + carry)
    est_lcs = total_luts + carry4_count * 2

    elapsed = time.time() - t0
    logger.info(
        "Synthesized %s in %.2fs: Total LUTs=%d, CARRY4=%d, FFs=%d, DSPs=%d",
        cfg["id"], elapsed, total_luts, carry4_count, ff_count, dsp_count
    )

    return {
        "total_luts": total_luts,
        "luts_by_type": luts_by_type,
        "carry4": carry4_count,
        "ffs": ff_count,
        "dsps": dsp_count,
        "estimated_lcs": est_lcs,
        "artix7_35t_lut_util_pct": round((total_luts / ARTIX7_35T_LUTS) * 100.0, 2),
        "artix7_35t_ff_util_pct": round((ff_count / ARTIX7_35T_FFS) * 100.0, 2),
        "synth_time_sec": round(elapsed, 2)
    }


def simulate_verification(cfg: Dict[str, Any], num_tests: int = 100) -> Dict[str, Any]:
    """Run verification in Icarus Verilog and extract accuracy metrics."""
    sim_bin = BUILD_DIR / f"sim_fpga_{cfg['id']}.out"
    compile_cmd = [
        "iverilog", "-g2012",
        f"-Ptb_accelerator_multi.ROWS={cfg['rows']}",
        f"-Ptb_accelerator_multi.COLS={cfg['cols']}",
        f"-Ptb_accelerator_multi.K={cfg['k']}",
        f"-Ptb_accelerator_multi.APPROX_LSB={cfg['lsb']}",
        f"-Ptb_accelerator_multi.NUM_TESTS={num_tests}",
        "-o", str(sim_bin),
        str(RTL_DIR / "pe_mac.v"),
        str(RTL_DIR / "systolic4x4.v"),
        str(RTL_DIR / "tb_accelerator_multi.sv")
    ]
    subprocess.run(compile_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    res_run = subprocess.run(["vvp", str(sim_bin)], capture_output=True, text=True, check=True)
    m = re.search(r"ACCEL_METRICS:\s*(\{.*\})", res_run.stdout)
    return json.loads(m.group(1)) if m else {}


def main():
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    results = []

    baseline_fpga: Dict[str, Dict[str, Any]] = {}

    for cfg in CONFIGS:
        fpga_res = synthesize_artix7(cfg, nodsp=True)
        sim_metrics = simulate_verification(cfg, num_tests=100)

        scale_key = cfg["scale"]
        if cfg["lsb"] == 0:
            baseline_fpga[scale_key] = fpga_res

        base = baseline_fpga[scale_key]
        lut_red_pct = ((base["total_luts"] - fpga_res["total_luts"]) / base["total_luts"]) * 100.0 if base["total_luts"] > 0 else 0.0
        carry_red_pct = ((base["carry4"] - fpga_res["carry4"]) / base["carry4"]) * 100.0 if base["carry4"] > 0 else 0.0
        lc_red_pct = ((base["estimated_lcs"] - fpga_res["estimated_lcs"]) / base["estimated_lcs"]) * 100.0 if base["estimated_lcs"] > 0 else 0.0

        item = {
            "config_id": cfg["id"],
            "name": cfg["name"],
            "scale": scale_key,
            "rows": cfg["rows"],
            "cols": cfg["cols"],
            "num_pes": cfg["rows"] * cfg["cols"],
            "lsb_width": cfg["lsb"],
            "total_luts": fpga_res["total_luts"],
            "lut_reduction_pct": round(lut_red_pct, 2),
            "luts_saved": base["total_luts"] - fpga_res["total_luts"],
            "carry4": fpga_res["carry4"],
            "carry_reduction_pct": round(carry_red_pct, 2),
            "carry_saved": base["carry4"] - fpga_res["carry4"],
            "ffs": fpga_res["ffs"],
            "estimated_lcs": fpga_res["estimated_lcs"],
            "lc_reduction_pct": round(lc_red_pct, 2),
            "artix7_35t_lut_util_pct": fpga_res["artix7_35t_lut_util_pct"],
            "artix7_35t_ff_util_pct": fpga_res["artix7_35t_ff_util_pct"],
            "luts_by_type": fpga_res["luts_by_type"],
            "sim_metrics": sim_metrics,
            "flow_status": "PASSED" if sim_metrics.get("control_errors", 0) == 0 else "FAILED"
        }
        results.append(item)
        logger.info(
            "FPGA RESULT [%s]: LUTs=%d (-%.1f%%, %d saved) | CARRY4=%d (-%.1f%%) | FFs=%d | Frobenius Err=%.3f%% | Artix35T Util=%.1f%%",
            cfg["id"], fpga_res["total_luts"], lut_red_pct, item["luts_saved"],
            fpga_res["carry4"], carry_red_pct, fpga_res["ffs"],
            sim_metrics.get("frobenius_err_pct", 0.0), fpga_res["artix7_35t_lut_util_pct"]
        )

    out_file = BUILD_DIR / "fpga_artix7_sweep_results.json"
    with open(out_file, "w") as f:
        json.dump(results, f, indent=2)

    logger.info("FPGA sweep complete! Results saved to %s", out_file)


if __name__ == "__main__":
    main()
