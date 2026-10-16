"""RTLIL Relaxability Inference and Submodule Extractor using Pyosys.

Traverses IEEE 1364/1800 annotated Verilog designs in Pyosys RTLIL,
computes safe combinational cones (C_safe = C_relax \\ C_precise),
and partitions the design into an isolated combinational submodule and top wrapper
using the Yosys `submod` pass.
"""

from __future__ import annotations

import argparse
import json
import logging
from collections import Counter, deque
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from pyosys import libyosys as ys

logger = logging.getLogger("cone_extractor")


def decode_attr(attr_val: Any, default: Any = None) -> Any:
    """Decode a Yosys RTLIL Const attribute into a Python primitive."""
    if attr_val is None:
        return default
    try:
        s = attr_val.decode_string()
        if s and all(c.isprintable() for c in s):
            return s
    except Exception:
        pass
    if hasattr(attr_val, "as_int"):
        try:
            return attr_val.as_int()
        except Exception:
            pass
    try:
        return attr_val.as_string()
    except Exception:
        return default


class DSU:
    """Disjoint Set Union for wire bit alias resolution."""

    def __init__(self) -> None:
        self.parent: Dict[Tuple[str, int], Tuple[str, int]] = {}

    def find(self, item: Tuple[str, int]) -> Tuple[str, int]:
        if item not in self.parent:
            self.parent[item] = item
        if self.parent[item] != item:
            self.parent[item] = self.find(self.parent[item])
        return self.parent[item]

    def union(self, a: Tuple[str, int], b: Tuple[str, int]) -> None:
        ra = self.find(a)
        rb = self.find(b)
        if ra != rb:
            self.parent[ra] = rb


