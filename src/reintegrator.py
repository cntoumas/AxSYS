"""Design Re-integrator.

Stitches the extracted parent shell (top_shell.v) and the approximated
submodule gate netlist (approx_cone.v) into a unified netlist (final_approx_top.v)
ready for physical design and verification.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from pyosys import libyosys as ys

logger = logging.getLogger("reintegrator")

TECH_V_DEFAULT = Path(__file__).resolve().parent.parent / "third_party" / "AxLS" / "templates" / "NanGate15nm.v"


class Reintegrator:
    """Re-integrates parent wrapper shell with approximated subcircuits."""

    def __init__(
        self,
        top_shell_path: str | Path,
        approx_cone_path: str | Path,
        tech_verilog_path: Optional[str | Path] = None,
    ):
        self.top_shell_path = Path(top_shell_path).resolve()
        self.approx_cone_path = Path(approx_cone_path).resolve()
        self.tech_v = Path(tech_verilog_path).resolve() if tech_verilog_path else TECH_V_DEFAULT

    def reintegrate(self, out_final_path: str | Path, flatten: bool = False) -> Dict[str, Any]:
        """Combine top shell and approximate submodule into unified Verilog."""
        out_p = Path(out_final_path).resolve()
        out_p.parent.mkdir(parents=True, exist_ok=True)

        design = ys.Design()

        tech_cmd = f"read_verilog {self.tech_v}; " if self.tech_v.exists() else ""
        flatten_cmd = "flatten; opt_clean; " if flatten else ""
        cmd = (
            f"read_verilog {self.top_shell_path} {self.approx_cone_path}; "
            f"{tech_cmd}"
            f"hierarchy -check -auto-top; "
            f"proc; opt_clean; "
            f"{flatten_cmd}"
            f"write_verilog {out_p}"
        )

        logger.info("Executing Yosys re-integration: %s", cmd)
        ys.run_pass(cmd, design)

        top_mod = design.top_module()
        top_name = top_mod.name.str().lstrip("\\") if top_mod else "unknown"

        return {
            "status": "SUCCESS",
            "top_module": top_name,
            "final_netlist": str(out_p),
            "flattened": flatten,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Axc Design Re-integrator")
    parser.add_argument("--top-shell", required=True, help="Path to top_shell.v")
    parser.add_argument("--approx-cone", required=True, help="Path to approx_cone.v")
    parser.add_argument("--tech-v", default=None, help="Path to standard cell Verilog library")
    parser.add_argument("-o", "--output", required=True, help="Path for final_approx_top.v")
    parser.add_argument("--flatten", action="store_true", help="Flatten hierarchy into a single module")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging")

    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)

    reintegrator = Reintegrator(
        top_shell_path=args.top_shell,
        approx_cone_path=args.approx_cone,
        tech_verilog_path=args.tech_v,
    )
    result = reintegrator.reintegrate(out_final_path=args.output, flatten=args.flatten)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
