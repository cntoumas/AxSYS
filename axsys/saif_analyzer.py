"""SAIF (Switching Activity Interchange Format) Vector-Driven Power Analyzer for AxSYS.

Simulates gate-level netlists with cycle-accurate stimulus vectors, extracts bit-level
toggle counts and activity factors from Value Change Dump (VCD) waveforms, exports
industry-standard IEEE SAIF 2.0 files, and computes realistic switching and leakage power
based on standard-cell Liberty (.lib) models.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pyosys import libyosys as ys

logger = logging.getLogger("axsys.saif")


class SaifPowerAnalyzer:
    """Evaluates standard-cell power dissipation using real vector switching activity (SAIF)."""

    def __init__(
        self,
        lib_path: str | Path,
        tech_vlog: Optional[str | Path] = None,
        vdd: float = 0.8,
        clk_mhz: float = 200.0,
    ) -> None:
        self.lib_path = Path(lib_path).resolve()
        if not self.lib_path.exists():
            raise FileNotFoundError(f"Liberty file not found: {self.lib_path}")

        self.tech_vlog = Path(tech_vlog).resolve() if tech_vlog else None
        self.vdd = vdd
        self.clk_mhz = clk_mhz
        self.cell_models: Dict[str, Dict[str, Any]] = {}
        self._parse_liberty()

    def _parse_liberty(self) -> None:
        """Parse cell area, leakage power, and individual pin capacitances from Liberty (.lib)."""
        content = self.lib_path.read_text(encoding="utf-8")
        cell_matches = list(re.finditer(r"cell\s*\(\s*([A-Za-z0-9_]+)\s*\)\s*\{", content))

        for i, m in enumerate(cell_matches):
            cell_name = m.group(1)
            start = m.start()
            end = cell_matches[i + 1].start() if i + 1 < len(cell_matches) else len(content)
            cell_text = content[start:end]

            area_m = re.search(r"area\s*:\s*([\d\.]+);", cell_text)
            area = float(area_m.group(1)) if area_m else 0.0

            leak_m = re.search(r"cell_leakage_power\s*:\s*([\d\.]+);", cell_text)
            leakage_pw = float(leak_m.group(1)) if leak_m else 0.0

            # Parse individual input pin capacitances
            pin_matches = list(re.finditer(r"pin\s*\(\s*([A-Za-z0-9_]+)\s*\)\s*\{", cell_text))
            input_pins: Dict[str, float] = {}
            for j, pm in enumerate(pin_matches):
                pname = pm.group(1)
                pstart = pm.start()
                pend = pin_matches[j + 1].start() if j + 1 < len(pin_matches) else len(cell_text)
                pbody = cell_text[pstart:pend]
                if re.search(r"direction\s*:\s*input\s*;", pbody):
                    cap_m = re.search(r"capacitance\s*:\s*([\d\.]+);", pbody)
                    cap = float(cap_m.group(1)) if cap_m else 0.5
                    input_pins[pname] = cap

            self.cell_models[cell_name] = {
                "area": area,
                "leakage_uw": leakage_pw / 1e6,  # Convert pW -> uW
                "input_pins": input_pins,
                "total_pin_cap_ff": sum(input_pins.values()),
            }

        logger.debug("Loaded %d cell models from %s", len(self.cell_models), self.lib_path.name)

    def _inspect_ports(self, netlist_path: Path, top_module: str) -> Dict[str, List[Dict[str, Any]]]:
        """Inspect input and output ports of the top module using Pyosys."""
        design = ys.Design()
        ys.run_pass(f"read_verilog -sv {netlist_path}", design)
        top = design.module(ys.IdString(f"\\{top_module}"))
        if not top:
            top = design.top_module()
        if not top:
            raise ValueError(f"Could not find top module {top_module} in {netlist_path}")

        inputs = []
        outputs = []
        for wname_id, wire in top.wires_.items():
            name = wname_id.str().lstrip("\\")
            if wire.port_input:
                inputs.append({"name": name, "width": wire.width, "is_signed": bool(wire.is_signed)})
            if wire.port_output:
                outputs.append({"name": name, "width": wire.width, "is_signed": bool(wire.is_signed)})
        return {"inputs": inputs, "outputs": outputs}

    def parse_netlist_loads(self, netlist_path: Path) -> Tuple[Dict[str, float], float, Dict[str, int]]:
        """Compute the fanout load capacitance for each net in the netlist (in fF)."""
        text = netlist_path.read_text(encoding="utf-8")

        inst_pattern = re.compile(
            r"\b([A-Z0-9_]+_X\d+)\s+([a-zA-Z0-9_]+)\s*\((.*?)\);",
            re.DOTALL,
        )

        net_load_ff: Dict[str, float] = defaultdict(float)
        cell_counts: Dict[str, int] = defaultdict(int)
        total_leakage_uw = 0.0

        for match in inst_pattern.finditer(text):
            ctype = match.group(1)
            conns_str = match.group(3)

            cell_counts[ctype] += 1
            cmodel = self.cell_models.get(ctype, {"area": 0.0, "leakage_uw": 0.0, "input_pins": {}})
            total_leakage_uw += cmodel["leakage_uw"]

            # Parse pin connections: .PIN(NET)
            pin_conns = re.findall(r"\.([A-Za-z0-9_]+)\s*\(\s*([a-zA-Z0-9_\[\]]+)\s*\)", conns_str)
            for pin, net in pin_conns:
                if pin in cmodel["input_pins"]:
                    net_load_ff[net] += cmodel["input_pins"][pin]

        # Add estimated wire parasitic capacitance (0.5 fF per connection)
        for net in list(net_load_ff.keys()):
            net_load_ff[net] += 0.5

        return dict(net_load_ff), total_leakage_uw, dict(cell_counts)

    def parse_vcd_activity(
        self,
        vcd_path: Path,
        target_scope: str,
        num_cycles: int,
    ) -> Tuple[Dict[str, float], Dict[str, int]]:
        """Parse VCD and return per-net activity factor (alpha) and toggle counts."""
        alias_to_names: Dict[str, List[str]] = defaultdict(list)
        current_scope_parts: List[str] = []

        toggle_counts: Dict[str, int] = defaultdict(int)
        last_values: Dict[str, str] = {}

        with open(vcd_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                if line.startswith("$scope"):
                    parts = line.split()
                    if len(parts) >= 3:
                        current_scope_parts.append(parts[2])
                    continue
                elif line.startswith("$upscope"):
                    if current_scope_parts:
                        current_scope_parts.pop()
                    continue
                elif line.startswith("$var"):
                    parts = line.split()
                    if len(parts) >= 5:
                        alias = parts[3]
                        var_name = parts[4]
                        scope_str = ".".join(current_scope_parts)
                        if target_scope in scope_str:
                            alias_to_names[alias].append(var_name)
                    continue
                elif line.startswith("$enddefinitions"):
                    break

            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue

                if line.startswith("b"):
                    parts = line.split()
                    if len(parts) >= 2:
                        val = parts[0][1:]
                        alias = parts[1]
                        if alias in alias_to_names:
                            old = last_values.get(alias, "")
                            if old and old != val:
                                toggle_counts[alias] += 1
                            last_values[alias] = val
                elif line[0] in ("0", "1", "x", "z"):
                    val = line[0]
                    alias = line[1:]
                    if alias in alias_to_names:
                        old = last_values.get(alias, "")
                        if old and old != val:
                            toggle_counts[alias] += 1
                        last_values[alias] = val

        wire_toggles: Dict[str, int] = {}
        wire_alphas: Dict[str, float] = {}

        for alias, names in alias_to_names.items():
            toggles = toggle_counts.get(alias, 0)
            alpha = toggles / (2.0 * num_cycles) if num_cycles > 0 else 0.0
            for name in names:
                wire_toggles[name] = toggles
                wire_alphas[name] = min(alpha, 1.0)

        return wire_alphas, wire_toggles

    def generate_saif(
        self,
        saif_path: Path,
        module_name: str,
        wire_toggles: Dict[str, int],
        num_cycles: int,
        clk_period_ns: float,
    ) -> None:
        """Write industry-standard SAIF 2.0 format."""
        duration_ns = num_cycles * clk_period_ns
        lines = [
            "(SAIFILE",
            '(SAIFVERSION "2.0")',
            '(DIRECTION "backward")',
            f'(DESIGN "{module_name}")',
            '(VENDOR "AxSYS / Open-Source EDA")',
            '(PROGRAM_NAME "AxSYS SAIF Generator")',
            '(VERSION "1.0")',
            "(DIVIDER / )",
            "(TIMESCALE 1 ns)",
            f"(DURATION {duration_ns:.2f})",
            f"(INSTANCE {module_name}",
            "   (NET",
        ]

        t_half = duration_ns / 2.0
        for wire, tc in sorted(wire_toggles.items()):
            lines.append(f"      ({wire}")
            lines.append(f"         (T0 {t_half:.1f}) (T1 {t_half:.1f}) (TX 0.0)")
            lines.append(f"         (TC {tc}) (IG 0)")
            lines.append("      )")

        lines.extend([
            "   )",
            ")",
            ")",
        ])
        saif_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def run_simulation(
        self,
        netlist_path: Path,
        top_module: str,
        work_dir: Path,
        ports_info: Dict[str, List[Dict[str, Any]]],
        num_cycles: int = 1000,
        clk_period_ns: float = 5.0,
    ) -> Path:
        """Compile netlist with Icarus Verilog, execute deterministic stimulus, and dump VCD."""
        work_dir.mkdir(parents=True, exist_ok=True)
        vcd_path = work_dir / f"{top_module}.vcd"

        inputs = ports_info["inputs"]
        outputs = ports_info["outputs"]

        clk_names = {"clk", "clock"}
        rst_names = {"rst", "rst_n", "reset", "reset_n"}

        tb_lines = [
            "`timescale 1ns/1ps",
            "",
            "module tb_saif;",
            "  reg clk;",
            "  reg rst_n;",
        ]

        # Declare input regs
        for inp in inputs:
            name = inp["name"]
            width = inp["width"]
            is_signed = inp.get("is_signed", False)
            if name not in clk_names and name not in rst_names:
                signed_str = "signed " if is_signed else ""
                range_str = f"[{width-1}:0] " if width > 1 else ""
                tb_lines.append(f"  reg {signed_str}{range_str}{name};")

        # Declare output wires
        for out in outputs:
            name = out["name"]
            width = out["width"]
            is_signed = out.get("is_signed", False)
            signed_str = "signed " if is_signed else ""
            range_str = f"[{width-1}:0] " if width > 1 else ""
            tb_lines.append(f"  wire {signed_str}{range_str}{name};")

        # Instantiate DUT
        tb_lines.extend([
            "",
            f"  {top_module} dut (",
        ])
        conns = []
        for inp in inputs:
            name = inp["name"]
            conns.append(f"    .{name}({name})")
        for out in outputs:
            name = out["name"]
            conns.append(f"    .{name}({name})")
        tb_lines.append(",\n".join(conns))
        tb_lines.extend([
            "  );",
            "",
            f"  always #({clk_period_ns / 2.0}) clk = ~clk;",
            "",
            "  integer i;",
            "  initial begin",
            f"    $dumpfile(\"{vcd_path}\");",
            "    $dumpvars(0, dut);",
            "",
            "    clk = 0;",
            "    rst_n = 0;",
        ])

        # Initialize input regs
        for inp in inputs:
            name = inp["name"]
            if name not in clk_names and name not in rst_names:
                tb_lines.append(f"    {name} = 0;")

        tb_lines.extend([
            "    #20;",
            "    rst_n = 1;",
            "",
            f"    for (i = 0; i < {num_cycles}; i = i + 1) begin",
            "      @(posedge clk);",
        ])

        # Stimulus per cycle
        for inp in inputs:
            name = inp["name"]
            if name not in clk_names and name not in rst_names:
                tb_lines.append(f"      {name} = $urandom;")

        tb_lines.extend([
            "    end",
            "",
            "    @(posedge clk);",
            "    #20;",
            "    $finish(0);",
            "  end",
            "endmodule",
        ])

        tb_path = work_dir / "tb_saif.v"
        tb_path.write_text("\n".join(tb_lines) + "\n", encoding="utf-8")

        sim_vvp = work_dir / "sim.vvp"
        netlist_text = netlist_path.read_text(encoding="utf-8")
        has_cell_defs = "module INV_X1" in netlist_text or "module AND2_X1" in netlist_text

        cmd = [
            "iverilog",
            "-g2012",
            "-DPRIMITIVES",
            "-o", str(sim_vvp),
            str(tb_path),
            str(netlist_path),
        ]
        if not has_cell_defs and self.tech_vlog and self.tech_vlog.exists():
            cmd.append(str(self.tech_vlog))

        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"iverilog compilation failed:\n{res.stderr}\n{res.stdout}")

        run_res = subprocess.run(["vvp", str(sim_vvp)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=work_dir)
        if run_res.returncode != 0:
            raise RuntimeError(f"vvp execution failed:\n{run_res.stderr}\n{run_res.stdout}")

        return vcd_path

    def evaluate_saif_power(
        self,
        netlist_path: Path,
        top_module: str,
        work_dir: Path,
        num_cycles: int = 1000,
    ) -> Dict[str, Any]:
        """Execute simulation, dump VCD, generate SAIF, and compute vector-driven power."""
        clk_period_ns = 1000.0 / self.clk_mhz
        ports_info = self._inspect_ports(netlist_path, top_module)

        vcd_path = self.run_simulation(netlist_path, top_module, work_dir, ports_info, num_cycles, clk_period_ns)
        net_loads_ff, total_leakage_uw, cell_counts = self.parse_netlist_loads(netlist_path)
        wire_alphas, wire_toggles = self.parse_vcd_activity(vcd_path, "dut", num_cycles)

        saif_path = work_dir / f"{top_module}.saif"
        self.generate_saif(saif_path, top_module, wire_toggles, num_cycles, clk_period_ns)

        # Dynamic power with vector-driven SAIF activity: P_dyn = sum(0.5 * V^2 * f * C_load * alpha)
        total_dyn_saif_uw = 0.0
        total_cap_ff = sum(net_loads_ff.values())
        matched_nets = 0

        for net, cap in net_loads_ff.items():
            alpha = wire_alphas.get(net, wire_alphas.get(f"\\{net}", 0.20))
            if net in wire_alphas:
                matched_nets += 1
            p_dyn_net = 0.5 * (self.vdd ** 2) * self.clk_mhz * cap * alpha * 1e-3
            total_dyn_saif_uw += p_dyn_net

        # Static 20% power for direct reference comparison
        static_alpha = 0.20
        total_dyn_static_uw = 0.5 * (self.vdd ** 2) * self.clk_mhz * total_cap_ff * static_alpha * 1e-3
        avg_alpha = sum(wire_alphas.values()) / len(wire_alphas) if wire_alphas else 0.0

        return {
            "netlist": str(netlist_path),
            "saif_path": str(saif_path),
            "total_cells": sum(cell_counts.values()),
            "total_nets": len(net_loads_ff),
            "matched_nets": matched_nets,
            "average_activity_factor": round(avg_alpha, 4),
            "total_capacitance_ff": round(total_cap_ff, 2),
            "leakage_power_uw": round(total_leakage_uw, 4),
            "static_dyn_power_uw": round(total_dyn_static_uw, 4),
            "static_total_power_uw": round(total_leakage_uw + total_dyn_static_uw, 4),
            "saif_dyn_power_uw": round(total_dyn_saif_uw, 4),
            "saif_total_power_uw": round(total_leakage_uw + total_dyn_saif_uw, 4),
        }

    def compare_exact_vs_approx(
        self,
        exact_netlist: Path,
        approx_netlist: Path,
        top_module: str,
        work_dir: Path,
        num_cycles: int = 1000,
    ) -> Dict[str, Any]:
        """Compute differential power and area metrics using vector-driven SAIF."""
        exact_res = self.evaluate_saif_power(exact_netlist, top_module, work_dir / "exact", num_cycles)
        approx_res = self.evaluate_saif_power(approx_netlist, top_module, work_dir / "approx", num_cycles)

        base_static = exact_res["static_total_power_uw"]
        app_static = approx_res["static_total_power_uw"]
        static_sav = ((base_static - app_static) / base_static * 100.0) if base_static > 0 else 0.0

        base_saif = exact_res["saif_total_power_uw"]
        app_saif = approx_res["saif_total_power_uw"]
        saif_sav = ((base_saif - app_saif) / base_saif * 100.0) if base_saif > 0 else 0.0

        base_dyn_saif = exact_res["saif_dyn_power_uw"]
        app_dyn_saif = approx_res["saif_dyn_power_uw"]
        dyn_saif_sav = ((base_dyn_saif - app_dyn_saif) / base_dyn_saif * 100.0) if base_dyn_saif > 0 else 0.0

        return {
            "top_module": top_module,
            "exact": exact_res,
            "approx": approx_res,
            "static_total_savings_percent": round(static_sav, 2),
            "saif_total_savings_percent": round(saif_sav, 2),
            "saif_dyn_savings_percent": round(dyn_saif_sav, 2),
            "pruned_cells": exact_res["total_cells"] - approx_res["total_cells"],
        }
