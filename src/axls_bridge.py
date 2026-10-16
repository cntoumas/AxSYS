"""AxLS Approximation Bridge.

Wraps AxLS (Approximate Logic Synthesis) to optimize extracted combinational cones
subject to IEEE-annotated error metrics and thresholds (MED, MRED, WCE, ER).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

AXLS_DIR = Path(__file__).resolve().parent.parent / "third_party" / "AxLS"
if str(AXLS_DIR) not in sys.path:
    sys.path.insert(0, str(AXLS_DIR))

from circuit import Circuit
from pruning_algorithms.inouts import GetOutputs
from synthesis import resynthesis, ys_get_area

logger = logging.getLogger("axls_bridge")


class AxlsBridge:
    """Bridges extracted RTLIL submodules into the AxLS approximation framework."""

    def __init__(
        self,
        cone_verilog_path: str | Path,
        tech: str = "NanGate15nm",
        samples: int = 500,
        work_dir: Optional[str | Path] = None,
    ):
        self.cone_vlog = Path(cone_verilog_path).resolve()
        self.tech = tech
        self.samples = samples
        self.work_dir = Path(work_dir).resolve() if work_dir else None

    def optimize(
        self,
        metric: str = "med",
        bound: float = 0.05,
        lsb_width: Optional[int] = None,
        out_approx_path: Optional[str | Path] = None,
    ) -> Dict[str, Any]:
        """Iteratively prune the gate-level netlist within the specified error bound."""
        metric_normalized = metric.lower()
        if metric_normalized not in ("med", "mred", "wce", "wcre", "msed", "er"):
            logger.warning("Unrecognized metric '%s', defaulting to 'med'", metric)
            metric_normalized = "med"

        # Use designated or temp directory
        temp_dir_ctx = None
        if self.work_dir is None:
            temp_dir_ctx = tempfile.TemporaryDirectory(prefix="axls_run_")
            run_dir = Path(temp_dir_ctx.name).resolve()
        else:
            run_dir = self.work_dir
            run_dir.mkdir(parents=True, exist_ok=True)

        orig_cwd = os.getcwd()

        try:
            # AxLS assumes filename matches module name inside the file
            content = self.cone_vlog.read_text(encoding="utf-8")
            match = re.search(r"\bmodule\s+(\w+)", content)
            topmodule = match.group(1) if match else self.cone_vlog.stem

            local_cone_v = run_dir / f"{topmodule}.v"
            shutil.copy(self.cone_vlog, local_cone_v)

            # Change cwd so AxLS relative paths work as expected
            os.chdir(run_dir)

            # 1. Initialize AxLS Circuit (maps to NanGate15nm via Yosys)
            circuit = Circuit(str(local_cone_v), self.tech)

            initial_area_val = ys_get_area(circuit.netl_file, self.tech, circuit.topmodule)
            initial_area = float(initial_area_val) if initial_area_val else 0.0
            logger.info("Initial circuit area (%s): %.2f", self.tech, initial_area)

            # 2. Generate simulation vectors & golden testbench
            tb_path = str((run_dir / "tb_cone.v").resolve())
            dataset_path = str((run_dir / "dataset.txt").resolve())
            exact_out_path = str((run_dir / "exact_out.txt").resolve())
            approx_out_path = str((run_dir / "approx_out.txt").resolve())

            circuit.generate_dataset(dataset_path, self.samples)
            circuit.write_tb(tb_path, dataset_path, iterations=self.samples)
            circuit.exact_output(tb_path, exact_out_path)

            # 3. Find candidate nodes to prune using InOuts targeting relaxed outputs
            candidate_outputs: List[str] = []
            if lsb_width is not None and lsb_width > 0:
                # Target output bits [0 .. lsb_width-1]
                for out_sig in circuit.outputs:
                    for bit_idx in range(lsb_width):
                        if f"[{bit_idx}]" in out_sig:
                            candidate_outputs.append(out_sig)
            else:
                candidate_outputs = circuit.outputs

            logger.info("Targeting candidate outputs for pruning: %s", candidate_outputs)

            depricable_nodes = GetOutputs(circuit.netl_root, candidate_outputs)
            candidate_node_names = [n.attrib["var"] for n in depricable_nodes]
            logger.info("Found %d candidate nodes for pruning", len(candidate_node_names))

            # 4. Greedy Pruning Loop
            deleted_nodes: List[str] = []
            current_error: float = 0.0

            for node_name in candidate_node_names:
                circuit.delete(node_name)
                try:
                    err = circuit.simulate_and_compute_error(
                        tb_path, metric_normalized, exact_out_path, approx_out_path
                    )
                except Exception as exc:
                    logger.debug("Simulation failed on node %s: %s", node_name, exc)
                    circuit.undodelete(node_name)
                    continue

                if err <= bound:
                    # Accept deletion
                    deleted_nodes.append(node_name)
                    current_error = float(err)
                    logger.info("Pruned node %s -> %s error: %.6f <= %.6f", node_name, metric_normalized, err, bound)
                else:
                    # Reject deletion
                    circuit.undodelete(node_name)

            logger.info("Pruning complete. Total nodes pruned: %d, Final %s error: %.6f", len(deleted_nodes), metric_normalized, current_error)

            # 5. Export and resynthesize the approximated netlist
            raw_approx_v = circuit.write_to_disk("approx_raw")
            clean_netlist_path = resynthesis(raw_approx_v, self.tech, circuit.topmodule)
            final_area_val = ys_get_area(clean_netlist_path, self.tech, circuit.topmodule)
            final_area = float(final_area_val) if final_area_val else 0.0

            area_savings = 0.0
            if initial_area > 0:
                area_savings = ((initial_area - final_area) / initial_area) * 100.0

            logger.info(
                "Area results: Initial=%.2f, Approx=%.2f (%.2f%% savings)",
                initial_area, final_area, area_savings
            )

            # 6. Copy to destination if specified
            final_dest = clean_netlist_path
            if out_approx_path:
                out_p = Path(out_approx_path).resolve()
                out_p.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(clean_netlist_path, out_p)
                final_dest = str(out_p)

            return {
                "status": "SUCCESS",
                "topmodule": topmodule,
                "metric": metric_normalized,
                "bound": bound,
                "measured_error": current_error,
                "pruned_nodes_count": len(deleted_nodes),
                "pruned_nodes": deleted_nodes,
                "initial_area": initial_area,
                "final_area": final_area,
                "area_savings_percent": round(area_savings, 2),
                "approx_netlist": final_dest,
            }

        finally:
            os.chdir(orig_cwd)
            if temp_dir_ctx:
                temp_dir_ctx.cleanup()


def main() -> None:
    parser = argparse.ArgumentParser(description="AxLS Approximation Bridge CLI")
    parser.add_argument("-i", "--input", required=True, help="Input extracted cone Verilog")
    parser.add_argument("-m", "--metric", default="med", help="Target error metric (med, mred, wce, er)")
    parser.add_argument("-b", "--bound", type=float, default=0.05, help="Maximum error bound")
    parser.add_argument("--lsb-width", type=int, default=None, help="LSB bit-width to restrict pruning")
    parser.add_argument("-t", "--tech", default="NanGate15nm", help="Standard cell tech library")
    parser.add_argument("-s", "--samples", type=int, default=500, help="Simulation samples")
    parser.add_argument("-o", "--output", default=None, help="Output approximated Verilog path")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging")

    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)

    bridge = AxlsBridge(
        cone_verilog_path=args.input,
        tech=args.tech,
        samples=args.samples,
    )
    result = bridge.optimize(
        metric=args.metric,
        bound=args.bound,
        lsb_width=args.lsb_width,
        out_approx_path=args.output,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
