"""Automated Miter Verification Harness.

Instantiates the golden exact RTL and the final approximated gate netlist
side-by-side in an automated Miter testbench, compiling and executing with Icarus Verilog.

Enforces two strict verification invariants:
1. Zero Control Corruption: 100% cycle-exact match on (* axc_precise *) and unannotated outputs.
2. Bounded Error: Measured error metric on (* axc_relax *) signals <= axc_bound.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from pyosys import libyosys as ys

logger = logging.getLogger("verifier")

TECH_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "third_party" / "AxLS" / "templates"
TECH_V_DEFAULT = TECH_TEMPLATES_DIR / "NanGate15nm.v"


class MiterVerifier:
    """Generates and executes comparison miter testbenches for approximate hardware."""

    def __init__(
        self,
        exact_vlog: str | Path,
        approx_vlog: str | Path,
        meta_json: str | Path,
        tech: str = "NanGate15nm",
        tech_vlog: Optional[str | Path] = None,
        num_cycles: int = 500,
    ):
        self.exact_vlog = Path(exact_vlog).resolve()
        self.approx_vlog = Path(approx_vlog).resolve()
        self.meta_json = Path(meta_json).resolve()

        if tech_vlog:
            self.tech_vlog = Path(tech_vlog).resolve()
        else:
            tech_as_path = Path(tech)
            if tech_as_path.is_file():
                self.tech_vlog = tech_as_path.resolve()
            else:
                candidate = TECH_TEMPLATES_DIR / f"{tech}.v"
                self.tech_vlog = candidate.resolve() if candidate.is_file() else TECH_V_DEFAULT

        if not self.tech_vlog.exists():
            logger.warning("Technology Verilog file not found: %s", self.tech_vlog)

        self.num_cycles = num_cycles

        with open(self.meta_json, "r", encoding="utf-8") as f:
            self.meta = json.load(f)

        self.top_module = self.meta.get("top_module", "top")

    def _prepare_approx_netlist(self, work_dir: Path) -> Path:
        """Rename approximate top module to avoid collision in iverilog."""
        renamed_vlog = work_dir / f"{self.top_module}_approx.v"
        design = ys.Design()
        tech_cmd = f"read_verilog -overwrite {self.tech_vlog}; " if self.tech_vlog.exists() else ""
        cmd = (
            f"read_verilog -overwrite {self.approx_vlog}; {tech_cmd}"
            f"hierarchy -check -top {self.top_module}; "
            f"rename {self.top_module} {self.top_module}_approx; "
            f"write_verilog {renamed_vlog}"
        )
        ys.run_pass(cmd, design)
        return renamed_vlog

    def _inspect_module_ports(self) -> Dict[str, Any]:
        """Inspect input and output ports of top module."""
        design = ys.Design()
        ys.run_pass(f"read_verilog -sv {self.exact_vlog}; hierarchy -check -auto-top; proc; opt_clean", design)
        top = design.top_module()
        inputs = []
        outputs = []
        for wname_id, wire in top.wires_.items():
            name = wname_id.str().lstrip("\\")
            if wire.port_input:
                inputs.append({"name": name, "width": wire.width, "is_signed": bool(wire.is_signed)})
            if wire.port_output:
                outputs.append({"name": name, "width": wire.width, "is_signed": bool(wire.is_signed)})
        return {"inputs": inputs, "outputs": outputs}

    def generate_miter_tb(self, work_dir: Path, ports_info: Dict[str, Any]) -> Path:
        """Generate self-checking Verilog miter testbench."""
        tb_path = work_dir / "tb_miter.v"

        inputs = ports_info["inputs"]
        outputs = ports_info["outputs"]

        relaxed_names = {s["wire"]: s for s in self.meta.get("relaxed_signals", [])}

        lines: List[str] = [
            "`timescale 1ns / 1ps",
            "",
            "module tb_miter;",
            "  reg clk;",
            "  reg rst_n;",
        ]

        # Declare input regs
        clk_inputs = {"clk", "clock"}
        rst_inputs = {"rst", "rst_n", "reset", "reset_n"}

        for inp in inputs:
            name = inp["name"]
            width = inp["width"]
            is_signed = inp.get("is_signed", False)
            if name not in clk_inputs and name not in rst_inputs:
                signed_str = "signed " if is_signed else ""
                range_str = f"[{width-1}:0] " if width > 1 else ""
                lines.append(f"  reg {signed_str}{range_str}{name};")

        # Declare output wires for exact and approx
        for out in outputs:
            name = out["name"]
            width = out["width"]
            is_signed = out.get("is_signed", False)
            signed_str = "signed " if is_signed else ""
            range_str = f"[{width-1}:0] " if width > 1 else ""
            lines.append(f"  wire {signed_str}{range_str}{name}_exact;")
            lines.append(f"  wire {signed_str}{range_str}{name}_approx;")

        lines.extend([
            "",
            "  integer cycle_count = 0;",
            "  integer control_errors = 0;",
            "  real total_error_distance = 0.0;",
            "  real max_error_distance = 0.0;",
            "  real total_squared_error = 0.0;",
            "  real total_rel_error = 0.0;",
            "  integer error_cycle_count = 0;",
            "  real current_error = 0.0;",
            "  real diff_val = 0.0;",
        ])

        for sig_name in relaxed_names:
            lines.extend([
                f"  real total_error_distance_{sig_name} = 0.0;",
                f"  real max_error_distance_{sig_name} = 0.0;",
                f"  real total_squared_error_{sig_name} = 0.0;",
                f"  real total_rel_error_{sig_name} = 0.0;",
                f"  integer error_cycle_count_{sig_name} = 0;",
            ])

        lines.extend([
            "",
            "  // Clock generation",
            "  always #5 clk = ~clk;",
            "",
            f"  // Golden reference: {self.top_module}",
            f"  {self.top_module} uut_exact (",
        ])

        exact_conns = []
        for inp in inputs:
            name = inp["name"]
            exact_conns.append(f"    .{name}({name})")
        for out in outputs:
            name = out["name"]
            exact_conns.append(f"    .{name}({name}_exact)")
        lines.append(",\n".join(exact_conns))
        lines.extend([
            "  );",
            "",
            f"  // Approximated implementation: {self.top_module}_approx",
            f"  {self.top_module}_approx uut_approx (",
        ])

        approx_conns = []
        for inp in inputs:
            name = inp["name"]
            approx_conns.append(f"    .{name}({name})")
        for out in outputs:
            name = out["name"]
            approx_conns.append(f"    .{name}({name}_approx)")
        lines.append(",\n".join(approx_conns))
        lines.extend([
            "  );",
            "",
            "  initial begin",
            "    clk = 0;",
            "    rst_n = 0;",
        ])

        for inp in inputs:
            name = inp["name"]
            if name not in clk_inputs and name not in rst_inputs:
                lines.append(f"    {name} = 0;")

        lines.extend([
            "    #20 rst_n = 1;",
            "  end",
            "",
            "  always @(posedge clk) begin",
            "    if (rst_n) begin",
            "      cycle_count <= cycle_count + 1;",
            "",
            "      // 1. Verify 100% Precise Control Integrity",
        ])

        for out in outputs:
            name = out["name"]
            if name not in relaxed_names:
                lines.extend([
                    f"      if ({name}_exact !== {name}_approx) begin",
                    f"        $display(\"[ERROR: CYCLE %0d] Precise output mismatch on '{name}': exact=%h approx=%h\", cycle_count, {name}_exact, {name}_approx);",
                    "        control_errors <= control_errors + 1;",
                    "      end",
                ])

        lines.extend([
            "",
            "      // 2. Measure Datapath Approximate Error",
        ])

        for out in outputs:
            name = out["name"]
            if name in relaxed_names:
                lines.extend([
                    f"      if ({name}_exact >= {name}_approx) begin",
                    f"        diff_val = {name}_exact - {name}_approx;",
                    "      end else begin",
                    f"        diff_val = {name}_approx - {name}_exact;",
                    "      end",
                    f"      total_error_distance_{name} = total_error_distance_{name} + diff_val;",
                    f"      if (diff_val > max_error_distance_{name}) max_error_distance_{name} = diff_val;",
                    f"      if (diff_val > 0.0) error_cycle_count_{name} = error_cycle_count_{name} + 1;",
                    f"      total_squared_error_{name} = total_squared_error_{name} + (diff_val * diff_val);",
                    f"      if ({name}_exact != 0) begin",
                    f"        total_rel_error_{name} = total_rel_error_{name} + (diff_val / ({name}_exact > 0 ? {name}_exact : -{name}_exact));",
                    "      end",
                    "      total_error_distance = total_error_distance + diff_val;",
                    "      if (diff_val > max_error_distance) max_error_distance = diff_val;",
                    "      if (diff_val > 0.0) error_cycle_count = error_cycle_count + 1;",
                    "      total_squared_error = total_squared_error + (diff_val * diff_val);",
                    f"      if ({name}_exact != 0) begin",
                    f"        total_rel_error = total_rel_error + (diff_val / ({name}_exact > 0 ? {name}_exact : -{name}_exact));",
                    "      end",
                ])

        lines.extend([
            "",
            "      // Random stimulus for next cycle",
        ])

        for inp in inputs:
            name = inp["name"]
            width = inp["width"]
            if name not in clk_inputs and name not in rst_inputs:
                lines.append(f"      {name} <= $urandom;")

        lines.extend([
            f"      if (cycle_count >= {self.num_cycles}) begin",
            "        $display(\"--- VERIFICATION SUMMARY ---\");",
            "        $display(\"Simulated cycles: %0d\", cycle_count);",
            "        $display(\"Control corruption errors: %0d\", control_errors);",
            "        $display(\"Mean Error Distance (MED): %f\", total_error_distance / cycle_count);",
            "        $display(\"Worst Case Error (WCE): %f\", max_error_distance);",
            "        $display(\"Error Rate (ER): %f\", error_cycle_count * 1.0 / cycle_count);",
            "        $display(\"Mean Squared Error (MSED): %f\", total_squared_error / cycle_count);",
            "        $display(\"Mean Relative Error (MRED): %f\", total_rel_error / cycle_count);",
        ])

        for sig_name in relaxed_names:
            lines.extend([
                f"        $display(\"Signal {sig_name} Mean Error Distance (MED): %f\", total_error_distance_{sig_name} / cycle_count);",
                f"        $display(\"Signal {sig_name} Worst Case Error (WCE): %f\", max_error_distance_{sig_name});",
                f"        $display(\"Signal {sig_name} Error Rate (ER): %f\", error_cycle_count_{sig_name} * 1.0 / cycle_count);",
                f"        $display(\"Signal {sig_name} Mean Squared Error (MSED): %f\", total_squared_error_{sig_name} / cycle_count);",
                f"        $display(\"Signal {sig_name} Mean Relative Error (MRED): %f\", total_rel_error_{sig_name} / cycle_count);",
            ])

        lines.extend([
            "        if (control_errors > 0) begin",
            "          $display(\"RESULT: FAILED_CONTROL_CORRUPTION\");",
            "          $finish(1);",
            "        end else begin",
            "          $display(\"RESULT: SUCCESS_CONTROL_INTACT\");",
            "          $finish(0);",
            "        end",
            "      end",
            "    end",
            "  end",
            "endmodule",
        ])

        tb_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return tb_path

    def verify(self) -> Dict[str, Any]:
        """Compile and execute Miter verification harness."""
        with tempfile.TemporaryDirectory(prefix="miter_run_") as tmp_dir:
            work_dir = Path(tmp_dir).resolve()

            # 1. Rename approximate module to avoid collision in iverilog
            approx_renamed = self._prepare_approx_netlist(work_dir)

            # 2. Inspect ports
            ports_info = self._inspect_module_ports()

            # 3. Generate testbench
            tb_path = self.generate_miter_tb(work_dir, ports_info)

            # 4. Compile with iverilog (try without tech_vlog first to avoid duplicate definitions)
            sim_vvp = work_dir / "sim.vvp"
            compile_cmd = [
                "iverilog", "-g2012", "-o", str(sim_vvp),
                str(tb_path),
                str(self.exact_vlog),
                str(approx_renamed),
            ]

            logger.info("Compiling Miter: %s", " ".join(compile_cmd))
            try:
                proc_comp = subprocess.run(compile_cmd, capture_output=True, text=True, timeout=120)
                if proc_comp.returncode != 0 and self.tech_vlog.exists():
                    compile_cmd_tech = compile_cmd + [str(self.tech_vlog)]
                    proc_comp_tech = subprocess.run(compile_cmd_tech, capture_output=True, text=True, timeout=120)
                    if proc_comp_tech.returncode == 0:
                        proc_comp = proc_comp_tech
            except subprocess.TimeoutExpired:
                logger.error("Miter compilation timed out after 120s")
                return {
                    "status": "TIMEOUT",
                    "stderr": "iverilog compilation timed out after 120 seconds",
                }

            if proc_comp.returncode != 0:
                logger.error("Miter compilation failed: %s", proc_comp.stderr)
                return {
                    "status": "COMPILATION_ERROR",
                    "stderr": proc_comp.stderr,
                }

            # 5. Run simulation with safety timeout
            run_cmd = ["vvp", str(sim_vvp)]
            try:
                proc_run = subprocess.run(run_cmd, capture_output=True, text=True, timeout=120)
            except subprocess.TimeoutExpired:
                logger.error("Miter simulation timed out after 120s")
                return {
                    "status": "TIMEOUT",
                    "stderr": "vvp simulation timed out after 120 seconds",
                }

            stdout = proc_run.stdout
            logger.info("Miter simulation output:\n%s", stdout)

            # Parse results
            control_errors = -1
            m_ctrl = re.search(r"Control corruption errors:\s+(\d+)", stdout)
            if m_ctrl:
                control_errors = int(m_ctrl.group(1))

            med = 0.0
            m_med = re.search(r"Mean Error Distance \(MED\):\s+([\d\.]+)", stdout)
            if m_med:
                med = float(m_med.group(1))

            wce = 0.0
            m_wce = re.search(r"Worst Case Error \(WCE\):\s+([\d\.]+)", stdout)
            if m_wce:
                wce = float(m_wce.group(1))

            er = 0.0
            m_er = re.search(r"Error Rate \(ER\):\s+([\d\.]+)", stdout)
            if m_er:
                er = float(m_er.group(1))

            msed = 0.0
            m_msed = re.search(r"Mean Squared Error \(MSED\):\s+([\d\.]+)", stdout)
            if m_msed:
                msed = float(m_msed.group(1))

            mred = 0.0
            m_mred = re.search(r"Mean Relative Error \(MRED\):\s+([\d\.]+)", stdout)
            if m_mred:
                mred = float(m_mred.group(1))

            control_passed = (control_errors == 0) and ("RESULT: SUCCESS_CONTROL_INTACT" in stdout)

            sig_metrics: Dict[str, Dict[str, float]] = {}
            for sig in self.meta.get("relaxed_signals", []):
                wire = sig.get("wire", "")
                if not wire:
                    continue
                m_s_med = re.search(rf"Signal {re.escape(wire)} Mean Error Distance \(MED\):\s+([\d\.]+)", stdout)
                m_s_wce = re.search(rf"Signal {re.escape(wire)} Worst Case Error \(WCE\):\s+([\d\.]+)", stdout)
                m_s_er = re.search(rf"Signal {re.escape(wire)} Error Rate \(ER\):\s+([\d\.]+)", stdout)
                m_s_msed = re.search(rf"Signal {re.escape(wire)} Mean Squared Error \(MSED\):\s+([\d\.]+)", stdout)
                m_s_mred = re.search(rf"Signal {re.escape(wire)} Mean Relative Error \(MRED\):\s+([\d\.]+)", stdout)
                sig_metrics[wire] = {
                    "MED": float(m_s_med.group(1)) if m_s_med else med,
                    "WCE": float(m_s_wce.group(1)) if m_s_wce else wce,
                    "ER": float(m_s_er.group(1)) if m_s_er else er,
                    "MSED": float(m_s_msed.group(1)) if m_s_msed else msed,
                    "MRED": float(m_s_mred.group(1)) if m_s_mred else mred,
                }

            # Compare against bounds across all declared relaxed signals
            bound_passed = True
            metric_results = []
            for sig in self.meta.get("relaxed_signals", []):
                bound = float(sig.get("bound", 1e9))
                metric = sig.get("metric", "MED").upper()
                wire_name = sig.get("wire", "unknown")

                wire_metrics = sig_metrics.get(wire_name, {})
                if metric in wire_metrics:
                    measured_val = wire_metrics[metric]
                else:
                    logger.error("Unsupported error metric '%s' on signal '%s'", metric, wire_name)
                    bound_passed = False
                    metric_results.append({
                        "wire": wire_name,
                        "metric": metric,
                        "bound": bound,
                        "measured": None,
                        "satisfied": False,
                        "error": f"Unsupported metric: {metric}",
                    })
                    continue

                satisfied = measured_val <= bound
                if not satisfied:
                    bound_passed = False

                metric_results.append({
                    "wire": wire_name,
                    "metric": metric,
                    "bound": bound,
                    "measured": measured_val,
                    "satisfied": satisfied,
                })

            overall_status = "PASSED" if (control_passed and bound_passed) else "FAILED"

            return {
                "status": overall_status,
                "control_integrity": "PASSED" if control_passed else "FAILED",
                "control_errors": control_errors,
                "measured_med": med,
                "measured_wce": wce,
                "measured_er": er,
                "measured_msed": msed,
                "measured_mred": mred,
                "error_bound_satisfied": bound_passed,
                "metric_evaluations": metric_results,
                "simulated_cycles": self.num_cycles,
                "log": stdout,
            }


def main() -> None:
    parser = argparse.ArgumentParser(description="Miter Verification Harness CLI")
    parser.add_argument("--exact", required=True, help="Golden exact RTL Verilog")
    parser.add_argument("--approx", required=True, help="Approximated top netlist Verilog")
    parser.add_argument("--meta", required=True, help="Path to metadata.json")
    parser.add_argument("-t", "--tech", default="NanGate15nm", help="Standard cell library name")
    parser.add_argument("--tech-v", default=None, help="Standard cell library Verilog path")
    parser.add_argument("-n", "--cycles", type=int, default=500, help="Simulation clock cycles")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging")

    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)

    verifier = MiterVerifier(
        exact_vlog=args.exact,
        approx_vlog=args.approx,
        meta_json=args.meta,
        tech=args.tech,
        tech_vlog=args.tech_v,
        num_cycles=args.cycles,
    )
    result = verifier.verify()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
