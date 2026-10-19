"""Top-Level Flow Orchestrator for Attribute-Driven Approximate Computing.

Coordinates the complete pipeline:
1. RTLIL Relaxability Analysis & Cone Extraction (Pyosys)
2. Approximate Logic Synthesis Optimization (AxLS)
3. Parent Shell & Approximated Cone Re-integration (Yosys)
4. Attribute-Driven SDC Timing Relaxation Generation
5. Automated Miter Verification (Icarus Verilog)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

from axsys.axls_bridge import AxlsBridge
from axsys.cone_extractor import ConeExtractor
from axsys.reintegrator import Reintegrator
from axsys.power_estimator import PowerEstimator
from axsys.sdc_generator import SdcGenerator
from axsys.verifier import MiterVerifier

logger = logging.getLogger("axc_flow")


class AxcFlow:
    """Full-flow execution manager."""

    def __init__(
        self,
        input_verilog: str | Path,
        output_dir: str | Path,
        tech: str = "NanGate15nm",
        clk_port: str = "clk",
        clk_period_ns: float = 10.0,
        sim_samples: int = 500,
        verify_cycles: int = 500,
    ):
        self.input_verilog = Path(input_verilog).resolve()
        self.output_dir = Path(output_dir).resolve()
        self.tech = tech
        self.clk_port = clk_port
        self.clk_period_ns = clk_period_ns
        self.sim_samples = sim_samples
        self.verify_cycles = verify_cycles

        # Resolve tech Verilog library path
        tech_p = Path(self.tech)
        if tech_p.is_file():
            self.tech_vlog_path: Optional[Path] = tech_p.resolve()
        else:
            cand = Path(__file__).resolve().parent.parent / "third_party" / "AxLS" / "templates" / f"{self.tech}.v"
            self.tech_vlog_path = cand.resolve() if cand.is_file() else None

        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run(self) -> Dict[str, Any]:
        """Execute the end-to-end flow."""
        start_time = time.time()
        logger.info("=== STARTING AXC EDA FLOW ===")
        logger.info("Input Verilog: %s", self.input_verilog)
        logger.info("Output Directory: %s", self.output_dir)
        logger.info("Technology: %s (library file: %s)", self.tech, self.tech_vlog_path)

        # -------------------------------------------------------------
        # STEP 1: Cone Extraction
        # -------------------------------------------------------------
        logger.info("--- Step 1: RTLIL Relaxability Analysis & Cone Extraction ---")
        submod_vlog = self.output_dir / "extracted_cone.v"
        top_shell_vlog = self.output_dir / "top_shell.v"
        meta_json_path = self.output_dir / "cone_meta.json"

        extractor = ConeExtractor(verilog_path=self.input_verilog)
        cone_result = extractor.extract_safe_cone(
            submod_tag="axc_cone_0",
            out_submod_path=submod_vlog,
            out_top_path=top_shell_vlog,
            out_meta_path=meta_json_path,
        )

        if cone_result.get("status") != "SUCCESS":
            elapsed = time.time() - start_time
            status_reason = cone_result.get("status", "EXTRACTION_FAILED")
            logger.warning("Cone extraction halted with status: %s", status_reason)
            stopped_summary: Dict[str, Any] = {
                "flow_status": "STOPPED",
                "reason": status_reason,
                "top_module": cone_result.get("top_module", "unknown"),
                "elapsed_seconds": round(elapsed, 2),
                "details": cone_result,
            }
            summary_path = self.output_dir / "flow_summary.json"
            with open(summary_path, "w", encoding="utf-8") as f:
                json.dump(stopped_summary, f, indent=2)
            return stopped_summary

        relaxed_signals = cone_result.get("relaxed_signals", [])
        logger.info("Identified %d relaxed signal(s): %s", len(relaxed_signals), [s.get("wire") for s in relaxed_signals])
        for s in relaxed_signals:
            logger.info("  Signal: %s | Metric: %s | Bound: %s | LSB: %s",
                        s.get("wire"), s.get("metric"), s.get("bound"), s.get("lsb_width"))

        primary_metric = relaxed_signals[0].get("metric", "MED") if relaxed_signals else "MED"
        # When multiple relaxed signals exist, target the most restrictive (minimum) bound
        bounds_list = [float(s["bound"]) for s in relaxed_signals if "bound" in s]
        primary_bound = min(bounds_list) if bounds_list else 0.05

        lsb_candidates = [int(s["lsb_width"]) for s in relaxed_signals if s.get("lsb_width") is not None]
        primary_lsb = max(lsb_candidates) if lsb_candidates else None

        # -------------------------------------------------------------
        # STEP 2: AxLS Logic Approximation
        # -------------------------------------------------------------
        logger.info("--- Step 2: AxLS Gate-Level Approximation ---")
        approx_cone_vlog = self.output_dir / "approx_cone.v"
        axls_work_dir = self.output_dir / "axls_workspace"

        bridge = AxlsBridge(
            cone_verilog_path=submod_vlog,
            tech=self.tech,
            samples=self.sim_samples,
            work_dir=axls_work_dir,
        )

        approx_result = bridge.optimize(
            metric=primary_metric,
            bound=primary_bound,
            lsb_width=primary_lsb,
            out_approx_path=approx_cone_vlog,
        )

        # -------------------------------------------------------------
        # STEP 3: Re-Integration
        # -------------------------------------------------------------
        logger.info("--- Step 3: Top Shell and Approximate Cone Re-integration ---")
        final_top_vlog = self.output_dir / "final_approx_top.v"

        reintegrator = Reintegrator(
            top_shell_path=top_shell_vlog,
            approx_cone_path=approx_cone_vlog,
            tech=self.tech,
            tech_verilog_path=self.tech_vlog_path,
        )
        reint_result = reintegrator.reintegrate(out_final_path=final_top_vlog)

        # -------------------------------------------------------------
        # STEP 4: SDC Constraint Generation
        # -------------------------------------------------------------
        logger.info("--- Step 4: Attribute-Driven SDC Timing Constraint Generation ---")
        out_sdc_path = self.output_dir / "final_approx_top.sdc"

        sdc_gen = SdcGenerator(
            clk_port=self.clk_port,
            clk_period_ns=self.clk_period_ns,
            relaxation_factor=1.5,
            constraint_mode="max_delay",
        )
        sdc_gen.generate_sdc(metadata=cone_result, out_sdc_path=out_sdc_path)

        # -------------------------------------------------------------
        # STEP 5: Automated Verification
        # -------------------------------------------------------------
        logger.info("--- Step 5: Miter Verification Harness ---")
        verifier = MiterVerifier(
            exact_vlog=self.input_verilog,
            approx_vlog=final_top_vlog,
            meta_json=meta_json_path,
            tech=self.tech,
            tech_vlog=self.tech_vlog_path,
            num_cycles=self.verify_cycles,
        )
        verify_result = verifier.verify()

        # -------------------------------------------------------------
        # STEP 6: Power Dissipation Estimation
        # -------------------------------------------------------------
        logger.info("--- Step 6: Power Dissipation Estimation ---")
        power_info: Dict[str, Any] = {}
        try:
            clk_mhz = 1000.0 / self.clk_period_ns if self.clk_period_ns > 0 else 100.0
            power_estimator = PowerEstimator(tech=self.tech, clk_mhz=clk_mhz)
            power_info = power_estimator.evaluate_netlist(final_top_vlog)
            logger.info(
                "Power dissipation: Total=%.3f uW (Leakage=%.3f uW, Dynamic=%.3f uW)",
                power_info["total_power_uw"],
                power_info["leakage_power_uw"],
                power_info["dynamic_power_uw"],
            )
        except Exception as exc:
            logger.warning("Power estimation could not be completed: %s", exc)

        elapsed = time.time() - start_time
        logger.info("=== FLOW FINISHED IN %.2f SECONDS ===", elapsed)

        summary: Dict[str, Any] = {
            "flow_status": "SUCCESS" if verify_result.get("status") == "PASSED" else "VERIFICATION_FAILED",
            "elapsed_seconds": round(elapsed, 2),
            "top_module": cone_result.get("top_module", "unknown"),
            "submodule_module": cone_result.get("submodule_module", ""),
            "extracted_safe_cells": cone_result.get("num_safe_cells", 0),
            "approximation": {
                "metric": primary_metric,
                "bound": primary_bound,
                "relaxed_signals": relaxed_signals,
                "measured_error": approx_result.get("measured_error"),
                "pruned_nodes": approx_result.get("pruned_nodes_count"),
                "initial_area": approx_result.get("initial_area"),
                "approx_area": approx_result.get("final_area"),
                "area_savings_percent": approx_result.get("area_savings_percent"),
            },
            "power": power_info,
            "verification": verify_result,
            "generated_files": {
                "top_shell": str(top_shell_vlog),
                "extracted_cone": str(submod_vlog),
                "approx_cone": str(approx_cone_vlog),
                "final_approx_top": str(final_top_vlog),
                "sdc_constraints": str(out_sdc_path),
                "metadata": str(meta_json_path),
            },
        }

        # Write run summary JSON
        summary_path = self.output_dir / "flow_summary.json"
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)

        return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Full Axc EDA Flow Orchestrator")
    parser.add_argument("-i", "--input", required=True, help="Input annotated Verilog file")
    parser.add_argument("-o", "--output-dir", default="build/axc_output", help="Output directory")
    parser.add_argument("-t", "--tech", default="NanGate15nm", help="Standard cell tech library")
    parser.add_argument("--clk", "--clk-port", dest="clk", default="clk", help="Clock port name")
    parser.add_argument("--period", "--clk-period", dest="period", type=float, default=10.0, help="Clock period in ns")
    parser.add_argument("-s", "--samples", type=int, default=300, help="AxLS simulation samples")
    parser.add_argument("-n", "--verify-cycles", type=int, default=300, help="Miter verification clock cycles")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging")

    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    flow = AxcFlow(
        input_verilog=args.input,
        output_dir=args.output_dir,
        tech=args.tech,
        clk_port=args.clk,
        clk_period_ns=args.period,
        sim_samples=args.samples,
        verify_cycles=args.verify_cycles,
    )
    result = flow.run()
    print(json.dumps(result, indent=2))
    if result.get("flow_status") != "SUCCESS":
        sys.exit(1)


if __name__ == "__main__":
    main()
