"""AxLS Approximation Bridge.

Wraps AxLS (Approximate Logic Synthesis) to optimize extracted combinational cones
subject to IEEE-annotated error metrics and thresholds (MED, MRED, WCE, ER).
Supports multiple logic approximation backends (InOuts, ProbPrun, DecisionTree)
and an automated tournament mode (axc_method = "auto") selecting the champion
netlist minimizing NanGate15nm standard-cell gate area.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from sklearn.tree import DecisionTreeClassifier

AXLS_DIR = Path(__file__).resolve().parent.parent / "third_party" / "AxLS"
if str(AXLS_DIR) not in sys.path:
    sys.path.insert(0, str(AXLS_DIR))

from circuit import Circuit
from circuiterror import compute_error
from pruning_algorithms.inouts import GetOutputs
from pruning_algorithms.probprun import GetOneNode
from synthesis import resynthesis, ys_get_area
from utils import read_dataset

from axsys.fpga_estimator import FpgaEstimator

logger = logging.getLogger("axls_bridge")


def parse_vcd_duty_cycle(vcd_path: Path, target_module: str) -> Dict[str, Tuple[int, int]]:
    """Parse VCD and return for each wire in target_module: (t0_pct, t1_pct)."""
    var_map: Dict[str, str] = {}
    current_scope: List[str] = []

    if not vcd_path.exists():
        return {}

    with open(vcd_path, "r", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith("$scope"):
                parts = line.split()
                if len(parts) >= 3:
                    current_scope.append(parts[2])
            elif line.startswith("$upscope"):
                if current_scope:
                    current_scope.pop()
            elif line.startswith("$var"):
                parts = line.split()
                if len(parts) >= 5:
                    alias = parts[3]
                    var_name = parts[4]
                    if target_module in ".".join(current_scope):
                        var_map[alias] = var_name
            elif line.startswith("$enddefinitions"):
                break

        cur_time = 0
        last_time: Dict[str, int] = defaultdict(int)
        cur_val: Dict[str, str] = defaultdict(lambda: "0")
        time_1: Dict[str, int] = defaultdict(int)
        time_0: Dict[str, int] = defaultdict(int)

        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith("#"):
                try:
                    cur_time = int(line[1:])
                except ValueError:
                    pass
            elif line[0] in ("0", "1"):
                val = line[0]
                alias = line[1:]
                if alias in var_map:
                    dt = cur_time - last_time[alias]
                    if cur_val[alias] == "1":
                        time_1[alias] += dt
                    elif cur_val[alias] == "0":
                        time_0[alias] += dt
                    cur_val[alias] = val
                    last_time[alias] = cur_time
            elif line.startswith("b"):
                parts = line.split()
                if len(parts) >= 2:
                    val = parts[0][1:]
                    alias = parts[1]
                    if alias in var_map:
                        dt = cur_time - last_time[alias]
                        bit0 = val[-1] if val else "0"
                        if cur_val[alias] == "1":
                            time_1[alias] += dt
                        elif cur_val[alias] == "0":
                            time_0[alias] += dt
                        cur_val[alias] = bit0
                        last_time[alias] = cur_time

        for alias in var_map:
            dt = cur_time - last_time[alias]
            if cur_val[alias] == "1":
                time_1[alias] += dt
            elif cur_val[alias] == "0":
                time_0[alias] += dt

    result: Dict[str, Tuple[int, int]] = {}
    for alias, name in var_map.items():
        tot = time_1[alias] + time_0[alias]
        t1 = int(round((time_1[alias] / tot) * 100)) if tot > 0 else 50
        t0 = 100 - t1
        result[name] = (t0, t1)
    return result


def tree_to_verilog_expr(tree: Any, node_id: int, input_names: List[str], classes: np.ndarray) -> str:
    """Recursively convert scikit-learn decision tree node to robust synthesizable Verilog expression."""
    if tree.children_left[node_id] == -1 and tree.children_right[node_id] == -1:
        class_idx = int(np.argmax(tree.value[node_id][0]))
        pred = classes[class_idx]
        return "1'b1" if pred == 1 else "1'b0"

    feat = tree.feature[node_id]
    inp = input_names[feat]
    neg_inp = f"(!{inp})"

    left = tree_to_verilog_expr(tree, tree.children_left[node_id], input_names, classes)
    right = tree_to_verilog_expr(tree, tree.children_right[node_id], input_names, classes)

    if left == "1'b0" and right == "1'b0":
        return "1'b0"
    if left == "1'b1" and right == "1'b1":
        return "1'b1"
    if left == "1'b0" and right == "1'b1":
        return inp
    if left == "1'b1" and right == "1'b0":
        return neg_inp
    if left == "1'b0":
        return f"({inp} & {right})"
    if right == "1'b0":
        return f"({neg_inp} & {left})"
    if left == "1'b1":
        return f"({neg_inp} | {right})"
    if right == "1'b1":
        return f"({inp} | {left})"
    return f"(({neg_inp} & {left}) | ({inp} & {right}))"


class AxlsBridge:
    """Bridges extracted RTLIL submodules into the AxLS approximation framework."""

    def __init__(
        self,
        cone_verilog_path: str | Path,
        tech: str = "NanGate15nm",
        samples: int = 500,
        work_dir: Optional[str | Path] = None,
        trace_hex_path: Optional[str | Path] = None,
        target: str = "asic",
        fpga_family: str = "xc7",
        fpga_device: str = "xc7a35t",
        fpga_nodsp: bool = True,
    ):
        self.cone_vlog = Path(cone_verilog_path).resolve()
        self.tech = tech
        self.samples = samples
        self.work_dir = Path(work_dir).resolve() if work_dir else None
        self.trace_hex_path = Path(trace_hex_path).resolve() if trace_hex_path else None
        self.target = target.lower()
        self.fpga_family = fpga_family.lower()
        self.fpga_device = fpga_device.lower()
        self.fpga_nodsp = fpga_nodsp

        # Auto-detect FPGA from tech string if applicable
        if self.tech.lower() in ("xc7", "artix7", "xilinx"):
            self.target = "fpga"
            self.fpga_family = "xc7"

    def _evaluate_netlist_cost(self, netlist_path: str | Path, topmodule: str) -> float:
        """Evaluate circuit cost: Logic Cells (LCs) for FPGA, or standard-cell gate area (um^2) for ASIC."""
        if self.target == "fpga":
            try:
                estimator = FpgaEstimator(family=self.fpga_family, device=self.fpga_device, nodsp=self.fpga_nodsp)
                res = estimator.evaluate_netlist(netlist_path, top_module=topmodule)
                return float(res["estimated_lcs"])
            except Exception as e:
                logger.warning("FPGA evaluation failed on %s: %s", netlist_path, e)
                return 999999.0
        else:
            area_val = ys_get_area(str(netlist_path), self.tech, topmodule)
            return float(area_val) if area_val else 0.0

    def optimize(
        self,
        metric: str = "med",
        bound: float = 0.05,
        lsb_width: Optional[int] = None,
        method: str = "auto",
        out_approx_path: Optional[str | Path] = None,
        trace_hex_path: Optional[str | Path] = None,
        isolated: bool = True,
    ) -> Dict[str, Any]:
        """Iteratively optimize or prune the gate-level netlist within the specified error bound.

        When isolated=True, runs in an isolated subprocess to protect the calling process's
        working directory from os.chdir() and ensure thread safety.
        """
        eff_trace = trace_hex_path or self.trace_hex_path
        if not isolated:
            return self._optimize_direct(
                metric=metric,
                bound=bound,
                lsb_width=lsb_width,
                method=method,
                out_approx_path=out_approx_path,
                trace_hex_path=eff_trace,
            )

        # Isolated execution mode
        run_dir = self.work_dir
        temp_dir_ctx = None
        if run_dir is None:
            temp_dir_ctx = tempfile.TemporaryDirectory(prefix="axls_run_")
            run_dir = Path(temp_dir_ctx.name).resolve()
        else:
            run_dir.mkdir(parents=True, exist_ok=True)

        target_out = Path(out_approx_path).resolve() if out_approx_path else (run_dir / "approx_cone.v")
        target_out.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            sys.executable,
            "-m", "axsys.axls_bridge",
            "-i", str(self.cone_vlog),
            "-m", metric,
            "-b", str(bound),
            "-t", str(self.tech),
            "-s", str(self.samples),
            "-a", str(method),
            "--work-dir", str(run_dir),
            "-o", str(target_out),
            "--target", self.target,
            "--fpga-family", self.fpga_family,
            "--fpga-device", self.fpga_device,
        ]
        if not self.fpga_nodsp:
            cmd.append("--allow-dsp")
        if lsb_width is not None:
            cmd.extend(["--lsb-width", str(lsb_width)])
        if eff_trace:
            cmd.extend(["--trace-hex", str(eff_trace)])

        repo_root = str(Path(__file__).resolve().parent.parent)
        env = os.environ.copy()
        env["PYTHONPATH"] = f"{repo_root}:{env.get('PYTHONPATH', '')}"

        logger.info("Spawning isolated AxLS worker in %s with method=%s", run_dir, method)
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(run_dir),
                env=env,
                capture_output=True,
                text=True,
                timeout=300,
            )
            if proc.returncode != 0:
                logger.error("AxLS worker failed (exit %d):\n%s", proc.returncode, proc.stderr)
                return {
                    "status": "FAILED",
                    "error": proc.stderr or proc.stdout,
                }

            lines = [line for line in proc.stdout.strip().splitlines() if line.strip()]
            for start_idx in range(len(lines)):
                try:
                    result = json.loads("\n".join(lines[start_idx:]))
                    return result
                except json.JSONDecodeError:
                    continue

            logger.error("Could not parse JSON output from AxLS worker:\n%s", proc.stdout)
            return {"status": "FAILED", "error": "Invalid JSON response from AxLS worker"}
        except subprocess.TimeoutExpired:
            logger.error("AxLS optimization timed out after 300s")
            return {"status": "TIMEOUT", "error": "AxLS optimization timed out after 300s"}
        finally:
            if temp_dir_ctx:
                temp_dir_ctx.cleanup()

    def _optimize_direct(
        self,
        metric: str = "med",
        bound: float = 0.05,
        lsb_width: Optional[int] = None,
        method: str = "auto",
        out_approx_path: Optional[str | Path] = None,
        trace_hex_path: Optional[str | Path] = None,
    ) -> Dict[str, Any]:
        """Direct AxLS optimization (executed inside worker process)."""
        metric_normalized = metric.lower()
        if metric_normalized not in ("med", "mred", "wce", "wcre", "msed", "er"):
            logger.warning("Unrecognized metric '%s', defaulting to 'med'", metric)
            metric_normalized = "med"

        method_normalized = method.lower()
        if method_normalized not in ("auto", "inouts", "probprun", "decisiontree"):
            logger.warning("Unrecognized method '%s', defaulting to 'auto'", method)
            method_normalized = "auto"

        temp_dir_ctx = None
        if self.work_dir is None:
            temp_dir_ctx = tempfile.TemporaryDirectory(prefix="axls_run_")
            run_dir = Path(temp_dir_ctx.name).resolve()
        else:
            run_dir = self.work_dir
            run_dir.mkdir(parents=True, exist_ok=True)

        orig_cwd = os.getcwd()

        try:
            content = self.cone_vlog.read_text(encoding="utf-8")
            match = re.search(r"\bmodule\s+(\w+)", content)
            topmodule = match.group(1) if match else self.cone_vlog.stem

            local_cone_v = run_dir / f"{topmodule}.v"
            shutil.copy(self.cone_vlog, local_cone_v)

            os.chdir(run_dir)

            synth_tech = "NanGate15nm" if self.tech.lower() in ("xc7", "artix7", "xilinx") else self.tech
            circuit = Circuit(str(local_cone_v), synth_tech)
            initial_area = self._evaluate_netlist_cost(circuit.netl_file, circuit.topmodule)
            metric_label = "Logic Cells" if self.target == "fpga" else f"um^2 ({self.tech})"
            logger.info("Initial circuit cost [%s]: %.2f", metric_label, initial_area)

            tb_path = str((run_dir / "tb_cone.v").resolve())
            dataset_path = str((run_dir / "dataset.txt").resolve())
            exact_out_path = str((run_dir / "exact_out.txt").resolve())
            approx_out_path = str((run_dir / "approx_out.txt").resolve())

            eff_trace = trace_hex_path or self.trace_hex_path
            iterations = self.samples
            if eff_trace and Path(eff_trace).exists():
                logger.info("Using realistic pipeline trace dataset from %s", eff_trace)
                trace_content = Path(eff_trace).read_text(encoding="utf-8")
                lines = [l.strip() for l in trace_content.splitlines() if l.strip()]
                header = None
                data_lines = []
                for line in lines:
                    if line.startswith("#"):
                        header = line.lstrip("#").strip().split()
                    else:
                        data_lines.append(line)

                expected_inputs = []
                for raw_in in circuit.raw_inputs:
                    m = re.search(r" (\S+);", raw_in)
                    if m:
                        expected_inputs.append(m.group(1))

                if header and expected_inputs and set(header) == set(expected_inputs):
                    logger.info("Re-aligning trace columns from %s to expected order %s", header, expected_inputs)
                    realigned = []
                    col_map = {col_name: idx for idx, col_name in enumerate(header)}
                    for dline in data_lines:
                        tokens = dline.split()
                        if len(tokens) == len(header):
                            mapped = [tokens[col_map[inp]] for inp in expected_inputs]
                            realigned.append(" ".join(mapped))
                    data_lines = realigned

                Path(dataset_path).write_text("\n".join(data_lines) + "\n", encoding="utf-8")
                iterations = len(data_lines)
            else:
                circuit.generate_dataset(dataset_path, self.samples)

            circuit.write_tb(tb_path, dataset_path, iterations=iterations, dump_vcd=True)
            circuit.exact_output(tb_path, exact_out_path)

            candidate_outputs: List[str] = []
            if lsb_width is not None and lsb_width > 0:
                for out_sig in circuit.outputs:
                    for bit_idx in range(lsb_width):
                        if f"[{bit_idx}]" in out_sig:
                            candidate_outputs.append(out_sig)
            else:
                candidate_outputs = circuit.outputs

            logger.info("Target candidate outputs for approximation: %s", candidate_outputs)

            if method_normalized == "auto":
                return self._run_tournament(
                    local_cone_v=local_cone_v,
                    circuit=circuit,
                    topmodule=topmodule,
                    run_dir=run_dir,
                    tb_path=tb_path,
                    dataset_path=dataset_path,
                    exact_out_path=exact_out_path,
                    approx_out_path=approx_out_path,
                    metric_normalized=metric_normalized,
                    bound=bound,
                    lsb_width=lsb_width,
                    candidate_outputs=candidate_outputs,
                    initial_area=initial_area,
                    out_approx_path=out_approx_path,
                )
            elif method_normalized == "inouts":
                res = self._run_inouts(
                    local_cone_v=local_cone_v,
                    topmodule=topmodule,
                    run_dir=run_dir,
                    tb_path=tb_path,
                    exact_out_path=exact_out_path,
                    approx_out_path=approx_out_path,
                    metric_normalized=metric_normalized,
                    bound=bound,
                    candidate_outputs=candidate_outputs,
                    initial_area=initial_area,
                )
                return self._finalize_single_result(res, topmodule, metric_normalized, bound, initial_area, out_approx_path)
            elif method_normalized == "probprun":
                res = self._run_probprun(
                    local_cone_v=local_cone_v,
                    topmodule=topmodule,
                    run_dir=run_dir,
                    tb_path=tb_path,
                    exact_out_path=exact_out_path,
                    approx_out_path=approx_out_path,
                    metric_normalized=metric_normalized,
                    bound=bound,
                    initial_area=initial_area,
                )
                return self._finalize_single_result(res, topmodule, metric_normalized, bound, initial_area, out_approx_path)
            elif method_normalized == "decisiontree":
                res = self._run_decisiontree(
                    circuit=circuit,
                    topmodule=topmodule,
                    run_dir=run_dir,
                    tb_path=tb_path,
                    dataset_path=dataset_path,
                    exact_out_path=exact_out_path,
                    approx_out_path=approx_out_path,
                    metric_normalized=metric_normalized,
                    bound=bound,
                    lsb_width=lsb_width,
                    candidate_outputs=candidate_outputs,
                    initial_area=initial_area,
                )
                return self._finalize_single_result(res, topmodule, metric_normalized, bound, initial_area, out_approx_path)
            else:
                raise ValueError(f"Unknown method {method_normalized}")

        finally:
            os.chdir(orig_cwd)
            if temp_dir_ctx:
                temp_dir_ctx.cleanup()

    def _run_inouts(
        self,
        local_cone_v: Path,
        topmodule: str,
        run_dir: Path,
        tb_path: str,
        exact_out_path: str,
        approx_out_path: str,
        metric_normalized: str,
        bound: float,
        candidate_outputs: List[str],
        initial_area: float,
    ) -> Dict[str, Any]:
        """Method 1: InOuts greedy fanin pruning."""
        t_start = time.time()
        logger.info("[InOuts] Starting greedy fanin pruning...")
        synth_tech = "NanGate15nm" if self.tech.lower() in ("xc7", "artix7", "xilinx") else self.tech
        circuit = Circuit(str(local_cone_v), synth_tech)
        depricable_nodes = GetOutputs(circuit.netl_root, candidate_outputs)
        candidate_node_names = [n.attrib["var"] for n in depricable_nodes]
        logger.info("[InOuts] Found %d candidate nodes", len(candidate_node_names))

        deleted_nodes: List[str] = []
        current_error: float = 0.0

        for node_name in candidate_node_names:
            circuit.delete(node_name)
            try:
                err = circuit.simulate_and_compute_error(
                    tb_path, metric_normalized, exact_out_path, approx_out_path
                )
            except Exception as exc:
                circuit.undodelete(node_name)
                continue

            if err <= bound:
                deleted_nodes.append(node_name)
                current_error = float(err)
            else:
                circuit.undodelete(node_name)

        raw_approx_v = circuit.write_to_disk("approx_inouts_raw")
        clean_netlist_path = resynthesis(raw_approx_v, synth_tech, circuit.topmodule)
        final_area = self._evaluate_netlist_cost(clean_netlist_path, circuit.topmodule)

        area_savings = 0.0
        if initial_area > 0:
            area_savings = ((initial_area - final_area) / initial_area) * 100.0

        elapsed = time.time() - t_start
        logger.info(
            "[InOuts] Complete: area=%.2f (%.2f%% savings), error=%.6f, pruned=%d, runtime=%.2fs",
            final_area, area_savings, current_error, len(deleted_nodes), elapsed
        )

        return {
            "method": "inouts",
            "status": "SUCCESS",
            "initial_area": initial_area,
            "final_area": final_area,
            "area_savings_percent": round(area_savings, 2),
            "measured_error": current_error,
            "compliant": bool(current_error <= bound),
            "pruned_nodes_count": len(deleted_nodes),
            "pruned_nodes": deleted_nodes,
            "netlist_path": clean_netlist_path,
            "runtime_s": round(elapsed, 2),
        }

    def _run_probprun(
        self,
        local_cone_v: Path,
        topmodule: str,
        run_dir: Path,
        tb_path: str,
        exact_out_path: str,
        approx_out_path: str,
        metric_normalized: str,
        bound: float,
        initial_area: float,
    ) -> Dict[str, Any]:
        """Method 2: ProbPrun probabilistic signal-activity pruning."""
        t_start = time.time()
        logger.info("[ProbPrun] Starting probabilistic activity pruning...")
        synth_tech = "NanGate15nm" if self.tech.lower() in ("xc7", "artix7", "xilinx") else self.tech
        circuit = Circuit(str(local_cone_v), synth_tech)

        vcd_p = run_dir / f"{topmodule}.vcd"
        duty = parse_vcd_duty_cycle(vcd_p, topmodule)
        logger.info("[ProbPrun] Parsed duty cycle for %d nets from VCD", len(duty))

        for node in circuit.netl_root.findall("./node"):
            out_wire = node.find("output").attrib["wire"]
            clean_w = out_wire.strip("_")
            if out_wire in duty:
                t0, t1 = duty[out_wire]
            elif clean_w in duty:
                t0, t1 = duty[clean_w]
            else:
                t0, t1 = 50, 50
            node.find("output").set("t0", str(t0))
            node.find("output").set("t1", str(t1))

        gen = GetOneNode(circuit.netl_root)
        deleted_nodes: List[str] = []
        current_error: float = 0.0

        for var, const_val, pct in gen:
            circuit.delete(var)
            try:
                err = circuit.simulate_and_compute_error(
                    tb_path, metric_normalized, exact_out_path, approx_out_path
                )
            except Exception as exc:
                circuit.undodelete(var)
                continue

            if err <= bound:
                deleted_nodes.append(var)
                current_error = float(err)
            else:
                circuit.undodelete(var)

        raw_approx_v = circuit.write_to_disk("approx_probprun_raw")
        clean_netlist_path = resynthesis(raw_approx_v, synth_tech, circuit.topmodule)
        final_area = self._evaluate_netlist_cost(clean_netlist_path, circuit.topmodule)

        area_savings = 0.0
        if initial_area > 0:
            area_savings = ((initial_area - final_area) / initial_area) * 100.0

        elapsed = time.time() - t_start
        logger.info(
            "[ProbPrun] Complete: area=%.2f (%.2f%% savings), error=%.6f, pruned=%d, runtime=%.2fs",
            final_area, area_savings, current_error, len(deleted_nodes), elapsed
        )

        return {
            "method": "probprun",
            "status": "SUCCESS",
            "initial_area": initial_area,
            "final_area": final_area,
            "area_savings_percent": round(area_savings, 2),
            "measured_error": current_error,
            "compliant": bool(current_error <= bound),
            "pruned_nodes_count": len(deleted_nodes),
            "pruned_nodes": deleted_nodes,
            "netlist_path": clean_netlist_path,
            "runtime_s": round(elapsed, 2),
        }

    def _run_decisiontree(
        self,
        circuit: Circuit,
        topmodule: str,
        run_dir: Path,
        tb_path: str,
        dataset_path: str,
        exact_out_path: str,
        approx_out_path: str,
        metric_normalized: str,
        bound: float,
        lsb_width: Optional[int],
        candidate_outputs: List[str],
        initial_area: float,
    ) -> Dict[str, Any]:
        """Method 3: Decision Tree ML-driven boolean function rewriting."""
        t_start = time.time()
        logger.info("[DecisionTree] Starting decision tree approximation search...")

        try:
            # Parse raw integer dataset and filter out empty lines from trailing newlines
            raw_X_lines = read_dataset(dataset_path, 16)
            raw_y_lines = read_dataset(exact_out_path, 10)
            X_clean = [r for r in raw_X_lines if len(r) > 0]
            y_clean = [r for r in raw_y_lines if len(r) > 0]
            min_rows = min(len(X_clean), len(y_clean))
            X_clean = X_clean[:min_rows]
            y_clean = y_clean[:min_rows]

            # Extract bit widths for input ports
            in_port_widths: List[Tuple[str, int]] = []
            for raw_in in circuit.raw_inputs:
                m_width = re.search(r"\[(\d+):0\]\s*(\w+)", raw_in)
                if m_width:
                    msb = int(m_width.group(1))
                    name = m_width.group(2)
                    in_port_widths.append((name, msb + 1))
                else:
                    m_single = re.search(r"input\s+(?:wire\s+|signed\s+)?(\w+)", raw_in)
                    if m_single:
                        in_port_widths.append((m_single.group(1), 1))

            # Extract bit widths for output ports
            out_port_widths: List[Tuple[str, int]] = []
            for raw_out in circuit.raw_outputs:
                m_width = re.search(r"\[(\d+):0\]\s*(\w+)", raw_out)
                if m_width:
                    msb = int(m_width.group(1))
                    name = m_width.group(2)
                    out_port_widths.append((name, msb + 1))
                else:
                    m_single = re.search(r"output\s+(?:wire\s+|reg\s+|signed\s+)?(\w+)", raw_out)
                    if m_single:
                        out_port_widths.append((m_single.group(1), 1))

            expected_in_bits = sum(w for _, w in in_port_widths)
            expected_out_bits = sum(w for _, w in out_port_widths)

            # Convert to bit-level matrices
            valid_X = []
            valid_y = []
            for r_x, r_y in zip(X_clean, y_clean):
                row_x_bits = []
                for val, (pname, width) in zip(r_x, in_port_widths):
                    for s in range(width - 1, -1, -1):
                        row_x_bits.append((val >> s) & 1)

                row_y_bits = []
                for val, (pname, width) in zip(r_y, out_port_widths):
                    for s in range(width - 1, -1, -1):
                        row_y_bits.append((val >> s) & 1)

                if (not expected_in_bits or len(row_x_bits) == expected_in_bits) and \
                   (not expected_out_bits or len(row_y_bits) == expected_out_bits):
                    valid_X.append(row_x_bits)
                    valid_y.append(row_y_bits)

            X_bin = np.array(valid_X, dtype=np.uint8)
            y_bin = np.array(valid_y, dtype=np.uint8)

            input_bit_names = circuit.inputs
            output_bit_names = circuit.outputs

            # Evaluate depth sweep (depths 2, 4)
            depth_candidates = [2, 4]
            best_cand: Optional[Dict[str, Any]] = None

            synth_tech = "NanGate15nm" if self.tech.lower() in ("xc7", "artix7", "xilinx") else self.tech
            tech_vlog = str(Path(__file__).resolve().parent.parent / "third_party" / "AxLS" / "templates" / f"{synth_tech}.v")

            for depth in depth_candidates:
                verilog_lines = [
                    f"module {topmodule} ({', '.join(circuit.raw_parameters.split(','))});"
                ]
                for raw_in in circuit.raw_inputs:
                    verilog_lines.append(f"    {raw_in}")
                for raw_out in circuit.raw_outputs:
                    verilog_lines.append(f"    {raw_out}")

                for col_idx, out_name in enumerate(output_bit_names):
                    # Check if output is a candidate for relaxation
                    is_cand = (out_name in candidate_outputs)
                    tree_depth = depth if is_cand else 8
                    clf = DecisionTreeClassifier(max_depth=tree_depth)
                    clf.fit(X_bin, y_bin[:, col_idx])
                    expr = tree_to_verilog_expr(clf.tree_, 0, input_bit_names, clf.classes_)
                    verilog_lines.append(f"    assign {out_name} = {expr};")

                verilog_lines.append("endmodule")

                dt_vlog = run_dir / f"dt_depth_{depth}.v"
                dt_vlog.write_text("\n".join(verilog_lines) + "\n", encoding="utf-8")

                clean_v = resynthesis(str(dt_vlog), synth_tech, topmodule)
                sim_bin = str((run_dir / f"sim_dt_{depth}").resolve())

                # Simulate netlist with iverilog
                compile_cmd = ["iverilog", "-o", sim_bin, tb_path, clean_v, tech_vlog]
                proc_c = subprocess.run(compile_cmd, cwd=str(run_dir), capture_output=True, text=True)
                if proc_c.returncode != 0:
                    continue

                proc_r = subprocess.run([sim_bin], cwd=str(run_dir), capture_output=True, text=True)
                if proc_r.returncode != 0:
                    continue

                sim_out_txt = run_dir / "output.txt"
                if sim_out_txt.exists():
                    shutil.copy(sim_out_txt, approx_out_path)
                elif not Path(approx_out_path).exists():
                    continue

                err = compute_error(metric_normalized, exact_out_path, approx_out_path)
                area = self._evaluate_netlist_cost(clean_v, topmodule)

                cand_info = {
                    "depth": depth,
                    "measured_error": float(err),
                    "final_area": area,
                    "netlist_path": clean_v,
                    "compliant": bool(err <= bound),
                }

                if cand_info["compliant"]:
                    if best_cand is None or cand_info["final_area"] < best_cand["final_area"]:
                        best_cand = cand_info
                elif best_cand is None:
                    best_cand = cand_info

            elapsed = time.time() - t_start

            if best_cand:
                area_savings = 0.0
                if initial_area > 0:
                    area_savings = ((initial_area - best_cand["final_area"]) / initial_area) * 100.0

                logger.info(
                    "[DecisionTree] Best depth=%d: area=%.2f (%.2f%% savings), error=%.6f, compliant=%s",
                    best_cand.get("depth", 0), best_cand["final_area"], area_savings, best_cand["measured_error"], best_cand["compliant"]
                )

                return {
                    "method": "decisiontree",
                    "status": "SUCCESS",
                    "initial_area": initial_area,
                    "final_area": best_cand["final_area"],
                    "area_savings_percent": round(area_savings, 2),
                    "measured_error": best_cand["measured_error"],
                    "compliant": best_cand["compliant"],
                    "best_depth": best_cand.get("depth"),
                    "netlist_path": best_cand["netlist_path"],
                    "runtime_s": round(elapsed, 2),
                }

        except Exception as exc:
            logger.warning("[DecisionTree] Exception during synthesis: %s", exc)

        elapsed = time.time() - t_start
        return {
            "method": "decisiontree",
            "status": "FAILED",
            "initial_area": initial_area,
            "final_area": initial_area,
            "area_savings_percent": 0.0,
            "measured_error": 999999.0,
            "compliant": False,
            "runtime_s": round(elapsed, 2),
        }

    def _run_tournament(
        self,
        local_cone_v: Path,
        circuit: Circuit,
        topmodule: str,
        run_dir: Path,
        tb_path: str,
        dataset_path: str,
        exact_out_path: str,
        approx_out_path: str,
        metric_normalized: str,
        bound: float,
        lsb_width: Optional[int],
        candidate_outputs: List[str],
        initial_area: float,
        out_approx_path: Optional[str | Path],
    ) -> Dict[str, Any]:
        """Tournament Mode: Run all candidate methods in parallel, rank on leaderboard, and select minimum-area netlist."""
        logger.info("=== STARTING BACKEND TOURNAMENT (axc_method = 'auto' - PARALLEL EXECUTION) ===")
        t_start = time.time()

        methods = ["inouts", "probprun", "decisiontree"]
        workers: Dict[str, subprocess.Popen] = {}
        repo_root = str(Path(__file__).resolve().parent.parent)
        env = os.environ.copy()
        env["PYTHONPATH"] = f"{repo_root}:{env.get('PYTHONPATH', '')}"

        eff_trace = self.trace_hex_path

        # Launch all 3 candidate methods in parallel subprocesses
        for m in methods:
            m_dir = run_dir / f"tourn_{m}"
            m_dir.mkdir(parents=True, exist_ok=True)
            cmd = [
                sys.executable,
                "-m", "axsys.axls_bridge",
                "-i", str(self.cone_vlog),
                "-m", metric_normalized,
                "-b", str(bound),
                "-t", str(self.tech),
                "-s", str(self.samples),
                "-a", m,
                "--work-dir", str(m_dir),
                "--target", self.target,
                "--fpga-family", self.fpga_family,
                "--fpga-device", self.fpga_device,
            ]
            if not self.fpga_nodsp:
                cmd.append("--allow-dsp")
            if lsb_width is not None:
                cmd.extend(["--lsb-width", str(lsb_width)])
            if eff_trace:
                cmd.extend(["--trace-hex", str(eff_trace)])

            logger.info("Launching parallel tournament worker for method: %s", m)
            log_path = m_dir / "worker.log"
            log_f = open(log_path, "w", encoding="utf-8")
            workers[m] = (subprocess.Popen(
                cmd,
                cwd=str(m_dir),
                env=env,
                stdout=log_f,
                stderr=subprocess.STDOUT,
            ), log_f, log_path)

        leaderboard: List[Dict[str, Any]] = []
        for m in methods:
            proc, log_f, log_path = workers[m]
            try:
                proc.wait(timeout=300)
            except subprocess.TimeoutExpired:
                logger.warning("Tournament worker for %s timed out after 300s", m)
                proc.kill()
                proc.wait()
            finally:
                try:
                    log_f.close()
                except Exception:
                    pass

            content = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
            parsed_res: Optional[Dict[str, Any]] = None
            if proc.returncode == 0:
                # Quickly find the JSON object emitted at the end of the log
                cand_idx = content.rfind("\n{\n")
                if cand_idx == -1:
                    cand_idx = content.rfind("{\n")
                if cand_idx != -1:
                    try:
                        parsed_res = json.loads(content[cand_idx:].strip())
                    except json.JSONDecodeError:
                        pass

                if not parsed_res:
                    tail_lines = content.strip().splitlines()[-100:]
                    for s_idx in range(len(tail_lines)):
                        try:
                            parsed_res = json.loads("\n".join(tail_lines[s_idx:]))
                            break
                        except json.JSONDecodeError:
                            continue

            if parsed_res and parsed_res.get("status") == "SUCCESS":
                # Mark compliance
                parsed_res["compliant"] = bool(parsed_res.get("measured_error", 999999.0) <= bound)
                parsed_res["method"] = m
                leaderboard.append(parsed_res)
            else:
                logger.warning("Tournament worker for %s returned non-zero (%d): %s", m, proc.returncode, content[-300:] if content else "")
                leaderboard.append({
                    "method": m,
                    "status": "FAILED",
                    "initial_area": initial_area,
                    "final_area": initial_area,
                    "area_savings_percent": 0.0,
                    "measured_error": 999999.0,
                    "compliant": False,
                    "error": content[-500:] if content else "Unknown error",
                })

        # Select champion: among compliant candidates, minimum area wins
        compliant_candidates = [c for c in leaderboard if c.get("status") == "SUCCESS" and c.get("compliant")]

        if compliant_candidates:
            # Sort by final_area ascending (lowest area champion)
            compliant_candidates.sort(key=lambda c: (c["final_area"], c["measured_error"]))
            champion = compliant_candidates[0]
            logger.info("Tournament Champion (Compliant): %s (area=%.2f, savings=%.2f%%)",
                        champion["method"], champion["final_area"], champion["area_savings_percent"])
        else:
            # Fallback: candidate with lowest measured error
            leaderboard.sort(key=lambda c: c.get("measured_error", float("inf")))
            champion = leaderboard[0]
            logger.warning("No candidate met bound %.6f! Selected lowest-error fallback: %s (err=%.6f)",
                           bound, champion["method"], champion.get("measured_error", 999999.0))

        # Copy champion netlist to output
        final_dest = champion.get("approx_netlist") or champion.get("netlist_path")
        if out_approx_path and final_dest and Path(final_dest).exists():
            out_p = Path(out_approx_path).resolve()
            out_p.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(final_dest, out_p)
            final_dest = str(out_p)

        elapsed = time.time() - t_start

        return {
            "status": "SUCCESS",
            "topmodule": topmodule,
            "method": "auto",
            "champion_method": champion["method"],
            "metric": metric_normalized,
            "bound": bound,
            "measured_error": champion["measured_error"],
            "pruned_nodes_count": champion.get("pruned_nodes_count", 0),
            "pruned_nodes": champion.get("pruned_nodes", []),
            "initial_area": initial_area,
            "final_area": champion["final_area"],
            "area_savings_percent": champion["area_savings_percent"],
            "approx_netlist": final_dest,
            "leaderboard": leaderboard,
            "tournament_runtime_s": round(elapsed, 2),
        }

    def _finalize_single_result(
        self,
        candidate_res: Dict[str, Any],
        topmodule: str,
        metric_normalized: str,
        bound: float,
        initial_area: float,
        out_approx_path: Optional[str | Path],
    ) -> Dict[str, Any]:
        """Wrap single algorithm execution into standard return format."""
        final_dest = candidate_res.get("netlist_path")
        if out_approx_path and final_dest and Path(final_dest).exists():
            out_p = Path(out_approx_path).resolve()
            out_p.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(final_dest, out_p)
            final_dest = str(out_p)

        return {
            "status": candidate_res.get("status", "SUCCESS"),
            "topmodule": topmodule,
            "method": candidate_res.get("method"),
            "champion_method": candidate_res.get("method"),
            "metric": metric_normalized,
            "bound": bound,
            "measured_error": candidate_res.get("measured_error", 0.0),
            "pruned_nodes_count": candidate_res.get("pruned_nodes_count", 0),
            "pruned_nodes": candidate_res.get("pruned_nodes", []),
            "initial_area": initial_area,
            "final_area": candidate_res.get("final_area", initial_area),
            "area_savings_percent": candidate_res.get("area_savings_percent", 0.0),
            "approx_netlist": final_dest,
            "leaderboard": [candidate_res],
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="AxLS Approximation Bridge CLI")
    parser.add_argument("-i", "--input", required=True, help="Input extracted cone Verilog")
    parser.add_argument("-m", "--metric", default="med", help="Target error metric (med, mred, wce, er)")
    parser.add_argument("-b", "--bound", type=float, default=0.05, help="Maximum error bound")
    parser.add_argument("-a", "--method", default="auto", choices=["auto", "inouts", "probprun", "decisiontree"], help="Approximation backend algorithm")
    parser.add_argument("--lsb-width", type=int, default=None, help="LSB bit-width to restrict pruning")
    parser.add_argument("-t", "--tech", default="NanGate15nm", help="Standard cell tech library")
    parser.add_argument("--target", default="asic", choices=["asic", "fpga"], help="Target architecture (asic, fpga)")
    parser.add_argument("--fpga-family", default="xc7", help="Target FPGA family (default: xc7)")
    parser.add_argument("--fpga-device", default="xc7a35t", help="Target FPGA device (default: xc7a35t)")
    parser.add_argument("--allow-dsp", action="store_true", help="Allow DSP slice inference on FPGA")
    parser.add_argument("-s", "--samples", type=int, default=500, help="Simulation samples")
    parser.add_argument("--trace-hex", default=None, help="Path to realistic datapath trace .hex file")
    parser.add_argument("--work-dir", default=None, help="Working directory for intermediate artifacts")
    parser.add_argument("-o", "--output", default=None, help="Output approximated Verilog path")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging")

    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)

    bridge = AxlsBridge(
        cone_verilog_path=args.input,
        tech=args.tech,
        samples=args.samples,
        work_dir=args.work_dir,
        trace_hex_path=args.trace_hex,
        target=args.target,
        fpga_family=args.fpga_family,
        fpga_device=args.fpga_device,
        fpga_nodsp=not args.allow_dsp,
    )
    result = bridge.optimize(
        metric=args.metric,
        bound=args.bound,
        lsb_width=args.lsb_width,
        method=args.method,
        out_approx_path=args.output,
        trace_hex_path=args.trace_hex,
        isolated=False,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
