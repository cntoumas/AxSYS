"""Comprehensive Systolic Accelerator Hardware Sweep, Power Analysis, and Verification.

Evaluates an entire 2D systolic tensor accelerator core (open-source hardware:
ridash2005/Systolic-Array-based-Hardware-Accelerator-for-CNNs) across multiple
approximate computing profiles.

Synthesizes both 4x4 (16 PEs) and 8x8 (64 PEs) accelerator arrays with NanGate 15nm
standard cells, computes static leakage and dynamic switching power via PowerEstimator,
and verifies mathematical matrix multiplication accuracy and zero control drift.
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
from axsys.power_estimator import PowerEstimator

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("accelerator_sweep")

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent.parent
RTL_DIR = WORKSPACE_ROOT / "examples" / "systolic_accelerator" / "rtl"
BUILD_DIR = WORKSPACE_ROOT / "build" / "accelerator_sweep"
LIB_PATH = WORKSPACE_ROOT / "third_party" / "AxLS" / "templates" / "NanGate15nm.lib"


CONFIGS_4X4 = [
    {"id": "exact_4x4", "name": "Exact Baseline", "lsb": 0, "bound": "0.0", "rows": 4, "cols": 4, "k": 4},
    {"id": "cfg0_light_4x4", "name": "Light Approx (LSB=2)", "lsb": 2, "bound": "8.0", "rows": 4, "cols": 4, "k": 4},
    {"id": "cfg1_conservative_4x4", "name": "Conservative Approx (LSB=4)", "lsb": 4, "bound": "16.0", "rows": 4, "cols": 4, "k": 4},
    {"id": "cfg2_moderate_4x4", "name": "Moderate Approx (LSB=6)", "lsb": 6, "bound": "32.0", "rows": 4, "cols": 4, "k": 4},
    {"id": "cfg3_aggressive_4x4", "name": "Aggressive Approx (LSB=8)", "lsb": 8, "bound": "64.0", "rows": 4, "cols": 4, "k": 4},
]

CONFIGS_8X8 = [
    {"id": "exact_8x8", "name": "Exact 8x8 Array", "lsb": 0, "bound": "0.0", "rows": 8, "cols": 8, "k": 8},
    {"id": "approx_8x8", "name": "Approx 8x8 (LSB=4)", "lsb": 4, "bound": "16.0", "rows": 8, "cols": 8, "k": 8},
]


def synthesize_accelerator(cfg: Dict[str, Any], output_netlist: Path) -> None:
    """Synthesize systolic array configuration to NanGate15nm gate netlist."""
    logger.info("Synthesizing %s (ROWS=%d, COLS=%d, APPROX_LSB=%d)...", cfg["id"], cfg["rows"], cfg["cols"], cfg["lsb"])
    t0 = time.time()
    d = yosys.Design()
    yosys.run_pass(f"read_verilog {RTL_DIR / 'pe_mac.v'}", d)
    yosys.run_pass(f"read_verilog {RTL_DIR / 'systolic4x4.v'}", d)
    yosys.run_pass(
        f"chparam -set ROWS {cfg['rows']} -set COLS {cfg['cols']} -set K {cfg['k']} -set APPROX_LSB {cfg['lsb']} Systolic4x4",
        d
    )
    yosys.run_pass("synth -top Systolic4x4 -flatten", d)
    yosys.run_pass(f"dfflibmap -liberty {LIB_PATH}", d)
    yosys.run_pass(f"abc -liberty {LIB_PATH}", d)
    yosys.run_pass("clean", d)
    yosys.run_pass(f"write_verilog -noattr {output_netlist}", d)
    logger.info("Completed synthesis of %s in %.2fs -> %s", cfg["id"], time.time() - t0, output_netlist.name)


def simulate_verification(cfg: Dict[str, Any], num_tests: int = 100) -> Dict[str, Any]:
    """Run multi-batch verification in Icarus Verilog and extract accuracy metrics."""
    logger.info("Simulating %s verification (%d batches)...", cfg["id"], num_tests)
    sim_bin = BUILD_DIR / f"sim_{cfg['id']}.out"
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
    res_comp = subprocess.run(compile_cmd, capture_output=True, text=True)
    if res_comp.returncode != 0:
        raise RuntimeError(f"Simulation compilation failed: {res_comp.stderr}")

    res_run = subprocess.run(["vvp", str(sim_bin)], capture_output=True, text=True)
    if res_run.returncode != 0:
        raise RuntimeError(f"Simulation execution failed: {res_run.stderr}")

    m = re.search(r"ACCEL_METRICS:\s*(\{.*\})", res_run.stdout)
    if not m:
        raise RuntimeError(f"Could not parse ACCEL_METRICS from stdout: {res_run.stdout}")

    return json.loads(m.group(1))


def main():
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    estimator = PowerEstimator("NanGate15nm", lib_path=LIB_PATH)

    all_configs = CONFIGS_4X4 + CONFIGS_8X8
    results: List[Dict[str, Any]] = []

    # Reference exact baselines for delta calculations
    baseline_power: Dict[str, Dict[str, Any]] = {}

    for cfg in all_configs:
        cfg_id = cfg["id"]
        netlist_path = BUILD_DIR / f"{cfg_id}_mapped.v"
        
        # 1. Synthesis
        if not netlist_path.exists():
            synthesize_accelerator(cfg, netlist_path)

        # 2. Power Estimation
        pwr = estimator.evaluate_netlist(netlist_path)

        # 3. Simulation & Accuracy
        sim_metrics = simulate_verification(cfg, num_tests=100)

        scale_key = f"{cfg['rows']}x{cfg['cols']}"
        if cfg["lsb"] == 0:
            baseline_power[scale_key] = pwr

        base = baseline_power.get(scale_key, pwr)
        area_reduction_pct = ((base["cell_area_um2"] - pwr["cell_area_um2"]) / base["cell_area_um2"]) * 100.0 if base["cell_area_um2"] > 0 else 0.0
        power_reduction_pct = ((base["total_power_uw"] - pwr["total_power_uw"]) / base["total_power_uw"]) * 100.0 if base["total_power_uw"] > 0 else 0.0
        cell_reduction_pct = ((base["cell_count"] - pwr["cell_count"]) / base["cell_count"]) * 100.0 if base["cell_count"] > 0 else 0.0
        leak_reduction_pct = ((base["leakage_power_uw"] - pwr["leakage_power_uw"]) / base["leakage_power_uw"]) * 100.0 if base["leakage_power_uw"] > 0 else 0.0
        dyn_reduction_pct = ((base["dynamic_power_uw"] - pwr["dynamic_power_uw"]) / base["dynamic_power_uw"]) * 100.0 if base["dynamic_power_uw"] > 0 else 0.0

        item = {
            "config_id": cfg_id,
            "name": cfg["name"],
            "scale": scale_key,
            "num_pes": cfg["rows"] * cfg["cols"],
            "lsb_width": cfg["lsb"],
            "bound": cfg["bound"],
            "cell_count": pwr["cell_count"],
            "cell_count_reduction_pct": round(cell_reduction_pct, 2),
            "area_um2": round(pwr["cell_area_um2"], 2),
            "area_reduction_pct": round(area_reduction_pct, 2),
            "leakage_power_uw": round(pwr["leakage_power_uw"], 2),
            "leakage_reduction_pct": round(leak_reduction_pct, 2),
            "dynamic_power_uw": round(pwr["dynamic_power_uw"], 2),
            "dynamic_reduction_pct": round(dyn_reduction_pct, 2),
            "total_power_uw": round(pwr["total_power_uw"], 2),
            "power_reduction_pct": round(power_reduction_pct, 2),
            "sim_metrics": sim_metrics,
            "flow_status": "PASSED" if sim_metrics["control_errors"] == 0 else "FAILED",
        }
        results.append(item)
        logger.info(
            "RESULT [%s]: Cells=%d (-%.1f%%) | Area=%.1f um2 (-%.1f%%) | Power=%.1f uW (-%.1f%%) | Frobenius Err=%.3f%% | Control Errors=%d",
            cfg_id, pwr["cell_count"], cell_reduction_pct, pwr["cell_area_um2"], area_reduction_pct,
            pwr["total_power_uw"], power_reduction_pct, sim_metrics["frobenius_err_pct"], sim_metrics["control_errors"]
        )

    out_file = BUILD_DIR / "accelerator_sweep_results.json"
    with open(out_file, "w") as f:
        json.dump(results, f, indent=2)

    logger.info("Accelerator sweep complete! Results saved to %s", out_file)


if __name__ == "__main__":
    main()