class ConeExtractor:
    """Extracts safe approximate combinational cones from annotated Verilog."""

    def __init__(self, verilog_path: str | Path, top_module: Optional[str] = None):
        self.verilog_path = Path(verilog_path).resolve()
        self.top_module_name = top_module
        self.design = ys.Design()

    def elaborate(self) -> ys.Module:
        """Elaborate behavioral blocks into RTLIL netlist."""
        top_cmd = f"hierarchy -check -top {self.top_module_name}" if self.top_module_name else "hierarchy -check -auto-top"
        cmd = f"read_verilog -sv {self.verilog_path}; {top_cmd}; proc; opt_expr; opt_clean"
        logger.info("Executing Pyosys elaboration: %s", cmd)
        ys.run_pass(cmd, self.design)

        top = self.design.top_module()
        if top is None:
            raise RuntimeError(f"Could not find top module in {self.verilog_path}")
        self.top_module_name = top.name.str().lstrip("\\")
        return top

    @staticmethod
    def is_sequential_cell(cell: ys.Cell) -> bool:
        """Check if cell is a sequential element (FF, Latch, or Memory)."""
        if cell.is_builtin_ff() or cell.is_mem_cell():
            return True
        cell_type = cell.type.str()
        seq_prefixes = (
            "$dff", "$adff", "$sdff", "$aldff", "$sdffe", "$sdffce",
            "$dlatch", "$sr", "$ff", "$mem", "$_DFF", "$_DLATCH"
        )
        return cell_type.startswith(seq_prefixes)

    def extract_safe_cone(
        self,
        submod_tag: str = "axc_cone_0",
        out_submod_path: Optional[str | Path] = None,
        out_top_path: Optional[str | Path] = None,
        out_meta_path: Optional[str | Path] = None,
    ) -> Dict[str, Any]:
        """Perform relaxability analysis and partition the safe cone."""
        top = self.elaborate()
        modules_before = set(m.str() for m in self.design.modules_.keys())

        dsu = DSU()

        # 1. Resolve wire-to-wire aliases from top.connections()
        for conn in top.connections():
            lhs, rhs = conn[0], conn[1]
            for b_l, b_r in zip(lhs, rhs):
                if b_l.wire and b_r.wire:
                    dsu.union(
                        (b_l.wire.name.str(), b_l.offset),
                        (b_r.wire.name.str(), b_r.offset)
                    )

        # 2. Build cell adjacency maps
        bit_drivers: Dict[Tuple[str, int], str] = {}
        cell_inputs: Dict[str, Set[Tuple[str, int]]] = {}
        cell_outputs: Dict[str, Set[Tuple[str, int]]] = {}
        seq_cells: Set[str] = set()

        for cname_id, cell in top.cells_.items():
            cname = cname_id.str()
            is_seq = self.is_sequential_cell(cell)
            if is_seq:
                seq_cells.add(cname)
            cell_inputs[cname] = set()
            cell_outputs[cname] = set()

            for pname, sig in cell.connections().items():
                is_out = cell.output(pname)
                is_in = cell.input(pname)
                for b in sig:
                    if b.wire:
                        c_b = dsu.find((b.wire.name.str(), b.offset))
                        if is_out:
                            cell_outputs[cname].add(c_b)
                            if not is_seq:
                                bit_drivers[c_b] = cname
                        if is_in:
                            cell_inputs[cname].add(c_b)

        # 3. Collect relaxed and precise seed signals
        relax_seeds: Set[Tuple[str, int]] = set()
        precise_seeds: Set[Tuple[str, int]] = set()
        relaxed_signals_meta: List[Dict[str, Any]] = []

        attr_relax_id = ys.IdString(r"\axc_relax")
        attr_precise_id = ys.IdString(r"\axc_precise")
        attr_metric_id = ys.IdString(r"\axc_metric")
        attr_bound_id = ys.IdString(r"\axc_bound")
        attr_lsb_id = ys.IdString(r"\axc_lsb_width")

        for wname_id, wire in top.wires_.items():
            wname = wname_id.str()
            has_relax = wire.has_attribute(attr_relax_id)
            has_precise = wire.has_attribute(attr_precise_id)

            if has_relax:
                metric = "MED"
                if wire.has_attribute(attr_metric_id):
                    metric = str(decode_attr(wire.attributes[attr_metric_id], "MED"))

                bound = 0.05
                if wire.has_attribute(attr_bound_id):
                    bound_val = decode_attr(wire.attributes[attr_bound_id], 0.05)
                    try:
                        bound = float(bound_val)
                    except (ValueError, TypeError):
                        bound = 0.05

                lsb_w = wire.width
                if wire.has_attribute(attr_lsb_id):
                    lsb_w_val = decode_attr(wire.attributes[attr_lsb_id], wire.width)
                    try:
                        lsb_w = int(lsb_w_val)
                    except (ValueError, TypeError):
                        lsb_w = wire.width

                relaxed_signals_meta.append({
                    "wire": wname.lstrip("\\"),
                    "width": wire.width,
                    "metric": metric,
                    "bound": bound,
                    "lsb_width": min(lsb_w, wire.width),
                })

                for i in range(min(lsb_w, wire.width)):
                    relax_seeds.add(dsu.find((wname, i)))

            if has_precise:
                for i in range(wire.width):
                    precise_seeds.add(dsu.find((wname, i)))
            elif wire.port_output and not has_relax:
                # Unannotated primary outputs default to precise
                for i in range(wire.width):
                    precise_seeds.add(dsu.find((wname, i)))

        # 4. Handle sequential cells:
        # - Control pins (CLK, ARST, SRST, EN, etc.) are always protected (added to precise_seeds).
        # - If a FF's output Q has relax_seeds, propagate those relax_seeds to the corresponding bits of D,
        #   and do NOT add D to precise_seeds.
        # - If a FF's output Q is unrelaxed / precise, add its D bits to precise_seeds.
        for cname in seq_cells:
            cell = top.cell(ys.IdString(cname))
            relaxed_q_indices: Set[int] = set()
            for pname, sig in cell.connections().items():
                if cell.output(pname):
                    for idx, b in enumerate(sig):
                        if b.wire and dsu.find((b.wire.name.str(), b.offset)) in relax_seeds:
                            relaxed_q_indices.add(idx)

            for pname, sig in cell.connections().items():
                if cell.input(pname):
                    pname_str = pname.str().upper()
                    is_data_in = pname_str in (r"\D", r"\DATA")
                    for idx, b in enumerate(sig):
                        if b.wire:
                            canon_b = dsu.find((b.wire.name.str(), b.offset))
                            if is_data_in and idx in relaxed_q_indices:
                                relax_seeds.add(canon_b)
                            else:
                                precise_seeds.add(canon_b)

        if not relax_seeds:
            logger.warning("No (* axc_relax *) signals found in design %s.", self.top_module_name)
            return {
                "top_module": self.top_module_name,
                "status": "NO_RELAX_SIGNALS",
                "safe_cells": [],
                "relaxed_signals": [],
            }

        # 5. Backward BFS for C_precise
        c_precise: Set[str] = set()
        queue = deque(precise_seeds)
        visited = set(queue)
        while queue:
            b = queue.popleft()
            if b in bit_drivers:
                cell_name = bit_drivers[b]
                if cell_name not in c_precise:
                    c_precise.add(cell_name)
                    for in_b in cell_inputs[cell_name]:
                        if in_b not in visited:
                            visited.add(in_b)
                            queue.append(in_b)

        # 6. Backward BFS for C_relax
        c_relax: Set[str] = set()
        queue = deque(relax_seeds)
        visited = set(queue)
        while queue:
            b = queue.popleft()
            if b in bit_drivers:
                cell_name = bit_drivers[b]
                if cell_name not in c_relax:
                    c_relax.add(cell_name)
                    for in_b in cell_inputs[cell_name]:
                        if in_b not in visited:
                            visited.add(in_b)
                            queue.append(in_b)

        # 7. Safe candidate set
        c_safe = c_relax - c_precise
        logger.info(
            "Cone analysis complete: |C_relax|=%d, |C_precise|=%d, |C_safe|=%d",
            len(c_relax), len(c_precise), len(c_safe)
        )

        if not c_safe:
            logger.warning("Safe cell set is empty. Candidate logic was entirely tainted by precise signals.")
            return {
                "top_module": self.top_module_name,
                "status": "TAINTED_EMPTY_SAFE_SET",
                "safe_cells": [],
                "relaxed_signals": relaxed_signals_meta,
            }

        # Count cell types
        cell_types = Counter()
        for cname in c_safe:
            cell = top.cell(ys.IdString(cname))
            if cell:
                cell_types[cell.type.str()] += 1

        # 8. Tag cells with \submod attribute
        submod_attr_id = ys.IdString(r"\submod")
        for cname in c_safe:
            cell = top.cell(ys.IdString(cname))
            if cell:
                cell.set_string_attribute(submod_attr_id, submod_tag)

        # 9. Partition via submod pass
        ys.run_pass("submod; opt_clean", self.design)

        modules_after = set(m.str() for m in self.design.modules_.keys())
        new_modules = modules_after - modules_before
        if not new_modules:
            raise RuntimeError("Yosys submod pass failed to create a new submodule module.")

        created_submod_module = list(new_modules)[0]
        created_submod_name = created_submod_module.lstrip("\\")

        # Find instance in top module
        top = self.design.top_module()
        created_instance_name = None
        for cname_id, cell in top.cells_.items():
            if cell.type.str() == created_submod_module:
                created_instance_name = cname_id.str().lstrip("\\")
                break

        # Inspect ports of created submodule
        submod = self.design.module(ys.IdString(created_submod_module))
        input_ports = []
        output_ports = []
        for wname_id, wire in submod.wires_.items():
            if wire.port_input:
                input_ports.append({"name": wname_id.str().lstrip("\\"), "width": wire.width})
            if wire.port_output:
                output_ports.append({"name": wname_id.str().lstrip("\\"), "width": wire.width})

        # 10. Write output files if requested
        result_files: Dict[str, str] = {}

        if out_submod_path:
            out_submod_p = Path(out_submod_path).resolve()
            out_submod_p.parent.mkdir(parents=True, exist_ok=True)
            ys.run_pass(
                f"select -module {created_submod_name}; write_verilog -selected {out_submod_p}; select -clear",
                self.design
            )
            result_files["submodule_verilog"] = str(out_submod_p)

        if out_top_path:
            out_top_p = Path(out_top_path).resolve()
            out_top_p.parent.mkdir(parents=True, exist_ok=True)
            ys.run_pass(
                f"delete {created_submod_name}; write_verilog {out_top_p}",
                self.design
            )
            result_files["top_shell_verilog"] = str(out_top_p)

        meta_result: Dict[str, Any] = {
            "top_module": self.top_module_name,
            "status": "SUCCESS",
            "submodule_module": created_submod_name,
            "submodule_instance": created_instance_name or submod_tag,
            "num_safe_cells": len(c_safe),
            "safe_cells": sorted(list(c_safe)),
            "cell_types": dict(cell_types),
            "relaxed_signals": relaxed_signals_meta,
            "submodule_inputs": input_ports,
            "submodule_outputs": output_ports,
            "files": result_files,
        }

        if out_meta_path:
            out_meta_p = Path(out_meta_path).resolve()
            out_meta_p.parent.mkdir(parents=True, exist_ok=True)
            with open(out_meta_p, "w", encoding="utf-8") as f:
                json.dump(meta_result, f, indent=2)
            result_files["metadata_json"] = str(out_meta_p)

        return meta_result


def main() -> None:
    parser = argparse.ArgumentParser(description="Pyosys RTLIL Relaxability Cone Extractor")
    parser.add_argument("-i", "--input", required=True, help="Input annotated Verilog file")
    parser.add_argument("-t", "--top", default=None, help="Top module name (optional)")
    parser.add_argument("--submod-tag", default="axc_cone_0", help="Submodule tag prefix (default: axc_cone_0)")
    parser.add_argument("--out-submod", default=None, help="Path for isolated submodule Verilog")
    parser.add_argument("--out-top", default=None, help="Path for top module shell Verilog")
    parser.add_argument("--out-meta", default=None, help="Path for metadata JSON output")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging")

    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)

    extractor = ConeExtractor(verilog_path=args.input, top_module=args.top)
    result = extractor.extract_safe_cone(
        submod_tag=args.submod_tag,
        out_submod_path=args.out_submod,
        out_top_path=args.out_top,
        out_meta_path=args.out_meta,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
