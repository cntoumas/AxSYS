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

from src.axls_bridge import AxlsBridge
from src.cone_extractor import ConeExtractor
from src.reintegrator import Reintegrator
from src.sdc_generator import SdcGenerator
from src.verifier import MiterVerifier

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

        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run(self) -> Dict[str, Any]:
        """Execute the end-to-end flow."""
        start_time = time.time()
        logger.info("=== STARTING AXC EDA FLOW ===")
        logger.info("Input Verilog: %s", self.input_verilog)
        logger.info("Output Directory: %s", self.output_dir)

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
            logger.warning("Cone extraction halted with status: %s", cone_result.get("status"))
            return {
                "status": "STOPPED",
                "reason": cone_result.get("status"),
                "details": cone_result,
            }

        relaxed_signals = cone_result.get("relaxed_signals", [])
        primary_metric = relaxed_signals[0]["metric"] if relaxed_signals else "MED"
        primary_bound = float(relaxed_signals[0]["bound"]) if relaxed_signals else 0.05
        primary_lsb = int(relaxed_signals[0]["lsb_width"]) if relaxed_signals else None

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
            num_cycles=self.verify_cycles,
        )
        verify_result = verifier.verify()

        elapsed = time.time() - start_time
        logger.info("=== FLOW FINISHED IN %.2f SECONDS ===", elapsed)

        summary: Dict[str, Any] = {
            "flow_status": "SUCCESS" if verify_result.get("status") == "PASSED" else "VERIFICATION_FAILED",
            "elapsed_seconds": round(elapsed, 2),
            "top_module": cone_result["top_module"],
            "submodule_module": cone_result["submodule_module"],
            "extracted_safe_cells": cone_result["num_safe_cells"],
            "approximation": {
                "metric": primary_metric,
                "bound": primary_bound,
                "measured_error": approx_result.get("measured_error"),
                "pruned_nodes": approx_result.get("pruned_nodes_count"),
                "initial_area": approx_result.get("initial_area"),
                "approx_area": approx_result.get("final_area"),
                "area_savings_percent": approx_result.get("area_savings_percent"),
            },
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
    parser.add_argument("--clk", default="clk", help="Clock port name")
    parser.add_argument("--period", type=float, default=10.0, help="Clock period in ns")
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
