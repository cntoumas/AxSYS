"""Standard-Cell Power Estimation Module for Approximate Computing EDA.

Parses technology Liberty (.lib) models to compute cycle-accurate static (leakage)
and dynamic (switching) power dissipation for gate-level netlists.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("power_estimator")

LIB_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "third_party" / "AxLS" / "templates"
DEFAULT_LIB = LIB_TEMPLATES_DIR / "NanGate15nm.lib"


class PowerEstimator:
    """Estimates static leakage and dynamic switching power from mapped gate netlists."""

    def __init__(
        self,
        tech: str = "NanGate15nm",
        lib_path: Optional[str | Path] = None,
        vdd: float = 0.8,
        clk_mhz: float = 100.0,
        default_alpha: float = 0.20,
    ):
        self.tech = tech
        self.vdd = vdd
        self.clk_mhz = clk_mhz
        self.default_alpha = default_alpha

        if lib_path:
            self.lib_path = Path(lib_path).resolve()
        else:
            cand = LIB_TEMPLATES_DIR / f"{tech}.lib"
            self.lib_path = cand.resolve() if cand.is_file() else DEFAULT_LIB

        self.cell_models: Dict[str, Dict[str, float]] = {}
        if self.lib_path.exists():
            self._parse_liberty()
        else:
            logger.warning("Technology Liberty file not found at: %s", self.lib_path)

    def _parse_liberty(self) -> None:
        """Parse cell area, leakage power, and pin capacitances from Liberty (.lib)."""
        content = self.lib_path.read_text(encoding="utf-8")
        cell_matches = list(re.finditer(r"cell\s*\(\s*([A-Za-z0-9_]+)\s*\)\s*\{", content))

        for i, m in enumerate(cell_matches):
            cell_name = m.group(1)
            start = m.start()
            end = cell_matches[i + 1].start() if i + 1 < len(cell_matches) else len(content)
            cell_text = content[start:end]

            # Area in um^2
            area_m = re.search(r"area\s*:\s*([\d\.]+);", cell_text)
            area = float(area_m.group(1)) if area_m else 0.0

            # Cell leakage power (Liberty default unit is 1pW in NanGate15nm)
            leak_m = re.search(r"cell_leakage_power\s*:\s*([\d\.]+);", cell_text)
            leakage_pw = float(leak_m.group(1)) if leak_m else 0.0

            # Input pin capacitances in fF
            pin_caps = re.findall(
                r"pin\s*\(\s*([A-Za-z0-9_]+)\s*\)\s*\{[^}]*direction\s*:\s*input[^}]*capacitance\s*:\s*([\d\.]+);",
                cell_text,
            )
            total_pin_cap_ff = sum(float(cap) for _, cap in pin_caps)

            self.cell_models[cell_name] = {
                "area": area,
                "leakage_uw": leakage_pw / 1e6,  # Convert pW -> uW
                "pin_cap_ff": total_pin_cap_ff,
            }
        logger.debug("Loaded %d cell models from %s", len(self.cell_models), self.lib_path.name)

    def evaluate_netlist(
        self,
        netlist_path: str | Path,
        alpha: Optional[float] = None,
        vdd: Optional[float] = None,
        clk_mhz: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Compute static leakage, dynamic switching, and total power for a gate netlist."""
        path = Path(netlist_path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"Netlist file not found: {path}")

        act_alpha = alpha if alpha is not None else self.default_alpha
        act_vdd = vdd if vdd is not None else self.vdd
        act_f_mhz = clk_mhz if clk_mhz is not None else self.clk_mhz

        text = path.read_text(encoding="utf-8")
        cells = re.findall(r"\b([A-Z0-9_]+_X\d+)\s+([a-zA-Z0-9_]+)\s*\(", text)
        counts = Counter([c[0] for c in cells])

        total_cells = sum(counts.values())
        total_area = 0.0
        total_leakage_uw = 0.0
        total_cap_ff = 0.0

        for ctype, count in counts.items():
            if ctype in self.cell_models:
                model = self.cell_models[ctype]
                total_area += model["area"] * count
                total_leakage_uw += model["leakage_uw"] * count
                total_cap_ff += model["pin_cap_ff"] * count

        # P_dyn (uW) = 0.5 * V^2 * f_clk * C_total * alpha
        # C_load in fF (1e-15 F), f in MHz (1e6 Hz), P_dyn in uW (1e6 W) -> factor is 1e-3
        total_dyn_uw = 0.5 * (act_vdd ** 2) * act_f_mhz * total_cap_ff * act_alpha * 1e-3
        total_power_uw = total_leakage_uw + total_dyn_uw

        return {
            "netlist": str(path),
            "cell_count": total_cells,
            "cell_area_um2": round(total_area, 3),
            "leakage_power_uw": round(total_leakage_uw, 4),
            "dynamic_power_uw": round(total_dyn_uw, 4),
            "total_power_uw": round(total_power_uw, 4),
            "total_capacitance_ff": round(total_cap_ff, 2),
            "supply_voltage_v": act_vdd,
            "clock_frequency_mhz": act_f_mhz,
            "activity_factor": act_alpha,
            "cell_breakdown": dict(counts),
        }

    def compare_power(
        self,
        exact_netlist: str | Path,
        approx_netlist: str | Path,
        alpha: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Calculate differential power and area metrics between exact baseline and approx."""
        exact_eval = self.evaluate_netlist(exact_netlist, alpha=alpha)
        approx_eval = self.evaluate_netlist(approx_netlist, alpha=alpha)

        base_total = exact_eval["total_power_uw"]
        approx_total = approx_eval["total_power_uw"]
        base_leak = exact_eval["leakage_power_uw"]
        approx_leak = approx_eval["leakage_power_uw"]
        base_dyn = exact_eval["dynamic_power_uw"]
        approx_dyn = approx_eval["dynamic_power_uw"]
        base_area = exact_eval["cell_area_um2"]
        approx_area = approx_eval["cell_area_um2"]

        total_savings = ((base_total - approx_total) / base_total * 100.0) if base_total > 0 else 0.0
        leak_savings = ((base_leak - approx_leak) / base_leak * 100.0) if base_leak > 0 else 0.0
        dyn_savings = ((base_dyn - approx_dyn) / base_dyn * 100.0) if base_dyn > 0 else 0.0
        area_savings = ((base_area - approx_area) / base_area * 100.0) if base_area > 0 else 0.0

        return {
            "exact": exact_eval,
            "approximate": approx_eval,
            "total_power_savings_percent": round(total_savings, 2),
            "leakage_power_savings_percent": round(leak_savings, 2),
            "dynamic_power_savings_percent": round(dyn_savings, 2),
            "area_savings_percent": round(area_savings, 2),
            "cells_pruned": exact_eval["cell_count"] - approx_eval["cell_count"],
        }
